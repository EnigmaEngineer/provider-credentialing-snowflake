"""Parse the DAGs with Airflow's own loader and record what came back.

    PYTHONPATH=<airflow target> python3.11 scripts/dag_parse.py

A parse is the only grading a project with no Airflow deployment can do, and
saying what it covers matters more than the number it produces. It catches an
import error, a duplicate task id, a cycle in the dependencies and a schedule
the scheduler cannot read. It catches nothing about whether a task works,
because no task runs.

Airflow 2 does not install on Python 3.13 and the sandbox default is 3.13, so
this runs under 3.11 against its own target directory. The suite does not
import Airflow at all. It reads the manifest this writes, which is the same
split the warehouse figures use and the reason the checks still run on a clone
with nothing installed.
"""

import argparse
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from orchestration import cycle  # noqa: E402

DAGS = os.path.join(ROOT, "orchestration", "dags")
OUT = os.path.join(ROOT, "measurements", "dag-parse.json")


def parse(folder):
    # Airflow writes a configuration file and a database wherever this points,
    # and neither belongs in the repository. A fresh directory per run also
    # means no state from the last parse can change this one.
    os.environ.setdefault("AIRFLOW_HOME", tempfile.mkdtemp(prefix="airflow-parse-"))
    # The loader reads the configuration before anything else, and a DagBag
    # built with the scheduler's defaults will happily create run records.
    os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"
    os.environ["AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION"] = "True"
    from airflow.models.dagbag import DagBag

    bag = DagBag(dag_folder=folder, include_examples=False, read_dags_from_db=False)
    return bag


def describe(dag):
    edges = sorted(
        (task.task_id, downstream)
        for task in dag.tasks
        for downstream in sorted(task.downstream_task_ids)
    )
    # `validate` is what the scheduler calls before it will schedule anything,
    # and it is the half of this measurement that is not a count.
    validated, complaint = True, None
    try:
        dag.validate()
    except Exception as exc:  # noqa: BLE001
        validated, complaint = False, "%s: %s" % (type(exc).__name__, exc)
    return {
        "dag_id": dag.dag_id,
        "schedule": str(dag.schedule_interval),
        "catchup": bool(dag.catchup),
        "max_active_runs": int(dag.max_active_runs),
        "task_ids": sorted(task.task_id for task in dag.tasks),
        "task_count": len(dag.tasks),
        "edges": [list(pair) for pair in edges],
        "edge_count": len(edges),
        "roots": sorted(task.task_id for task in dag.roots),
        "leaves": sorted(task.task_id for task in dag.leaves),
        "operators": sorted({type(task).__name__ for task in dag.tasks}),
        "validated": validated,
        "validation_complaint": complaint,
        "bash_commands": {
            task.task_id: task.bash_command
            for task in dag.tasks
            if hasattr(task, "bash_command")
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dags", default=DAGS)
    args = ap.parse_args(argv)

    import airflow

    bag = parse(args.dags)
    dags = {dag_id: describe(dag) for dag_id, dag in sorted(bag.dags.items())}
    measured = {
        "airflow_version": airflow.__version__,
        "python_version": "%d.%d.%d" % sys.version_info[:3],
        "dag_folder": os.path.relpath(args.dags, ROOT).replace(os.sep, "/"),
        "import_errors": {
            os.path.relpath(path, ROOT).replace(os.sep, "/"): text
            for path, text in sorted(bag.import_errors.items())
        },
        "dag_count": len(dags),
        "dags": dags,
        # Why each edge exists, as the relation that produced it. An edge a
        # reader cannot see the reason for is an edge somebody deletes.
        "ordering_reasons": [list(row) for row in cycle.ordering_reasons()],
        # Nothing here scheduled anything. A measurement that cannot say so is
        # a measurement somebody will read as a run.
        "scheduled_run": False,
        "measured": [
            "import_errors",
            "dags",
            "airflow_version",
            "scheduled_run",
            "ordering_reasons",
        ],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(measured, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("wrote %s" % OUT)
    print("  airflow %s on python %s" % (measured["airflow_version"], measured["python_version"]))
    for dag_id, found in sorted(dags.items()):
        print(
            "  %-20s %d tasks, %d edges, validated %s"
            % (dag_id, found["task_count"], len(found["edges"]), found["validated"])
        )
        for first, second in found["edges"]:
            print("    %s -> %s" % (first, second))
    if measured["import_errors"]:
        for path, text in sorted(measured["import_errors"].items()):
            print("  IMPORT ERROR %s\n%s" % (path, text))
        return 1
    if not all(found["validated"] for found in dags.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
