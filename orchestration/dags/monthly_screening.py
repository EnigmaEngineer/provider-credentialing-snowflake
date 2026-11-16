"""The monthly screening cycle, for Airflow 2.

Airflow 2 and not 3. Composer 2 and the Astronomer runtime images this targets
run Airflow 2, and the authoring imports differ between the two, so a DAG
written for 3.x would be written for a runtime the declared environment does
not have.

The task order is not written here. `orchestration.cycle.plan` derives it from
the project's own SQL and this module walks the answer. The reason is in that
module's docstring and the short version is that an order written by hand is an
order the next edit gets wrong.
"""

from __future__ import annotations

import os
import sys

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator

# Airflow puts the dags folder on the path and not its parent, so the package
# this DAG is built out of has to be found explicitly. On the image the
# repository is installed and this is a no-op.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from orchestration import cycle  # noqa: E402

TRANSFORM = "cd transform && DBT_PROFILES_DIR=profiles"

# The screening runs after the exclusion list is republished. OIG publishes
# monthly and the list is up early in the month, so the fourth day at 04:00
# gives it room and still lands the cycle inside the thirty day window the
# currency rule reads.
SCHEDULE = "0 4 4 * *"

default_args = {
    # A cycle that half ran is worse than one that did not. Every stage after
    # a failure is held rather than run against a relation the failed stage
    # was meant to build.
    "retries": 1,
    "retry_delay": pendulum.duration(minutes=10),
    "depends_on_past": False,
}

with DAG(
    dag_id="monthly_screening",
    description="Exclusion screening for every active provider, once per published list",
    schedule=SCHEDULE,
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    # No backfill. A screening answer is a statement about the list that was
    # current when it ran, and running last March's cycle today would write a
    # screening event dated then against the file published now.
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["screening", "monthly"],
) as dag:
    # Read once. Airflow re-imports every DAG file on a schedule, and each
    # derivation opens fifteen files under `transform/`, so calling this twice
    # per parse is twice the work for the same answer.
    project = cycle.read_project()

    tasks = {}
    for stage in cycle.plan(project):
        if stage.command is None:
            # A stage with nothing to run is a boundary. The system behind it
            # runs on its own schedule and what belongs here is a sensor on
            # the account this project does not have.
            tasks[stage.name] = EmptyOperator(task_id=stage.name, doc_md=stage.note)
            continue
        command = stage.command
        if command.startswith("dbt "):
            command = "%s %s" % (TRANSFORM, command)
        tasks[stage.name] = BashOperator(
            task_id=stage.name,
            bash_command=command,
            doc_md=stage.note,
        )

    # The edges come from the same derivation as the order. Chaining the
    # stages in a line would also run, and it would say the marts wait on the
    # history, which is not true and is the kind of claim a reader believes.
    for name, parents in sorted(cycle.dependencies(project).items()):
        for parent in sorted(parents):
            tasks[parent] >> tasks[name]
