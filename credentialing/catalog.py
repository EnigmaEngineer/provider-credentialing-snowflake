"""What the source database has to say about itself before anything replicates it.

The replication configuration lives in two places and only one of them is a
file this repository owns. The connector says which method to use. What that
method can actually see is decided by the source table's replica identity and
by whether it is in the publication, and neither of those appears in any
connector configuration.

So these rules read the catalog rather than any file. They are the same shape
as the rules over the warehouse configuration. Each one fires when the thing
that makes a capability real is absent, and absent here means a default
somebody got rather than chose.

The measurement the thresholds come from is in measurements/replication.json.

relreplident is a single character in pg_class. The four values and what each
one puts in the write ahead log for a delete, measured rather than read:

    d  default   the primary key columns only, and nothing at all when the
                 table has no primary key
    f  full      every column of the old row
    i  index     the columns of a nominated unique index
    n  nothing   no delete reaches the log, and the source refuses the DELETE
"""

DEFAULT = "d"
FULL = "f"
INDEX = "i"
NOTHING = "n"

# Every table the credentialing schema creates. Held here rather than read out
# of the DDL because a rule that derives its own subject list from the file it
# grades cannot fail on a table the file never created.
TABLES = (
    "application",
    "committee_decision",
    "facility",
    "license",
    "provider",
    "verification",
)

# The tables where a delete the warehouse does not see changes a screening
# answer. A rescinded committee decision left in place reads as an approval
# that no longer exists, and a provider cleared on a deleted licence is cleared
# on nothing. Both clear somebody who belongs in the review queue, which is the
# one direction of error that matters here.
DELETE_CHANGES_AN_ANSWER = ("committee_decision", "license")

CATALOG_SQL = """
SELECT c.relname
     || '|' || c.relreplident::text
     || '|' || (SELECT count(*) FROM pg_index i
                WHERE i.indrelid = c.oid AND i.indisprimary)
     || '|' || (SELECT count(*) FROM pg_publication_tables t
                WHERE t.schemaname = 'credentialing' AND t.tablename = c.relname)
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'credentialing' AND c.relkind = 'r'
 ORDER BY c.relname
"""


def read(run_sql):
    """One dict per table, from a callable that runs SQL and returns text rows.

    Takes the runner rather than a connection so the caller decides how it
    talks to the database, and because a function that takes a callable can be
    handed a canned answer by a check on a machine with no server. The rules
    below are graded against the committed answer. This is graded against text
    that looks like what psql returns.
    """
    out = {}
    for line in run_sql(CATALOG_SQL).splitlines():
        line = line.strip()
        if not line:
            continue
        name, ident, pk, published = line.split("|")
        out[name] = {
            "replica_identity": ident,
            "has_primary_key": int(pk) > 0,
            "in_publication": int(published) > 0,
        }
    return out


def every_table_is_present(cat):
    """A table missing from the catalog answer is a table nothing graded."""
    out = []
    for name in TABLES:
        if name not in cat:
            out.append("%s is not in the catalog answer, so no rule below saw it" % name)
    for name in sorted(cat):
        if name not in TABLES:
            out.append("%s is in the database and not in the list these rules cover" % name)
    return out


def every_table_has_a_primary_key(cat):
    out = []
    for name in sorted(cat):
        if not cat[name]["has_primary_key"]:
            out.append(
                "%s has no primary key, so a published delete has no row to name" % name
            )
    return out


def the_source_can_still_write(cat):
    """Publishing a table takes away the source's own updates and deletes.

    Measured. A published table whose replica identity is nothing, or default
    with no primary key, refuses the UPDATE and the DELETE outright. The error
    is raised in the credentialing application and not in the warehouse, so the
    first thing anybody notices is an operational failure in a system nobody
    changed.
    """
    out = []
    for name in sorted(cat):
        row = cat[name]
        if not row["in_publication"]:
            continue
        if row["replica_identity"] == NOTHING:
            out.append("%s is published and its replica identity is nothing, so the source cannot delete from it" % name)
        elif row["replica_identity"] == DEFAULT and not row["has_primary_key"]:
            out.append("%s is published with no primary key and the default identity, so the source cannot delete from it" % name)
    return out


def deletes_that_change_an_answer_carry_the_old_row(cat):
    out = []
    for name in DELETE_CHANGES_AN_ANSWER:
        row = cat.get(name)
        if row is None:
            out.append("%s is named as a table whose deletes matter and it is not in the catalog answer" % name)
            continue
        if row["replica_identity"] not in (FULL, INDEX):
            out.append(
                "%s runs on the %r replica identity, so a delete reaches the log carrying the key alone"
                % (name, row["replica_identity"])
            )
    return out


def publication_covers_every_table(cat):
    out = []
    for name in sorted(cat):
        if not cat[name]["in_publication"]:
            out.append(
                "%s is not in any publication, so it never replicates and nothing downstream says so"
                % name
            )
    return out


RULES = (
    every_table_is_present,
    every_table_has_a_primary_key,
    the_source_can_still_write,
    deletes_that_change_an_answer_carry_the_old_row,
    publication_covers_every_table,
)


def check_all(cat):
    return {rule.__name__: rule(cat) for rule in RULES}
