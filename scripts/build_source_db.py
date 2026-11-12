"""Create the credentialing database, load the generated workflow, measure it.

    python3 scripts/build_source_db.py --dsn 'host=/tmp user=cred dbname=postgres'

Loads through psql rather than through a driver. The bulk path a real
credentialing extract uses is COPY, the operator already needs psql to
administer the database, and a Python driver would be a dependency this
repository otherwise has no use for. The cost is that this script does not run
anywhere psql is absent, which includes the machine the test suite usually runs
on. Everything it writes is committed, so the suite grades the measurement
rather than the database.

The generated rows go to data/work/ and are not committed. The counts and the
catalog answers go to measurements/credentialing.json and are.
"""

import argparse
import csv
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from credentialing import catalog, generate  # noqa: E402
from screening import leie  # noqa: E402
from screening.registries import source  # noqa: E402

WORK = os.path.join("data", "work")
OUT = os.path.join("measurements", "credentialing.json")
SCHEMA = os.path.join("credentialing", "schema.sql")

# Load order, because every table after the first two points at one of them.
LOAD_ORDER = (
    "facility",
    "provider",
    "application",
    "license",
    "verification",
    "committee_decision",
)


def psql(dsn, sql=None, file=None, quiet=True):
    cmd = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-tAX"]
    cmd += ["-f", file] if file else ["-c", sql]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(
            "psql exited %d\n  %s\n  %s" % (done.returncode, (sql or file), done.stderr.strip())
        )
    if not quiet:
        print(done.stdout.strip())
    return done.stdout.strip()


def write_csv(name, rows, columns):
    path = os.path.join(WORK, name + ".csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: ("" if row.get(c) is None else row[c]) for c in columns})
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True, help="a libpq connection string psql accepts")
    ap.add_argument(
        "--exclusions",
        default=None,
        help="exclusion list to plant from. Defaults to the downloaded file, falls back to the fixture.",
    )
    args = ap.parse_args(argv)

    src = source("leie")
    path = args.exclusions or os.path.join("data", "raw", src.local_name)
    encoding = src.encoding
    if not os.path.exists(path):
        path = os.path.join("tests", "fixtures", "leie_sample.csv")
        encoding = "utf-8"
        print("no downloaded exclusion list, planting from the fixture at %s" % path)

    rows = list(leie.read(path, encoding=encoding))
    built = generate.generate(rows)
    os.makedirs(WORK, exist_ok=True)

    psql(args.dsn, sql="DROP PUBLICATION IF EXISTS credentialing_pub;")
    psql(args.dsn, sql="DROP SCHEMA IF EXISTS credentialing CASCADE;")
    psql(args.dsn, file=SCHEMA)

    loaded = {}
    for name in LOAD_ORDER:
        table_rows = built["tables"][name]
        columns = list(table_rows[0].keys())
        csv_path = write_csv(name, table_rows, columns)
        psql(
            args.dsn,
            sql="\\copy credentialing.%s (%s) FROM '%s' WITH (FORMAT csv, HEADER true)"
            % (name, ", ".join(columns), os.path.abspath(csv_path)),
        )
        loaded[name] = int(psql(args.dsn, sql="SELECT count(*) FROM credentialing.%s;" % name))

    # The labels are the answer key for the matching that comes later. They are
    # written beside the data and never into it.
    with open(os.path.join(WORK, "labels.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=("provider_id", "label", "planted_against")
        )
        writer.writeheader()
        writer.writerows(built["labels"])

    label_counts = {}
    for item in built["labels"]:
        label_counts[item["label"]] = label_counts.get(item["label"], 0) + 1

    cat = catalog.read(lambda sql: psql(args.dsn, sql=sql))

    measured = {
        "planted": generate.Plan().as_dict(),
        "labels": label_counts,
        "rows_loaded": loaded,
        "catalog": cat,
        "exclusion_source": os.path.basename(path),
        # Named so a reader can tell a partial run from a complete one. A
        # narrowed pass that writes over a complete file reads exactly like a
        # complete one unless the file says what it covered.
        "measured": ["planted", "labels", "rows_loaded", "catalog"],
    }
    os.makedirs("measurements", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(measured, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("wrote %s" % OUT)
    for name in LOAD_ORDER:
        print("  %-20s %d" % (name, loaded[name]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
