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
)


def check_all(path):
    """Every rule over a directory of configuration. Returns rule name to problems."""
    entries = tfread.read_dir(path)
    return {rule.__name__: rule(entries) for rule in RULES}
