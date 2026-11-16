"""Run the second cycle in the derived order and in the wrong one, and record both.

    python3 scripts/measure_cycle_order.py

The README already quotes a catalog error for one wrong order. A cycle that
snapshots before it transforms fails on a fresh warehouse, loudly, and that is
the half anybody finds on the first run.

This measures the other direction, and the answer is not the one the rule was
written for. `int_screening__screening_currency` reads the `provider_attribute`
snapshot, so a cycle that snapshots after it builds the marts looks like it
should publish the history as it stood before this cycle. Every intermediate
model is a view, so it does not. A view is re-evaluated when something queries
it and the snapshot has run by then.

So there is a third arm. The same wrong order with the currency model
materialized as a table, which is one line in `dbt_project.yml`. That is where
the wrong order stops being loud and starts being silent.

Every arm runs the first cycle in the derived order, which is what a deployment
looks like after one good run. Then one provider's surname moves in the source,
which is a change the snapshot's check columns are chosen to record, and the
second cycle runs in the order under test.

The stage commands are not written here. They come out of
`orchestration.cycle.plan`, so a change to what a stage runs changes what this
measures. The two landing stages have no local form and a seed stands in for
them, which is what the duckdb target does everywhere else in this project.

Nothing here touches the project in the repository. Each arm gets its own copy
of `transform/` in a scratch directory, because the second cycle has to be run
against a seed that moved and the committed seeds are the answer key for
everything else.
"""

import argparse
import json
import os
import shutil
import subprocess
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from orchestration import cycle  # noqa: E402

OUT = os.path.join(ROOT, "measurements", "cycle-order.json")
SEED = os.path.join("seeds", "raw_credentialing_provider.csv")

# The provider whose surname moves between the two cycles, and what it moves
# to. The surname is one of the snapshot's check columns, so this is a change
# the history exists to record, and it is also a change that makes the
# provider's last screening stale.
MOVED_PROVIDER = 1
MOVED_SURNAME = "RENAMED"

# The assertion the wrong order is expected to silence. It is named here
# because the measurement compares the two arms on it specifically, and a
# comparison over every test would report the difference without saying which
# test carries it.
STALENESS_TEST = "assert_no_active_provider_was_screened_before_their_attributes_moved"

MATERIALIZED = re.compile(r"""materialized\s*=\s*['"]([a-z_]+)['"]""")


def dbt(project, command):
    env = dict(os.environ)
    env["DBT_PROFILES_DIR"] = os.path.join(project, "profiles")
    env.setdefault("HOME", tempfile.gettempdir())
    done = subprocess.run(
        command.split() + ["--target", "duckdb"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
    )
    return done.returncode, (done.stdout + done.stderr)


def copy_project(label, materialize_marts_as=None):
    scratch = tempfile.mkdtemp(prefix="cycle-order-%s-" % label)
    project = os.path.join(scratch, "transform")
    shutil.copytree(os.path.join(ROOT, "transform"), project)
    shutil.rmtree(os.path.join(project, "target"), ignore_errors=True)
    if materialize_marts_as is not None:
        rewrite_mart_materialization(project, materialize_marts_as)
    return project


def project_default_materialization(project, directory="intermediate"):
    """What `dbt_project.yml` says the directory's models are built as."""
    path = os.path.join(project, "dbt_project.yml")
    with open(path, encoding="utf-8") as fh:
        rows = fh.read().splitlines()
    for index, row in enumerate(rows):
        if row.strip() != "%s:" % directory:
            continue
        for later in rows[index + 1 :]:
            if later.strip().startswith("+materialized:"):
                return later.split(":", 1)[1].strip()
            if later.strip() and not later.startswith(" " * 6):
                break
    return None


def mart_materializations(project):
    """What each intermediate model's own config says.

    Two places declare this. The project file sets a default per directory and
    every model here sets it again in its own `config` call, and the model
    wins. A measurement that rewrote the project file would change nothing and
    report that the ordering does not matter.
    """
    found = {}
    base = os.path.join(project, "models", "intermediate")
    for name in sorted(os.listdir(base)):
        if not name.endswith(".sql") or name.startswith("_"):
            continue
        with open(os.path.join(base, name), encoding="utf-8") as fh:
            body = fh.read()
        match = MATERIALIZED.search(body)
        found[os.path.splitext(name)[0]] = match.group(1) if match else None
    return found


def rewrite_mart_materialization(project, materialization):
    """Change what the intermediate models are built as, in the scratch copy.

    The model's own config and not the project default, because the model's
    own config is what decides. One line per model, and that is the point. The
    ordering rule is latent while every mart is a view and it is these lines
    away from mattering.
    """
    base = os.path.join(project, "models", "intermediate")
    changed = 0
    for name in sorted(os.listdir(base)):
        if not name.endswith(".sql") or name.startswith("_"):
            continue
        path = os.path.join(base, name)
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        rewritten, count = MATERIALIZED.subn(
            "materialized='%s'" % materialization, body, count=1
        )
        if count:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(rewritten)
            changed += count
    if not changed:
        raise SystemExit("no intermediate model declares a materialization to rewrite")
    return changed


def move_the_surname(project):
    """Rewrite one provider's surname in the seed, in place."""
    path = os.path.join(project, SEED)
    with open(path, encoding="utf-8") as fh:
        rows = fh.read().splitlines()
    header = rows[0].split(",")
    at_id = header.index("provider_id")
    at_name = header.index("last_name")
    changed = 0
    for index, row in enumerate(rows[1:], start=1):
        fields = row.split(",")
        if fields[at_id] != str(MOVED_PROVIDER):
            continue
        fields[at_name] = MOVED_SURNAME
        rows[index] = ",".join(fields)
        changed += 1
    if changed != 1:
        raise SystemExit(
            "expected one row for provider %d in the seed and found %d"
            % (MOVED_PROVIDER, changed)
        )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + "\n")


def transform_commands():
    """The cycle's own commands, minus the stages with no local form."""
    return [
        stage.command
        for stage in cycle.plan()
        if stage.command and stage.command.startswith("dbt ")
    ]


def snapshot_late_order(derived):
    """The derived order with the snapshot moved behind the marts.

    This is what a cycle written as transform and then record looks like, and
    it is the order somebody writes when the history reads as an afterthought.
    The grading stage stays last.
    """
    without = [command for command in derived if command != "dbt snapshot"]
    if len(without) == len(derived):
        raise SystemExit("the derived order has no snapshot stage in it")
    at = without.index("dbt test") if "dbt test" in without else len(without)
    return without[:at] + ["dbt snapshot"] + without[at:]


def query(project, sql):
    import duckdb

    database = os.path.join(project, "target", "screening.duckdb")
    with duckdb.connect(database, read_only=True) as conn:
        return conn.execute(sql).fetchall()


def published_versions(project):
    """What the mart says about the provider's attribute history."""
    rows = query(
        project,
        "select closed_attribute_versions from intermediate."
        "int_screening__screening_currency where provider_id = %d" % MOVED_PROVIDER,
    )
    return rows[0][0] if rows else None


def recorded_versions(project):
    """What the snapshot actually holds for the same provider."""
    rows = query(
        project,
        "select count(*) from snapshots.provider_attribute where provider_id = %d "
        "and dbt_valid_to is not null" % MOVED_PROVIDER,
    )
    return rows[0][0]


def test_results(project):
    """Every test's status, out of dbt's own run results rather than its log."""
    path = os.path.join(project, "target", "run_results.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        results = json.load(fh)
    found = {}
    for result in results.get("results", []):
        name = result["unique_id"].split(".")[-1]
        found[name] = result["status"]
    return found


ANSI = re.compile(r"\x1b\[[0-9;]*m")
STAMP = re.compile(r"^\d{2}:\d{2}:\d{2}\s*")


def complaints(text):
    """Every error line dbt printed, cleaned and sorted.

    Cleaned because the raw lines carry a wall clock time and colour escapes,
    and a manifest holding either does not reproduce. Sorted because dbt runs
    the three snapshots together and which one reports first varies between
    runs, so the first line is not a stable answer and the set is.
    """
    found = set()
    for line in text.splitlines():
        stripped = STAMP.sub("", ANSI.sub("", line).strip())
        if "Error" in stripped:
            found.add(stripped[:300])
    return sorted(found)


def run_cycle(project, commands, cycle_number):
    steps = []
    for command in commands:
        code, text = dbt(project, command)
        steps.append({"command": command, "exit_code": code, "cycle": cycle_number})
        if code != 0 and command != "dbt test":
            return steps, command, complaints(text)
    return steps, None, None


def run_arm(label, second_cycle, materialize_marts_as=None):
    """The first cycle derived, then the second in the order under test."""
    derived = transform_commands()
    project = copy_project(label, materialize_marts_as)
    code, text = dbt(project, "dbt seed")
    steps = [{"command": "dbt seed", "exit_code": code, "cycle": 1}]
    if code != 0:
        return {"failed_at": "dbt seed", "complaints": complaints(text), "steps": steps}
    first, failed, complaint = run_cycle(project, derived, 1)
    steps += first
    if failed:
        return {"failed_at": failed, "complaints": complaint, "steps": steps}

    move_the_surname(project)
    code, _text = dbt(project, "dbt seed --full-refresh")
    steps.append({"command": "dbt seed --full-refresh", "exit_code": code, "cycle": 2})
    second, failed, complaint = run_cycle(project, second_cycle, 2)
    steps += second

    tests = test_results(project)
    return {
        "order": list(second_cycle),
        "marts_materialized_as": materialize_marts_as or "as the project configures them",
        "failed_at": failed,
        "complaints": complaint or [],
        "steps": steps,
        "test_exit_code": next(
            (step["exit_code"] for step in reversed(steps) if step["command"] == "dbt test"),
            None,
        ),
        "staleness_test": tests.get(STALENESS_TEST),
        "tests_failing": sorted(
            name for name, status in tests.items() if status not in ("pass", "success")
        ),
        "published_closed_versions": published_versions(project),
        "recorded_closed_versions": recorded_versions(project),
    }


def snapshot_first_on_an_empty_warehouse():
    """The loud order, which the README already quotes.

    Measured again here so both directions sit in one manifest and the
    difference between them is the thing being published.
    """
    project = copy_project("snapshot-first")
    code, text = dbt(project, "dbt seed")
    if code != 0:
        return {"exit_code": code, "complaints": complaints(text)}
    code, text = dbt(project, "dbt snapshot")
    return {"exit_code": code, "complaints": complaints(text)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)

    derived = transform_commands()
    late = snapshot_late_order(derived)

    measured = {
        "derived_order": derived,
        "snapshot_late_order": late,
        "moved_provider": MOVED_PROVIDER,
        "mart_materialization_as_committed": mart_materializations(
            os.path.join(ROOT, "transform")
        ),
        "project_default_materialization": project_default_materialization(
            os.path.join(ROOT, "transform")
        ),
        "staleness_test": STALENESS_TEST,
        "derived": run_arm("derived", derived),
        "snapshot_late": run_arm("snapshot-late", late),
        "snapshot_late_with_table_marts": run_arm("snapshot-late-table", late, "table"),
        "snapshot_first_on_an_empty_warehouse": snapshot_first_on_an_empty_warehouse(),
        "measured": [
            "derived",
            "snapshot_late",
            "snapshot_late_with_table_marts",
            "snapshot_first_on_an_empty_warehouse",
            "derived_order",
            "snapshot_late_order",
            "mart_materialization_as_committed",
            "project_default_materialization",
        ],
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(measured, fh, indent=1, sort_keys=True)
        fh.write("\n")

    print("wrote %s" % args.out)
    print("  derived order   %s" % " then ".join(derived))
    print("  snapshot late   %s" % " then ".join(late))
    for arm in ("derived", "snapshot_late", "snapshot_late_with_table_marts"):
        found = measured[arm]
        print(
            "  %-30s dbt test exits %s, %s is %s, mart says %s, snapshot holds %s"
            % (
                arm,
                found["test_exit_code"],
                STALENESS_TEST.split("_was_")[0],
                found["staleness_test"],
                found["published_closed_versions"],
                found["recorded_closed_versions"],
            )
        )
    first = measured["snapshot_first_on_an_empty_warehouse"]
    print("  snapshot first on an empty warehouse exits %d" % first["exit_code"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
