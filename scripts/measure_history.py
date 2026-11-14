"""What attribute history records, and what each snapshot strategy misses.

    python3 scripts/measure_history.py --database /somewhere/history.duckdb

A snapshot is the only thing in the transform project that keeps state between
runs, so it is the only thing whose behaviour cannot be read off the models. It
has to be exercised. Build it. Change the source underneath it and build it
again, then count what each version actually says.

Two strategies run over the same table and the same change set. The check
strategy compares the four columns a match tier reads. The timestamp strategy
trusts the application's own updated_at. They are different answers to
different questions and the measurement is what each one records.

Three changes go in. A surname that moves and bumps the clock. A date of birth
that moves and does not, which is what a missing trigger or a direct update
looks like. And a specialty that moves and bumps the clock, which cannot change
a match at all.

The snapshots read the staging models rather than the raw tables, so dbt
snapshot on its own cannot run them. It is recorded here rather than described,
because the obvious way to write a monthly cycle is to snapshot first and then
transform, and that order fails on a fresh warehouse with a catalog error about
a schema that does not exist.

The database is an argument and it defaults to a file of this script's own,
never the one the seeds and the comparison share. A measurement script that
writes its fixtures into the shared warehouse poisons every other measurement
that reads it, and cleaning up afterwards is not cleaning up.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROJECT = os.path.join(ROOT, "transform")
OUT = os.path.join(ROOT, "measurements", "history.json")
SHARED = os.path.join(PROJECT, "target", "screening.duckdb")

# Each row is a provider identifier and the column that moves. Then the value
# it moves to, and whether the application's own clock moves with it.
#
# The three were chosen so that only the snapshot strategies move. Provider 5
# is in no tier at all, and provider 1 is reached by the identifier tier, so a
# surname change cannot alter which tier either of them lands in. Provider 3 is
# in no tier and holds no application. A change set that also broke the planted
# matches would leave the arms measured against a fixture whose tiers had
# shifted underneath them.
CHANGES = (
    (5, "last_name", "ELSWORTHY", True),
    (1, "last_name", "ANSELLY", False),
    (3, "primary_specialty", "GERIATRIC PSYCHIATRY", True),
)

# The columns the check arm watches, which are the ones the three tiers read.
MATCHED_COLUMNS = ("npi", "last_name", "first_name", "date_of_birth")

ARMS = {
    "check": "provider_attribute",
    "timestamp": "provider_attribute_by_timestamp",
}


def dbt(command, database, target="duckdb"):
    env = dict(os.environ)
    env["DBT_PROFILES_DIR"] = os.path.join(PROJECT, "profiles")
    env["SCREENING_DUCKDB"] = database
    done = subprocess.run(
        ["dbt"] + command + ["--target", target],
        cwd=PROJECT,
        env=env,
        capture_output=True,
        text=True,
    )
    # The exit code is read here rather than through a pipe, because a parse
    # that exits 2 and a parse that exits 0 look identical through tail.
    return done.returncode, done.stdout, done.stderr


def must(command, database):
    code, out, err = dbt(command, database)
    if code != 0:
        raise SystemExit(
            "dbt %s exited %d\n%s\n%s" % (" ".join(command), code, out[-4000:], err[-2000:])
        )
    return out


def catalog_errors(text):
    """Every catalog error dbt printed, sorted and deduplicated.

    Sorted because the snapshots run on four threads and whichever one reaches
    the missing schema first prints first. Recording the first line put a
    different string in the manifest on consecutive runs of the same
    measurement, which is a figure that does not reproduce.
    """
    found = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Catalog Error:"):
            found.add(stripped)
    return sorted(found)


def run_results():
    path = os.path.join(PROJECT, "target", "run_results.json")
    with open(path, encoding="utf-8") as fh:
        results = json.load(fh)
    out = {}
    for row in results["results"]:
        name = row["unique_id"].split(".")[-1]
        out[name] = {"status": row["status"], "failures": row.get("failures")}
    return out


def test_summary(results):
    failed = sorted(
        name for name, row in results.items() if row["status"] not in ("success", "pass")
    )
    return {
        "nodes": len(results),
        "failed": failed,
        "failed_count": len(failed),
    }


def versions(con, relation):
    rows = con.execute(
        "select provider_id, count(*), sum(case when dbt_valid_to is null then 1 else 0 end) "
        "from snapshots.%s group by provider_id order by provider_id" % relation
    ).fetchall()
    return {
        int(pid): {"versions": int(total), "open": int(open_rows)}
        for pid, total, open_rows in rows
    }


def currency(con):
    rows = con.execute(
        "select provider_id, is_active, outside_window, "
        "screened_against_a_superseded_file, attributes_moved_since_screening, "
        "screening_is_void from intermediate.int_screening__screening_currency "
        "order by provider_id"
    ).fetchall()
    out = {}
    for pid, active, window, replaced, moved, void in rows:
        out[int(pid)] = {
            "is_active": bool(active),
            "outside_window": bool(window),
            "screened_against_a_superseded_file": bool(replaced),
            "attributes_moved_since_screening": bool(moved),
            "screening_is_void": bool(void),
        }
    return out


def void_active(answers):
    return sorted(pid for pid, row in answers.items() if row["is_active"] and row["screening_is_void"])


def apply_changes(con):
    applied = []
    for provider_id, column, value, bump_clock in CHANGES:
        clock = ", updated_at = updated_at + interval 1 day" if bump_clock else ""
        con.execute(
            "update main.raw_credentialing_provider set %s = ?%s where provider_id = ?"
            % (column, clock),
            [value, provider_id],
        )
        applied.append(
            {
                "provider_id": provider_id,
                "column": column,
                "updated_at_moved": bump_clock,
                "a_tier_reads_this_column": column in MATCHED_COLUMNS,
            }
        )
    return applied


def gained(before, after):
    """Providers whose version count went up."""
    return sorted(
        pid for pid, row in after.items() if row["versions"] > before.get(pid, {}).get("versions", 0)
    )


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--database",
        default=os.path.join(tempfile.gettempdir(), "screening-history.duckdb"),
        help="where to build. Never the database the seeds and the comparison share.",
    )
    args = ap.parse_args(argv)

    database = os.path.abspath(args.database)
    if database == os.path.abspath(SHARED):
        raise SystemExit(
            "refusing to measure into %s, which other measurements read" % SHARED
        )
    if os.path.exists(database):
        os.remove(database)

    import duckdb

    must(["seed", "--full-refresh"], database)

    # The order a monthly cycle would be written in, run first so the error it
    # produces is a measured string rather than a sentence in a document.
    alone_code, alone_out, _alone_err = dbt(["snapshot"], database)
    snapshot_alone = {
        "exit": alone_code,
        "ran_before_the_models": alone_code == 0,
        "errors": catalog_errors(alone_out),
    }

    first_build = dbt(["build", "--exclude", "resource_type:seed"], database)
    before_tests = test_summary(run_results())

    con = duckdb.connect(database)
    before = {arm: versions(con, relation) for arm, relation in sorted(ARMS.items())}
    before_currency = currency(con)

    applied = apply_changes(con)
    con.close()

    must(["snapshot"], database)
    second_build = dbt(["build", "--exclude", "resource_type:seed"], database)
    after_tests = test_summary(run_results())

    con = duckdb.connect(database)
    after = {arm: versions(con, relation) for arm, relation in sorted(ARMS.items())}
    after_currency = currency(con)
    con.close()

    changed_a_matched_column = sorted(c["provider_id"] for c in applied if c["a_tier_reads_this_column"])
    recorded = {arm: gained(before[arm], after[arm]) for arm in sorted(ARMS)}

    measured = {
        "changes_applied": applied,
        "providers_whose_matched_attributes_changed": changed_a_matched_column,
        "versions": {
            "before": before,
            "after": after,
        },
        "recorded_a_new_version": recorded,
        "missed_by_the_timestamp_arm": sorted(
            set(changed_a_matched_column) - set(recorded["timestamp"])
        ),
        "recorded_by_the_timestamp_arm_and_unusable": sorted(
            set(recorded["timestamp"]) - set(changed_a_matched_column)
        ),
        "currency": {
            "before": before_currency,
            "after": after_currency,
            "void_active_before": void_active(before_currency),
            "void_active_after": void_active(after_currency),
        },
        "dbt_tests": {
            "before": before_tests,
            "after": after_tests,
            "before_exit": first_build[0],
            "after_exit": second_build[0],
        },
        "snapshot_alone_after_seed": snapshot_alone,
        "database": os.path.basename(database),
        "measured": [
            "changes_applied",
            "versions",
            "recorded_a_new_version",
            "currency",
            "dbt_tests",
            "snapshot_alone_after_seed",
        ],
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(measured, fh, indent=1, sort_keys=True)
        fh.write("\n")

    print("wrote %s" % OUT)
    for arm in sorted(ARMS):
        print("  %-10s recorded a new version for %r" % (arm, recorded[arm]))
    print("  matched attributes changed for %r" % changed_a_matched_column)
    print("  the timestamp arm missed %r" % measured["missed_by_the_timestamp_arm"])
    print("  it recorded %r, where no tier reads the column that moved"
          % measured["recorded_by_the_timestamp_arm_and_unusable"])
    print("  active and void before %r, after %r"
          % (measured["currency"]["void_active_before"], measured["currency"]["void_active_after"]))
    print("  dbt tests failed before %r" % before_tests["failed"])
    print("  dbt tests failed after  %r" % after_tests["failed"])
    print("  dbt snapshot alone exited %d" % snapshot_alone["exit"])
    for line in snapshot_alone["errors"]:
        print("    %s" % line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
