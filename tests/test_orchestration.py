"""Checks on the monthly cycle's graph and on the parse of the DAG built from it.

Two kinds here and the split is deliberate. The first kind calls the derivation
directly with answers written out, because a check that only reads
`measurements/dag-parse.json` cannot disagree with code that changed after the
manifest was written. That is the 2026-11-14 lesson and it cost a module half
its mutation score. The second kind reads the manifest, because the parse needs
Airflow and Airflow needs a Python this suite does not insist on.
"""

import json
import os
import re

from orchestration import clone, cycle

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROJECT = os.path.join(ROOT, "transform")
PARSE = os.path.join(ROOT, "measurements", "dag-parse.json")


def project():
    return cycle.read_project(PROJECT)


def manifest():
    with open(PARSE, encoding="utf-8") as fh:
        return json.load(fh)


def only_dag(found):
    assert found["dag_count"] == 1, found["dag_count"]
    return found["dags"]["monthly_screening"]


def sql_on_disk():
    """Model and snapshot file stems, counted from the files and not the code."""
    stems = set()
    for root in ("models", "snapshots"):
        for base, _dirs, names in os.walk(os.path.join(PROJECT, root)):
            for name in names:
                if name.endswith(".sql") and not name.startswith("_"):
                    stems.add(os.path.splitext(name)[0])
    return stems


# The derivation, called directly.


def check_the_derivation_covers_every_model_and_snapshot_file_in_both_directions():
    found = set(project().nodes)
    on_disk = sql_on_disk()
    assert found == on_disk, sorted(found ^ on_disk)


def check_every_snapshot_reads_a_staging_model():
    # This is the premise the whole ordering rests on. If it stops being true
    # the rule is still enforced and the reason for it has gone.
    found = project()
    for name, node in sorted(found.nodes.items()):
        if node.kind != "snapshot":
            continue
        staging = [
            read
            for read in node.reads
            if read in found.nodes and found.nodes[read].directory == "staging"
        ]
        assert staging, (name, node.reads)


def check_the_history_stage_runs_after_the_staging_stage():
    order = [stage.name for stage in cycle.plan(project())]
    assert order.index("transform_staging") < order.index("record_attribute_history"), order


def check_declaring_the_history_first_does_not_change_the_order():
    """The claim that the order cannot be written wrongly, as a check.

    The stages are declared with the snapshot ahead of the transform, which is
    exactly the mistake the README quotes a catalog error for, and the plan
    comes back in the same order it does from the real declaration.
    """
    found = project()
    declared = list(cycle.stages(found))
    names = [stage.name for stage in declared]
    history = declared.pop(names.index("record_attribute_history"))
    declared.insert(0, history)
    assert [stage.name for stage in declared][0] == "record_attribute_history"
    wrong = [stage.name for stage in cycle.plan(found, declared)]
    right = [stage.name for stage in cycle.plan(found)]
    assert wrong == right, (wrong, right)


def check_a_relation_no_stage_produces_is_refused():
    found = project()
    declared = [
        stage for stage in cycle.stages(found) if stage.name != "record_attribute_history"
    ]
    try:
        cycle.plan(found, declared)
    except cycle.CycleOrderError as exc:
        assert "no stage produces" in str(exc), str(exc)
    else:
        raise AssertionError("dropping the snapshot stage was accepted")


def check_two_stages_producing_one_relation_are_refused():
    found = project()
    declared = list(cycle.stages(found))
    declared.append(
        cycle.Stage("again", "dbt snapshot", "", found.snapshots(), note="a second owner")
    )
    try:
        cycle.owner_of(declared)
    except cycle.CycleOrderError as exc:
        assert "produced by both" in str(exc), str(exc)
    else:
        raise AssertionError("two stages producing one snapshot was accepted")


def check_a_dependency_pointing_both_ways_is_refused():
    # Two stages that each produce something the other reads. There is no
    # order for this and the derivation has to say so rather than pick one.
    nodes = {
        "first": cycle.Node("first", "model", "staging", ["second"]),
        "second": cycle.Node("second", "model", "staging", ["first"]),
    }
    found = cycle.Project(nodes, ())
    declared = [
        cycle.Stage("a", "dbt run --select first", "first", ("first",)),
        cycle.Stage("b", "dbt run --select second", "second", ("second",)),
    ]
    try:
        cycle.plan(found, declared)
    except cycle.CycleOrderError as exc:
        assert "cannot be ordered" in str(exc), str(exc)
    else:
        raise AssertionError("a pair of stages reading each other was ordered")


def check_the_unlanded_sources_are_exactly_the_ones_named():
    found = project()
    unlanded = {
        key.split(":", 1)[1].split(".", 1)[0] for key in cycle.unlanded_sources(found)
    }
    named = set(cycle.SOURCES_THE_CYCLE_DOES_NOT_LAND)
    assert unlanded == named, sorted(unlanded ^ named)


def check_the_grading_stage_runs_last():
    order = [stage.name for stage in cycle.plan(project())]
    assert order[-1] == "grade_the_cycle", order


def check_the_reduced_edges_order_the_stages_the_same_way():
    found = project()
    reduced = cycle.dependencies(found)
    order = [stage.name for stage in cycle.plan(found)]
    at = {name: index for index, name in enumerate(order)}
    for name, parents in sorted(reduced.items()):
        for parent in sorted(parents):
            assert at[parent] < at[name], (parent, name, order)


def check_no_reduced_edge_is_implied_by_the_others():
    found = project()
    reduced = {name: set(parents) for name, parents in cycle.dependencies(found).items()}
    for name in sorted(reduced):
        for parent in sorted(reduced[name]):
            others = reduced[name] - {parent}
            reach = set()
            stack = list(others)
            while stack:
                here = stack.pop()
                if here in reach:
                    continue
                reach.add(here)
                stack.extend(reduced.get(here, ()))
            assert parent not in reach, (parent, name)


def check_every_stage_that_needs_an_account_says_so():
    # The two landing stages are the account halves of the blueprint line and
    # the rest of the cycle is not. A stage that quietly needed an account
    # would make the whole cycle unrunnable and read as runnable.
    needs = sorted(stage.name for stage in cycle.stages(project()) if stage.needs_account)
    assert needs == ["land_registry_files", "replicate_credentialing"], needs


def check_the_stage_with_no_command_is_the_one_with_no_account():
    waiting = sorted(stage.name for stage in cycle.stages(project()) if stage.command is None)
    assert waiting == ["replicate_credentialing"], waiting


# The parse manifest.


def check_the_parse_manifest_has_no_import_errors():
    found = manifest()
    assert found["import_errors"] == {}, found["import_errors"]


def check_the_parse_manifest_was_taken_against_airflow_2():
    # Composer 2 and the Astronomer images this targets run Airflow 2, and the
    # authoring imports differ between 2 and 3.
    version = manifest()["airflow_version"]
    assert version.startswith("2."), version


def check_the_parse_says_nothing_was_scheduled():
    assert manifest()["scheduled_run"] is False


def check_the_dag_validated():
    dag = only_dag(manifest())
    assert dag["validated"] is True, dag["validation_complaint"]


def check_the_parsed_tasks_are_exactly_the_derived_stages():
    dag = only_dag(manifest())
    derived = sorted(stage.name for stage in cycle.plan(project()))
    assert sorted(dag["task_ids"]) == derived, sorted(set(dag["task_ids"]) ^ set(derived))


def check_the_parsed_edges_are_exactly_the_derived_edges():
    dag = only_dag(manifest())
    parsed = {(first, second) for first, second in dag["edges"]}
    derived = {
        (parent, name)
        for name, parents in cycle.dependencies(project()).items()
        for parent in parents
    }
    assert parsed == derived, sorted(parsed ^ derived)


def check_the_parsed_dag_asks_for_a_monthly_schedule():
    dag = only_dag(manifest())
    schedule = dag["schedule"]
    fields = schedule.split()
    assert len(fields) == 5, schedule
    # A day of month and a month of every, which is once a month. An hourly or
    # daily cron here would still parse and would screen against the same file
    # thirty times.
    assert fields[2] != "*" and fields[3] == "*", schedule


def check_the_parsed_dag_does_not_backfill():
    dag = only_dag(manifest())
    assert dag["catchup"] is False
    assert dag["max_active_runs"] == 1, dag["max_active_runs"]


def check_every_command_the_parsed_dag_holds_names_something_that_exists():
    dag = only_dag(manifest())
    missing = []
    for task, command in sorted(dag["bash_commands"].items()):
        for token in command.split():
            if token.endswith(".py") and not os.path.exists(os.path.join(ROOT, token)):
                missing.append((task, token))
    assert not missing, missing


def check_the_waiting_stage_has_no_command_in_the_parsed_dag():
    dag = only_dag(manifest())
    waiting = [stage.name for stage in cycle.stages(project()) if stage.command is None]
    for name in waiting:
        assert name not in dag["bash_commands"], name
    assert "EmptyOperator" in dag["operators"], dag["operators"]


# The per pull request clone. Statements and not a deployment, because there is
# no account, so what is graded is the name and the lifecycle.


def check_the_clone_name_comes_from_the_pull_request_number():
    assert clone.database_name(7) == "SCREENING_CI_PR_7"
    assert clone.database_name(1204) == "SCREENING_CI_PR_1204"


def check_a_clone_name_built_from_anything_but_an_integer_is_refused():
    # The identifier goes into DDL with no way to parameterise it, so a branch
    # name reaching this is a string concatenated into a statement.
    for bad in ("12", "main; drop database screening_analytics", None, 1.0, True, 0, -3):
        try:
            clone.database_name(bad)
        except clone.CloneNameError:
            continue
        raise AssertionError("accepted %r as a pull request number" % (bad,))


def check_the_create_and_the_drop_name_the_same_database():
    created = clone.create_statements(31)
    dropped = clone.drop_statements(31)
    name = clone.database_name(31)
    assert all(name in statement for statement in created), created
    assert all(name in statement for statement in dropped), dropped


def check_the_clone_is_transient_and_keeps_no_history():
    # The half that matters when the teardown does not run. A clone nothing
    # drops stops costing within a day rather than forever.
    created = " ".join(clone.create_statements(5)).lower()
    assert "transient database" in created, created
    assert "data_retention_time_in_days = 0" in created, created


def check_the_drop_tolerates_a_clone_that_was_never_created():
    dropped = clone.drop_statements(5)[0].lower()
    assert "if exists" in dropped, dropped


def check_the_clone_never_drops_the_database_it_clones():
    source = clone.SOURCE_DATABASE.lower()
    for number in (1, 2, 99):
        for statement in clone.drop_statements(number):
            assert source not in statement.lower(), statement


def check_the_clone_job_builds_its_statements_from_the_module():
    # The statements have one home. A job writing the DDL inline would be a
    # second place it lives and nothing would grade it.
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as fh:
        body = fh.read()
    assert "orchestration.clone" in body, "the clone job does not call the module"
    assert "clone %s" % clone.SOURCE_DATABASE not in body, "the DDL is inline in the workflow"


# The cycle order measurement. Two orders and three arms, because the second
# arm came back identical to the first and the reason was the materialisation.


def cycle_order():
    with open(os.path.join(ROOT, "measurements", "cycle-order.json"), encoding="utf-8") as fh:
        return json.load(fh)


def check_the_measured_derived_order_is_the_order_the_cycle_derives():
    found = cycle_order()
    derived = [
        stage.command
        for stage in cycle.plan(project())
        if stage.command and stage.command.startswith("dbt ")
    ]
    assert found["derived_order"] == derived, (found["derived_order"], derived)


def check_the_measured_wrong_order_puts_the_snapshot_behind_the_marts():
    found = cycle_order()
    late = found["snapshot_late_order"]
    assert late.index("dbt snapshot") > late.index("dbt run --select intermediate"), late
    assert late[-1] == "dbt test", late


def check_the_two_orders_agree_while_every_mart_is_a_view():
    # Measured and not assumed. The rule was written for a stale number and
    # the number is not stale, because a view is evaluated when it is read.
    found = cycle_order()
    right, late = found["derived"], found["snapshot_late"]
    assert right["published_closed_versions"] == late["published_closed_versions"], (
        right["published_closed_versions"],
        late["published_closed_versions"],
    )
    assert right["staleness_test"] == late["staleness_test"], (
        right["staleness_test"],
        late["staleness_test"],
    )


def check_the_derived_order_lets_the_staleness_assertion_fire():
    found = cycle_order()["derived"]
    assert found["staleness_test"] == "fail", found["staleness_test"]
    assert found["published_closed_versions"] == found["recorded_closed_versions"], found


def check_the_wrong_order_silences_the_staleness_assertion_when_a_mart_is_a_table():
    """The finding, as a check.

    The mart publishes a history with nothing in it, the snapshot holds the
    version that moved, and the assertion written to catch exactly this passes.
    """
    found = cycle_order()["snapshot_late_with_table_marts"]
    assert found["staleness_test"] == "pass", found["staleness_test"]
    assert found["test_exit_code"] == 0, found["test_exit_code"]
    assert found["published_closed_versions"] == 0, found["published_closed_versions"]
    assert found["recorded_closed_versions"] == 1, found["recorded_closed_versions"]


def check_the_snapshot_cannot_run_first_on_an_empty_warehouse():
    found = cycle_order()["snapshot_first_on_an_empty_warehouse"]
    assert found["exit_code"] != 0, found
    assert found["complaints"], found
    # The staging schema and not any error. A snapshot failing for some other
    # reason would satisfy a check that only read the exit code.
    assert any(
        "staging" in line and "does not exist" in line for line in found["complaints"]
    ), found["complaints"]


def check_no_complaint_in_the_manifest_carries_a_wall_clock_time():
    # A manifest that does not reproduce is a manifest whose diff says nothing.
    # dbt stamps every line it prints and colours it, and both had to come off.
    found = cycle_order()
    lines = list(found["snapshot_first_on_an_empty_warehouse"]["complaints"])
    for arm in ("derived", "snapshot_late", "snapshot_late_with_table_marts"):
        lines += found[arm].get("complaints") or []
    for line in lines:
        assert not re.match(r"^\d{2}:\d{2}:\d{2}", line), line
        assert "\x1b" not in line, line


def check_every_mart_declares_the_materialization_the_project_defaults_to():
    """The project default is a decoy while every model sets its own.

    `dbt_project.yml` says what the intermediate models are built as and each
    one says it again in its own config. The model wins. So a change to the
    project file changes nothing, which is how the arm above first came back
    saying the order did not matter.
    """
    found = cycle_order()
    default = found["project_default_materialization"]
    declared = found["mart_materialization_as_committed"]
    assert default, "the project declares no default for the intermediate models"
    disagreeing = sorted(
        name for name, value in declared.items() if value not in (None, default)
    )
    assert not disagreeing, (default, {name: declared[name] for name in disagreeing})


# Two cases added because a mutation pass on the day the module landed found
# nothing exercised them. Both are the 2026-10-15 shape, a filter no input
# reaches, and the answer is an input rather than a deletion.


def check_two_independent_stages_run_in_the_order_they_are_declared():
    """The tiebreak the module documents, graded.

    Nothing in this project depends on it, because the only independent pair
    is the two landing stages and the scheduler runs those together. The
    docstring claims declaration order anyway, so the claim gets a check.
    """
    nodes = {
        "left": cycle.Node("left", "model", "staging", []),
        "right": cycle.Node("right", "model", "staging", []),
    }
    found = cycle.Project(nodes, ())
    first = cycle.Stage("first", "dbt run --select left", "left", ("left",))
    second = cycle.Stage("second", "dbt run --select right", "right", ("right",))
    forward = [stage.name for stage in cycle.plan(found, [first, second])]
    backward = [stage.name for stage in cycle.plan(found, [second, first])]
    assert forward == ["first", "second"], forward
    assert backward == ["second", "first"], backward


def check_a_source_the_cycle_does_not_land_and_does_not_name_is_refused():
    """The refusal the real project never reaches, because its one gap is named.

    A second unlanded source is a model reading a relation the cycle has no
    task for, and the cycle would run green against whatever that relation
    last held.
    """
    key = cycle.source_key("elsewhere", "a_table")
    nodes = {
        "reader": cycle.Node("reader", "model", "staging", [key]),
    }
    found = cycle.Project(nodes, (key,))
    declared = [cycle.Stage("only", "dbt run --select staging", "staging", ("reader",))]
    try:
        cycle.plan(found, declared)
    except cycle.CycleOrderError as exc:
        assert "does not land and does not name" in str(exc) or "does not land" in str(exc), str(exc)
    else:
        raise AssertionError("a source nothing lands and nothing names was accepted")


def check_every_derived_edge_has_a_reason_in_the_manifest():
    """An edge a reader cannot see the reason for is an edge somebody deletes.

    The reason is the relation that produced the dependency, so every edge in
    the parsed DAG has at least one row naming a `ref` or a source behind it.
    """
    found = manifest()
    reasons = {(row[1], row[0]) for row in found["ordering_reasons"]}
    edges = {(first, second) for first, second in only_dag(found)["edges"]}
    unexplained = sorted(edges - reasons)
    assert not unexplained, unexplained


def check_the_reasons_in_the_manifest_are_the_ones_the_derivation_gives():
    found = [list(row) for row in cycle.ordering_reasons(project())]
    assert manifest()["ordering_reasons"] == found, "the manifest is stale"
