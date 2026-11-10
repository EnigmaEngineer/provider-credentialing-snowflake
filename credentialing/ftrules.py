"""One rule per replication capability, each firing when its setting is absent.

The same shape as the rules over the warehouse configuration and for the same
reason. The replication provider marks almost every field optional, so nothing
in terraform validate can fail on a setting nobody wrote, and the setting
nobody wrote is the one that decides whether the connector does the thing it
was added for.

Two of these are about the provider rather than about this configuration.

The provider offers two resources for a connector. One takes its service
settings as a JSON encoded string and does not read that string back, so
neither validate nor plan can see anything about the replication. The other
takes the same settings as a typed block. A rule refuses the first.

These rules read names and never values. That is a real limit and it is where
the reader stops rather than a judgement about what matters. The checks that
need a value use an independent parser, and the ones that compare this
configuration against the source schema have to, because a name matching
across two files is exactly the thing no single file can state.
"""

from screening import tfread

# The resource whose configuration is an opaque string. Named here rather than
# inline so the rule reads as a rule and not as a string comparison.
UNGRADEABLE_CONNECTOR = "fivetran_connection"
TYPED_CONNECTOR = "fivetran_connector"


def _resources(entries, kind):
    return [
        (name, b)
        for name, b in entries
        if b.kind == "resource" and b.labels and b.labels[0] == kind
    ]


def _named(block, arg):
    return arg in block.args or arg in block.nested_args


def every_service_setting_is_gradeable(entries):
    """The untyped resource puts the whole replication beyond any check."""
    out = []
    for name, b in _resources(entries, UNGRADEABLE_CONNECTOR):
        out.append(
            "%s %s uses %s, whose config is one string the provider does not read back"
            % (name, b.label, UNGRADEABLE_CONNECTOR)
        )
    return out


def connector_exists_and_names_its_source(entries):
    out = []
    found = _resources(entries, TYPED_CONNECTOR)
    if not found:
        out.append("no connector at all, so nothing replicates into the raw layer")
    for name, b in found:
        for arg in ("host", "port", "database", "user"):
            if not _named(b, arg):
                out.append("%s %s names no %s" % (name, b.label, arg))
    return out


def connector_decides_how_it_detects_change(entries):
    """An absent update method is a replication strategy nobody chose."""
    out = []
    for name, b in _resources(entries, TYPED_CONNECTOR):
        if not _named(b, "update_method"):
            out.append(
                "%s %s names no update_method, so how it finds a changed row is a default"
                % (name, b.label)
            )
    return out


def log_replication_names_the_slot_and_the_publication(entries):
    """Both are meaningless under the query based method and required under the other.

    This configuration chose log replication. The slot and the publication are
    the two objects that have to exist in the source database for it to work,
    and a connector that names neither is one that will be pointed at whatever
    Fivetran picks.
    """
    out = []
    for name, b in _resources(entries, TYPED_CONNECTOR):
        for arg in ("replication_slot", "publication_name"):
            if not _named(b, arg):
                out.append("%s %s names no %s" % (name, b.label, arg))
    return out


def connector_says_how_it_connects(entries):
    """An omitted connection type is inferred from whether a tunnel host is set."""
    out = []
    for name, b in _resources(entries, TYPED_CONNECTOR):
        if not _named(b, "connection_type"):
            out.append(
                "%s %s names no connection_type, so the method is inferred from another field"
                % (name, b.label)
            )
    return out


def landing_tables_are_separable_by_name(entries):
    out = []
    for name, b in _resources(entries, TYPED_CONNECTOR):
        if "destination_schema" not in b.nested:
            out.append("%s %s names no destination_schema" % (name, b.label))
        elif not _named(b, "prefix"):
            out.append(
                "%s %s names no prefix, so its tables are not separable from the registry tables"
                % (name, b.label)
            )
    return out


def schedule_is_chosen(entries):
    out = []
    found = _resources(entries, "fivetran_connector_schedule")
    if not found:
        out.append("no schedule, so the connector syncs on the account default")
    for name, b in found:
        for arg in ("sync_frequency", "paused"):
            if not _named(b, arg):
                out.append("%s %s names no %s" % (name, b.label, arg))
    return out


def a_new_column_needs_a_decision(entries):
    """This source holds a date of birth beside a name, which is what gets masked."""
    out = []
    found = _resources(entries, "fivetran_connector_schema_config")
    if not found:
        out.append("no schema config, so a column added to the source arrives on the next sync")
    for name, b in found:
        if not _named(b, "schema_change_handling"):
            out.append(
                "%s %s names no schema_change_handling, so a new column arrives without anyone allowing it"
                % (name, b.label)
            )
    return out


def destination_does_not_run_on_defaults(entries):
    out = []
    found = _resources(entries, "fivetran_destination")
    if not found:
        out.append("no destination, so there is nowhere for the connector to land")
    for name, b in found:
        for arg in ("default_virtual_warehouse", "role", "database"):
            if not _named(b, arg):
                out.append("%s %s names no %s" % (name, b.label, arg))
    return out


def replication_carries_no_inline_credential(entries):
    """The subject is argument names and not prose, which is why it reads names.

    A password or a private key written into this file would be committed. The
    rule reaches nested blocks because the service settings are one.
    """
    forbidden = ("password", "private_key", "passphrase", "aws_secret_access_key")
    out = []
    for name, b in entries:
        if b.kind != "resource" or not b.labels or not b.labels[0].startswith("fivetran_"):
            continue
        for arg in forbidden:
            if arg in b.args or arg in b.nested_args:
                out.append("%s %s names %s inline" % (name, b.label, arg))
    return out


RULES = (
    every_service_setting_is_gradeable,
    connector_exists_and_names_its_source,
    connector_decides_how_it_detects_change,
    log_replication_names_the_slot_and_the_publication,
    connector_says_how_it_connects,
    landing_tables_are_separable_by_name,
    schedule_is_chosen,
    a_new_column_needs_a_decision,
    destination_does_not_run_on_defaults,
    replication_carries_no_inline_credential,
)


def check_all(path):
    entries = tfread.read_dir(path)
    return {rule.__name__: rule(entries) for rule in RULES}
