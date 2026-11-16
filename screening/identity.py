"""Reconcile the names this configuration creates against the names something else depends on.

Terraform owns the account's namespace. It creates the warehouses, the roles,
the databases and the user. Nothing else in this repository creates any of
them, and three other files spend them: the dbt profile names a role and a
warehouse and a database, the clone module names a source database, and the
workflow names environment variables and terraform variables.

No tool reads more than one of those files. `terraform validate` grades the
configuration against the provider schema and never opens the profile.
`dbt parse` resolves the adapter without opening a connection, so a warehouse
that does not exist parses exactly like one that does. The workflow is YAML
and the only thing that has ever executed it is this repository's own runner,
which cannot reach an account either.

So the namespace is spread over three files and the join between them is
performed by nobody until an apply, and an apply has never happened. This
module performs it. A name is CREATED when a resource block sets it. A name is
CONSUMED when something outside `infra/` would send it to Snowflake. The
reconciliation runs in both directions, because a consumed name that is not
created is a failure at connect time and a created name that nothing consumes
is a resource somebody pays for and nobody uses.

The reverse direction needs its complement written down or it fires on every
object that is reached by a human rather than by a file. That list is
`UNCONSUMED_ON_PURPOSE` and every entry carries its reason.
"""

import os
import re

from . import tfread

# `env_var('NAME', 'DEFAULT')` as dbt spells it. This reads one construct and
# it is not a YAML parser. The construct is the only place the profile names a
# Snowflake object, so a reader for it is complete over the question being
# asked, and a profile that moved an identity out of an env_var default would
# be invisible here. A check asserts the count this finds against the count of
# `env_var` occurrences in the file, so that move fails rather than passes.
ENV_DEFAULT = re.compile(r"env_var\(\s*'([A-Z][A-Z0-9_]*)'\s*,\s*'([^']*)'\s*\)")
ENV_ANY = re.compile(r"env_var\(")
# A workflow step's environment block, as `NAME: value` under an `env:` key.
# The name starts upper case, which is the convention every environment
# variable here follows, and may carry lower case after it, because a
# terraform variable is passed as TF_VAR_ plus the variable's own lower case
# name. An earlier spelling of this refused the lower case tail, so it matched
# none of the TF_VAR lines and the rule below reported every required variable
# as unsupplied including the four that were passed.
WORKFLOW_ENV = re.compile(r"^\s+([A-Z][A-Za-z0-9_]*):\s*(.*)$")
TF_VAR = re.compile(r"TF_VAR_([a-z][a-z0-9_]*)")
# An unquoted Snowflake identifier this repository writes. Folded upper case
# with the project prefix, which is what every object here is named.
OBJECT_NAME = re.compile(r"\bSCREENING_[A-Z0-9_]+\b")

# The account namespace. A consumer spells one of these in full, because
# nothing resolves them for it. A schema or a view or a table is named
# relative to a database by the tool that reaches it, and dbt's resolution of
# those is already graded by measurements/targets.json, so the reverse
# direction would fire on every one of them and a rule that fires on innocent
# code gets switched off rather than fixed.
ACCOUNT_LEVEL = ("warehouse", "role", "database", "user", "monitor", "storage integration")

# Which resource kind holds which sort of name. A consumer names a warehouse
# or a role or a database and does not say which, so the reconciliation has to
# know what each created name is.
NAME_KINDS = {
    "snowflake_warehouse": "warehouse",
    "snowflake_database": "database",
    "snowflake_account_role": "role",
    "snowflake_role": "role",
    "snowflake_user": "user",
    "snowflake_service_user": "user",
    "snowflake_resource_monitor": "monitor",
    "snowflake_stage_external_s3": "stage",
    "snowflake_storage_integration_aws": "storage integration",
    "snowflake_schema": "schema",
    "snowflake_view": "view",
    "snowflake_table": "table",
}

# Objects the configuration creates that no file consumes, with the reason
# each one is not a defect. An omission from this list is a finding and that
# is the point of the list existing.
UNCONSUMED_ON_PURPOSE = {
    "SCREENING_LOAD_WH": "the registry load runs as COPY from the external stage and the statement names no warehouse in this repository, so the loading role's warehouse is spent by a session a human opens",
    "SCREENING_REPORT_WH": "the review queue is read by a reviewer rather than by a file here, so nothing in this repository names it",
    "SCREENING_MONITOR": "a monitor is attached by the warehouses rather than named by a consumer",
    "SCREENING_LOADER": "granted to the loader service user and assumed by Fivetran and by the stage, neither of which is configured outside infra",
    "SCREENING_ANALYST": "assumed by a person opening the marts",
    "SCREENING_REVIEWER": "assumed by a person opening the review queue",
    "SCREENING_LOADER_SVC": "the service user the loader role is granted to, named by the Fivetran destination inside infra",
    "SCREENING_RAW": "written by replication and read by the staging sources, both of which resolve the database from the dbt target rather than naming it",
    "SCREENING_REGISTRY_LANDING": "the storage integration, named by the stage inside infra and by nothing outside it",
}

# Environment variables a job sets for something that is not this repository,
# with what reads each one. Without this the rule fires on every variable a
# third party consumes, which is most of the ones worth setting.
# Required variables the apply job deliberately does not pass, because no
# account exists to give them a value. This list used to live inside a check
# in tests/test_workflow.py, which made it a second place the deployment's
# shape was written down. It is here now and that check reads it, so the two
# cannot drift.
#
# Wiring these to repository variables that do not exist would be worse than
# leaving them out. An unset `vars.X` renders as an empty string, so a
# required string variable would arrive empty and apply, where today the apply
# stops and names the variable. The gap is the better failure.
UNSUPPLIED_UNTIL_THERE_IS_AN_ACCOUNT = (
    "cost_alert_recipients",
    "credentialing_database",
    "credentialing_host",
    "fivetran_postgres_user",
    "fivetran_snowflake_role",
    "fivetran_snowflake_user",
    "loader_rsa_public_key",
    "loading_warehouse",
    "monthly_credit_quota",
    "raw_database",
    "registry_landing_url",
    "snowflake_host",
    "storage_aws_role_arn",
)

READ_BY_A_THIRD_PARTY = {
    "SNOWFLAKE_TOKEN_FILE_PATH": "the Snowflake terraform provider, which reads the token out of the file this names",
}


def created(entries):
    """Every Snowflake object name a resource block in the configuration sets.

    Returns name -> (kind, address). A resource whose name is an expression is
    not here, because this cannot resolve one, and the caller is told how many
    were skipped rather than being handed a short list that looks complete.
    """
    out = {}
    skipped = []
    for _file, b in entries:
        if b.kind != "resource" or not b.labels:
            continue
        kind = NAME_KINDS.get(b.labels[0])
        if kind is None:
            continue
        value = b.value("name")
        if value is None:
            if "name" in b.args:
                skipped.append(b.address)
            continue
        out[value] = (kind, b.address)
    return out, sorted(skipped)


def profile_identities(path):
    """The Snowflake object names the dbt profile falls back to.

    A default is what runs when the environment sets nothing, which is every
    local invocation and every job that forgets one. So the default is the
    name worth reconciling and not the variable.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    found = [(var, default) for var, default in ENV_DEFAULT.findall(text)]
    return found, len(ENV_ANY.findall(text))


def workflow_environment(path):
    """Environment variable names each step of the workflow sets, with their values."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for number, raw in enumerate(fh, start=1):
            m = WORKFLOW_ENV.match(raw.rstrip("\n"))
            if m:
                out.append((m.group(1), m.group(2).strip(), number))
    return out


def object_names_in(path):
    """Every project object name a file mentions, deduplicated and sorted."""
    with open(path, encoding="utf-8") as fh:
        return sorted(set(OBJECT_NAME.findall(fh.read())))


def declared_variables(entries):
    """Variable name -> whether it has a default."""
    return {
        b.labels[0]: ("default" in b.args)
        for _file, b in entries
        if b.kind == "variable" and b.labels
    }


# Names a consumer spends that Terraform deliberately does not create, with
# the reason. A clone is made per pull request by a statement rather than by a
# resource, so no configuration can carry its name.
CREATED_ELSEWHERE = {
    "SCREENING_CI_PR_": "the pull request clone is created by a statement built in orchestration/clone.py, because the name carries a number no configuration holds",
}


def _created_elsewhere(name):
    return any(name.startswith(prefix) for prefix in CREATED_ELSEWHERE)


def every_name_a_consumer_spends_is_created(created_names, consumers):
    """Forward. A name sent to Snowflake that no resource creates.

    This is the direction that fails at connect time, and it is the one no
    tool in this repository could ask before today. dbt resolves a target
    without opening a connection, so a warehouse that does not exist parses
    exactly like one that does.
    """
    out = []
    for where, name, detail in consumers:
        if name in created_names or _created_elsewhere(name):
            continue
        out.append("%s names %s and no resource creates it (%s)" % (where, name, detail))
    return out


def every_object_created_is_spent(created_names, consumers):
    """Reverse. An object nobody uses is one somebody pays for.

    An allow list refuses by absence and permits by absence too, so the
    complement has to be written down. UNCONSUMED_ON_PURPOSE is that
    complement and an object in neither is the finding.
    """
    spent = {name for _where, name, _detail in consumers}
    out = []
    for name in sorted(created_names):
        kind, address = created_names[name]
        if kind not in ACCOUNT_LEVEL:
            continue
        if name in spent or name in UNCONSUMED_ON_PURPOSE:
            continue
        out.append(
            "%s is created as a %s by %s and nothing outside infra names it, and it is not in the deliberate list"
            % (name, kind, address)
        )
    for name in sorted(UNCONSUMED_ON_PURPOSE):
        if name not in created_names:
            out.append("%s is excused as unconsumed and no resource creates it, so the reason is about nothing" % name)
    return out


def shell_variables(path):
    """Environment variable names the workflow's own run blocks dereference.

    A step that sets PR and then writes "$PR" in its script is reading it. The
    rule below would otherwise report every one of those, which is the shape
    of check that gets switched off rather than fixed.
    """
    out = set()
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            for m in re.finditer(r"\$\{?([A-Z][A-Z0-9_]*)\}?", raw):
                out.add(m.group(1))
    return out


def every_variable_a_job_sets_is_read(profile_variables, workflow_env, read_elsewhere=()):
    """A job that sets an environment variable nothing reads has no effect.

    The pull request build sets a database name per clone. If the profile
    reads a different variable, the build connects to whatever the profile
    falls back to, which is the database the clone was made to protect.
    """
    read = set(profile_variables) | set(read_elsewhere) | set(READ_BY_A_THIRD_PARTY)
    out = []
    for name, value, line in workflow_env:
        if name in read or TF_VAR.match(name):
            continue
        out.append(
            "the workflow sets %s at line %d and nothing reads it, so the value %s has no effect"
            % (name, line, value)
        )
    return out


def every_required_variable_is_supplied(variables, workflow_env, declared_gap=None):
    """An apply needs every variable that has no default, or it stops.

    `terraform apply -input=false` cannot prompt, so a required variable the
    job does not pass is a failed apply rather than a wrong one. The job is
    held off, which is why nothing fails today.

    The gap is deliberate while there is no account, so the rule fires on a
    variable that is in neither set and on a name excused here that no longer
    needs excusing. That second direction is what stops the list outliving the
    reason for it.
    """
    declared_gap = UNSUPPLIED_UNTIL_THERE_IS_AN_ACCOUNT if declared_gap is None else declared_gap
    supplied = {TF_VAR.match(name).group(1) for name, _value, _line in workflow_env if TF_VAR.match(name)}
    out = []
    for name in sorted(variables):
        if variables[name] or name in supplied or name in declared_gap:
            continue
        out.append("variable %s has no default, the apply job does not pass it, and it is not in the declared gap" % name)
    for name in sorted(declared_gap):
        if name not in variables:
            out.append("%s is excused as unsupplied and no variable block declares it" % name)
        elif name in supplied:
            out.append("%s is excused as unsupplied and the apply job passes it, so the excuse is stale" % name)
    return out


def every_variable_a_job_passes_is_declared(variables, workflow_env):
    """The other direction. Terraform ignores a TF_VAR for a variable nobody declared."""
    out = []
    for name, _value, line in workflow_env:
        m = TF_VAR.match(name)
        if not m:
            continue
        if m.group(1) not in variables:
            out.append("the apply job passes %s at line %d and no variable block declares %s" % (name, line, m.group(1)))
    return out


def consumers_of(root):
    """Every place outside infra that spends a Snowflake object name.

    Returns (where, name, detail) so a problem can say which file to open.
    """
    out = []
    profile = os.path.join(root, "transform", "profiles", "profiles.yml")
    pairs, _total = profile_identities(profile)
    for var, default in pairs:
        for name in OBJECT_NAME.findall(default):
            out.append(("the dbt profile", name, "the fallback for %s" % var))

    clone = os.path.join(root, "orchestration", "clone.py")
    with open(clone, encoding="utf-8") as fh:
        for number, raw in enumerate(fh, start=1):
            if raw.lstrip().startswith("#"):
                continue
            for name in OBJECT_NAME.findall(raw):
                out.append(("the clone module", name, "line %d" % number))

    workflow = os.path.join(root, ".github", "workflows", "ci.yml")
    with open(workflow, encoding="utf-8") as fh:
        for number, raw in enumerate(fh, start=1):
            if raw.lstrip().startswith("#"):
                continue
            for name in OBJECT_NAME.findall(raw):
                out.append(("the workflow", name, "line %d" % number))
    return out




# What removes each thing created outside the configuration. `terraform
# destroy` is the teardown for everything a resource block creates, so the
# only objects that need a teardown path written down are the ones no resource
# block holds. An entry here names the function that builds the statement, and
# a check asserts the function exists and that the statement it builds names
# the object.
TORN_DOWN_BY = {
    "SCREENING_CI_PR_": "orchestration.clone.drop_statements",
}


def every_object_created_elsewhere_has_a_teardown(created_elsewhere=None, torn_down_by=None):
    """A thing terraform destroy cannot reach needs something else that can.

    This is the whole teardown gap. `terraform destroy` removes the 21 objects
    the configuration creates and it has never heard of a clone built by a
    statement, so a clone is the one thing that can outlive a teardown. The
    transient database and the retention of zero bound what that costs, and
    they are not a substitute for a drop.
    """
    created_elsewhere = CREATED_ELSEWHERE if created_elsewhere is None else created_elsewhere
    torn_down_by = TORN_DOWN_BY if torn_down_by is None else torn_down_by
    out = []
    for prefix in sorted(created_elsewhere):
        if prefix not in torn_down_by:
            out.append("%s is created outside the configuration and nothing here names a teardown for it" % prefix)
    for prefix in sorted(torn_down_by):
        if prefix not in created_elsewhere:
            out.append("%s has a teardown and nothing creates it, so the teardown is about nothing" % prefix)
    return out


RULES = (
    every_object_created_elsewhere_has_a_teardown,
    every_name_a_consumer_spends_is_created,
    every_object_created_is_spent,
    every_variable_a_job_sets_is_read,
    every_required_variable_is_supplied,
    every_variable_a_job_passes_is_declared,
)
