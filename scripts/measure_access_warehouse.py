"""The two enforcement relations as the warehouse builds them.

    python3 scripts/measure_access_warehouse.py --database transform/target/screening.duckdb

This exists because the other access measurement builds the relations in
Python and that is a reimplementation, not a reading. It was wrong the first
time it ran. It built the candidate relation out of the tier cascade, which
answers which queue a provider lands in, while the model unions all three
tiers because a weaker pair is still worth keeping for somebody reviewing a
stronger decision. Four rows against the warehouse's five, found by running
both.

So this one runs the view statements against the models and writes what came
back. tests/test_access.py compares the two arms row by row, which is what
stops the Python side drifting into a second definition of the relations.

The statements here are the ones in infra/policies.tf with the three part
Snowflake names replaced by the schemas the models resolve into under duckdb.
That substitution is the one thing the comparison cannot grade, so the column
list and the join are kept identical and a check asserts the column names
agree with the access design.

Needs duckdb, so it runs in the cloud container and never on the device. Run
dbt seed and dbt build first or it reads a database with no models in it.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screening import access  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "measurements", "access_warehouse.json")
DEFAULT_DB = os.path.join(ROOT, "transform", "target", "screening.duckdb")

QUEUE = """
select
  q.provider_id,
  q.npi,
  q.npi_is_absent,
  q.last_name,
  q.first_name,
  q.date_of_birth,
  q.tier,
  q.tier_rank,
  q.records_matched,
  q.distinct_records_matched,
  q.cleared_without_review,
  a.facility_id
from intermediate.int_screening__provider_screening q
left join staging.stg_credentialing__application a
  on a.provider_id = q.provider_id and a.is_active
"""

CANDIDATE = """
select
  c.provider_id,
  c.tier,
  c.tier_rank,
  c.matched_npi,
  c.matched_fallback_key,
  a.facility_id
from intermediate.int_screening__match_candidate c
left join staging.stg_credentialing__application a
  on a.provider_id = c.provider_id and a.is_active
"""

# The columns the comparison is made on. Not every column, because the queue
# carries counts the Python arm does not rebuild, and a comparison over
# columns one side does not produce would be a comparison of nulls.
COMPARED = {
    "review_queue": ("provider_id", "tier", "tier_rank", "facility_id"),
    "match_candidate": (
        "provider_id",
        "tier",
        "tier_rank",
        "matched_npi",
        "matched_fallback_key",
        "facility_id",
    ),
}


def rows_and_columns(con, sql):
    got = con.execute(sql).fetchall()
    names = [d[0] for d in con.description]
    return [dict(zip(names, row)) for row in got], names


def comparable(name, rows):
    """The rows as sorted tuples of strings, so two engines can be diffed.

    Everything is stringified because duckdb returns a date object and the
    seed carries the same value as text, and a comparison that fails on the
    type rather than the value says nothing about either engine.
    """
    keys = COMPARED[name]
    out = []
    for row in rows:
        out.append([("" if row.get(k) is None else str(row.get(k))) for k in keys])
    return sorted(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=DEFAULT_DB)
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args(argv)

    import duckdb

    con = duckdb.connect(args.database, read_only=True)
    queue, queue_columns = rows_and_columns(con, QUEUE)
    candidate, candidate_columns = rows_and_columns(con, CANDIDATE)

    result = {
        "engine": "duckdb %s" % duckdb.__version__,
        "measured": ["compared_columns", "relations"],
        "compared_columns": {k: list(v) for k, v in sorted(COMPARED.items())},
        "relations": {
            "review_queue": {
                "rows": len(queue),
                "columns": queue_columns,
                "compared": comparable("review_queue", queue),
            },
            "match_candidate": {
                "rows": len(candidate),
                "columns": candidate_columns,
                "compared": comparable("match_candidate", candidate),
            },
        },
    }

    # The design's column list against the view's. A column the design does
    # not know about cannot be in a recovery set, so it reads whole for every
    # role and no rule anywhere complains.
    for name, got in sorted(result["relations"].items()):
        declared = set(access.relation(name).columns)
        actual = set(got["columns"])
        got["columns_the_design_does_not_know"] = sorted(actual - declared)
        got["columns_the_design_expects_and_the_view_lacks"] = sorted(declared - actual)

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1, sort_keys=True)
        handle.write("\n")
    for name, got in sorted(result["relations"].items()):
        print("%-18s %d rows, %d columns, unknown to the design %r"
              % (name, got["rows"], len(got["columns"]),
                 got["columns_the_design_does_not_know"]))
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
