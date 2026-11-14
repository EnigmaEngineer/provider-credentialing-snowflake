"""One rule per capability, each firing when the element that makes it real is absent.

Every rule here reads a block that exists and asks whether it names something.
That is the opposite of how the other gates in this repository work and it is
deliberate. terraform validate grades a value against the provider's schema,
so it is silent about a warehouse with no auto_suspend, a monitor with no
quota, a grant with no privileges and a pipe that does not auto ingest. Each
of those is a default somebody did not choose, and the file reads the same
either way.

A rule returns the problems it found. An empty list is a pass.
"""

from . import tfread


def _resources(entries, kind):
    return [(name, b) for name, b in entries if b.kind == "resource" and b.labels and b.labels[0] == kind]


def warehouse_suspends_itself(entries):
    out = []
    for name, b in _resources(entries, "snowflake_warehouse"):
        if "auto_suspend" not in b.args:
            out.append("%s %s names no auto_suspend, so it runs on the account default" % (name, b.label))
    return out


def warehouse_has_a_credit_ceiling(entries):
    out = []
    for name, b in _resources(entries, "snowflake_warehouse"):
        if "resource_monitor" not in b.args:
            out.append("%s %s names no resource_monitor, so nothing caps what it spends" % (name, b.label))
    return out


def monitor_can_actually_alert(entries):
    """A monitor with only a name is a budget alert that cannot alert."""
    out = []
    found = _resources(entries, "snowflake_resource_monitor")
    if not found:
        out.append("no resource monitor at all, so there is no budget alert")
    for name, b in found:
        for arg in ("credit_quota", "notify_triggers", "notify_users", "suspend_trigger"):
            if arg not in b.args:
                out.append("%s %s names no %s" % (name, b.label, arg))
    return out


def retention_is_chosen(entries):
    out = []
    for kind in ("snowflake_database", "snowflake_schema"):
        for name, b in _resources(entries, kind):
            if "data_retention_time_in_days" not in b.args:
                out.append(
                    "%s %s names no data_retention_time_in_days, so time travel is the account default"
                    % (name, b.label)
                )
    return out


def service_user_uses_a_key_pair(entries):
    out = []
    for name, b in _resources(entries, "snowflake_service_user"):
        if "rsa_public_key" not in b.args:
            out.append(
                "%s %s names no rsa_public_key, so it falls back to a password" % (name, b.label)
            )
    return out


def pipe_ingests_on_arrival(entries):
    out = []
    for name, b in _resources(entries, "snowflake_pipe"):
        if "auto_ingest" not in b.args:
            out.append(
                "%s %s names no auto_ingest, so it loads only when somebody asks it to"
                % (name, b.label)
            )
    return out


def stage_points_somewhere_and_carries_no_credential(entries):
    out = []
    for kind in ("snowflake_stage", "snowflake_stage_external_s3"):
        for name, b in _resources(entries, kind):
            if "url" not in b.args:
                out.append("%s %s names no url" % (name, b.label))
            if "storage_integration" not in b.args:
                out.append("%s %s names no storage_integration" % (name, b.label))
            if "credentials" in b.args or "credentials" in b.nested:
                out.append("%s %s carries inline credentials" % (name, b.label))
    return out


def grant_names_what_it_grants(entries):
    out = []
    for name, b in _resources(entries, "snowflake_grant_privileges_to_account_role"):
        if "all_privileges" in b.args:
            out.append("%s %s uses all_privileges" % (name, b.label))
        elif "privileges" not in b.args:
            out.append("%s %s names neither privileges nor all_privileges, so it grants nothing" % (name, b.label))
    return out


def file_format_decides_its_own_encoding(entries):
    """The encoding is a measurement on this data rather than a default."""
    out = []
    for name, b in _resources(entries, "snowflake_file_format_csv"):
        if "encoding" not in b.args:
            out.append("%s %s names no encoding, so it reads the file as UTF8" % (name, b.label))
        if "replace_invalid_characters" not in b.args:
            out.append(
                "%s %s names no replace_invalid_characters, so nothing in the file says whether a bad byte aborts or is swallowed"
                % (name, b.label)
            )
        if "null_if" not in b.args:
            out.append(
                "%s %s names no null_if, and this data encodes its absences as values"
                % (name, b.label)
            )
    return out


def provider_names_who_it_connects_as(entries):
    out = []
    found = [(n, b) for n, b in entries if b.kind == "provider"]
    if not found:
        out.append("no provider block, so an apply uses whatever is on the machine")
    for name, b in found:
        for arg in ("organization_name", "account_name", "user", "authenticator"):
            if arg not in b.args:
                out.append("%s provider names no %s" % (name, arg))
    return out




# The access rules, added 2026-11-14. Same shape as the ones above and the
# subject moved, because a policy is the one kind of object in this
# configuration that does nothing at all until something else points at it.
#
# terraform validate accepted a masking policy attached to no column and a row
# access policy attached to no relation. Both are complete resources with
# every required argument set. They would be created in the account, they
# would appear in SHOW MASKING POLICIES, and they would filter nothing.


def _referenced_anywhere(entries):
    """Every resource address that some other block refers to."""
    out = set()
    for _name, b in entries:
        out.update(b.refs)
    return out


def a_masking_policy_is_attached_to_a_column(entries):
    """A policy nothing points at is a policy that masks nothing.

    The attachment is a reference rather than an argument, so no rule reading
    argument names can see this and neither can validate.
    """
    out = []
    referenced = _referenced_anywhere(entries)
    for name, b in _resources(entries, "snowflake_masking_policy"):
        if b.address not in referenced:
            out.append(
                "%s %s is referenced by nothing, so it is created and masks no column"
                % (name, b.label)
            )
    return out


def a_row_access_policy_is_attached_to_a_relation(entries):
    out = []
    referenced = _referenced_anywhere(entries)
    for name, b in _resources(entries, "snowflake_row_access_policy"):
        if b.address not in referenced:
            out.append(
                "%s %s is referenced by nothing, so it is created and filters no rows"
                % (name, b.label)
            )
    return out


def a_view_the_reading_roles_use_filters_its_rows(entries):
    """A view in the enforcement schema with no row filter on it.

    This is the rule the grant comment in grants.tf rests on. The reading
    roles are granted on named views in one schema, and the schema's whole
    purpose is that what lands in it is filtered. A view added later with no
    row_access_policy block is readable in full and nothing else complains.
    """
    out = []
    for name, b in _resources(entries, "snowflake_view"):
        if "row_access_policy" not in b.nested:
            out.append(
                "%s %s names no row_access_policy, so every row reaches every role granted on it"
                % (name, b.label)
            )
    return out


def a_view_the_reading_roles_use_is_secure(entries):
    """is_secure is optional, and a view without it publishes its own definition.

    The definition is the lesser half. A view that is not secure lets the
    optimiser push a predicate past the filter, so a row the policy removed
    can be inferred from which queries come back empty.
    """
    out = []
    for name, b in _resources(entries, "snowflake_view"):
        if "is_secure" not in b.args:
            out.append(
                "%s %s names no is_secure, so it defaults to a view whose definition is readable"
                % (name, b.label)
            )
    return out


def a_conditional_masking_policy_is_given_its_deciding_column(entries):
    """A policy taking two arguments, attached without the second one.

    A masking policy with one argument reads the column it masks. One with two
    reads the column it masks and the column that decides, and the second one
    arrives through using at the attachment rather than at the policy. Attach
    it without using and Snowflake has a policy whose body references an
    argument nothing passes.

    This counts rather than checking presence. A view attaching two
    conditional policies and one using clause has one column unguarded, and
    the count is the only cheap way to see it.
    """
    out = []
    conditional = {
        b.address
        for _name, b in _resources(entries, "snowflake_masking_policy")
        if b.count_nested("argument") > 1
    }
    for name, b in _resources(entries, "snowflake_view"):
        wanted = len(conditional & b.refs)
        given = b.count_nested_arg("using")
        if given < wanted:
            out.append(
                "%s %s attaches %d conditional masking policies and sets using %d times"
                % (name, b.label, wanted, given)
            )
    return out


def the_row_filter_mapping_is_not_granted_to_the_roles_it_filters(entries):
    """A reviewer who can read the assignment mapping reads everybody's assignment.

    The one rule here that fires on something being present. It belongs with
    the others because the reason the grant gets written is the same absence
    the rest of them are about: a policy body queries a table, so the obvious
    move is to grant the querying role select on it. Snowflake evaluates the
    expression as the policy owner, so the grant buys nothing and widens what
    a reviewer can read to every other reviewer's assignment.

    The rule reads the mapping table by name rather than by a pattern. A
    second mapping table would need adding here, and a list of tables that
    must not be granted is the blocklist shape, so it is scoped to the one
    table whose contents are about people.
    """
    out = []
    mapping = "snowflake_table.review_assignment"
    filtered = ("snowflake_account_role.reviewer", "snowflake_account_role.analyst")
    for name, b in _resources(entries, "snowflake_grant_privileges_to_account_role"):
        if mapping not in b.refs:
            continue
        for role in filtered:
            if role in b.refs:
                out.append(
                    "%s %s grants %s on the row filter mapping, so it reads every "
                    "assignment and not only its own" % (name, b.label, role)
                )
    return out


def a_role_that_reads_has_a_warehouse(entries):
    """A role granted SELECT and no warehouse cannot run the query.

    Found by writing this rule. SCREENING_ANALYST and SCREENING_REVIEWER held
    usage on the analytics database, no object grant anywhere and no
    warehouse, for four days, while the comments on both roles described what
    each of them sees.
    """
    out = []
    reads = set()
    has_warehouse = set()
    for _name, b in _resources(entries, "snowflake_grant_privileges_to_account_role"):
        role = None
        for ref in b.refs:
            if ref.startswith("snowflake_account_role."):
                role = ref
        if role is None:
            continue
        if any(r.startswith("snowflake_warehouse.") for r in b.refs):
            has_warehouse.add(role)
        elif "on_schema_object" in b.nested:
            reads.add(role)
    for role in sorted(reads - has_warehouse):
        out.append("%s is granted on an object and no warehouse, so it cannot run a statement" % role)
    return out


RULES = (
    warehouse_suspends_itself,
    warehouse_has_a_credit_ceiling,
    monitor_can_actually_alert,
    retention_is_chosen,
    service_user_uses_a_key_pair,
    pipe_ingests_on_arrival,
    stage_points_somewhere_and_carries_no_credential,
    grant_names_what_it_grants,
    file_format_decides_its_own_encoding,
    provider_names_who_it_connects_as,
    a_masking_policy_is_attached_to_a_column,
    a_row_access_policy_is_attached_to_a_relation,
    a_view_the_reading_roles_use_filters_its_rows,
    a_view_the_reading_roles_use_is_secure,
    a_conditional_masking_policy_is_given_its_deciding_column,
    the_row_filter_mapping_is_not_granted_to_the_roles_it_filters,
    a_role_that_reads_has_a_warehouse,
)


def check_all(path):
    """Every rule over a directory of configuration. Returns rule name to problems."""
    entries = tfread.read_dir(path)
    return {rule.__name__: rule(entries) for rule in RULES}
