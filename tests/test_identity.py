"""Checks on the reconciliation between the three files that spend the account namespace.

Two kinds, and the split is the one the rest of this suite uses. The first
kind calls the rules directly against a fixture with the defects planted in
it, because a rule graded only against the live tree is a rule nobody has seen
fail. Every defect in that fixture was real here on 2026-11-16 and the live
tree is clean of all of them now, so without the fixture these five rules
would only ever run where the answer is already true.

The second kind reads measurements/identity.json and asserts the live tree
stays clean, which is the thing that has to keep being true.
"""

import json
import os

from screening import identity, tfread

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BAD = os.path.join(HERE, "fixtures", "identity_bad")
MANIFEST = os.path.join(ROOT, "measurements", "identity.json")


def manifest():
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


def bad_parts():
    entries = tfread.read_dir(os.path.join(BAD, "infra"))
    created, _skipped = identity.created(entries)
    consumers = identity.consumers_of(BAD)
    variables = identity.declared_variables(entries)
    workflow = os.path.join(BAD, ".github", "workflows", "ci.yml")
    env = identity.workflow_environment(workflow)
    pairs, _calls = identity.profile_identities(
        os.path.join(BAD, "transform", "profiles", "profiles.yml")
    )
    return created, consumers, variables, env, [v for v, _d in pairs], identity.shell_variables(workflow)


def check_the_fixture_names_a_role_and_a_warehouse_nothing_creates():
    created, consumers, _v, _e, _p, _s = bad_parts()
    found = identity.every_name_a_consumer_spends_is_created(created, consumers)
    assert len(found) == 2, found
    assert any("SCREENING_TRANSFORM_WH" in line for line in found), found
    assert any("SCREENING_TRANSFORM " in line or line.endswith("SNOWFLAKE_ROLE)") for line in found), found


def check_the_live_tree_spends_no_name_nothing_creates():
    assert manifest()["problems"]["a_name_spent_and_not_created"] == []


def check_the_fixture_creates_a_role_and_a_warehouse_nothing_spends():
    created, consumers, _v, _e, _p, _s = bad_parts()
    found = identity.every_object_created_is_spent(created, consumers)
    names = {line.split()[0] for line in found}
    assert "SCREENING_XFORM_WH" in names, found
    assert "SCREENING_TRANSFORMER" in names, found


def check_the_reverse_direction_is_what_catches_the_same_defect_twice():
    """The two directions see one defect from both ends and that is the point.

    A name spent and not created and an object created and not spent are the
    same typo. A reconciliation that ran one way would still have found it
    here, and the day it does not is the day somebody deletes the consumer
    instead of fixing the name.
    """
    created, consumers, _v, _e, _p, _s = bad_parts()
    forward = identity.every_name_a_consumer_spends_is_created(created, consumers)
    reverse = identity.every_object_created_is_spent(created, consumers)
    assert forward and reverse


def check_the_live_tree_creates_nothing_at_account_level_that_nothing_spends():
    assert manifest()["problems"]["an_object_created_and_not_spent"] == []


def check_the_fixture_sets_a_variable_the_profile_does_not_read():
    _c, _co, _v, env, profile_vars, shell = bad_parts()
    found = identity.every_variable_a_job_sets_is_read(profile_vars, env, shell)
    assert len(found) == 1, found
    assert "DBT_DATABASE" in found[0], found


def check_a_variable_the_shell_dereferences_is_not_reported():
    """The rule has to see a step reading its own variable or it gets switched off."""
    env = [("PR", "${{ github.event.number }}", 1)]
    assert identity.every_variable_a_job_sets_is_read([], env, set()) != []
    assert identity.every_variable_a_job_sets_is_read([], env, {"PR"}) == []


def check_a_variable_read_by_a_third_party_is_not_reported():
    env = [("SNOWFLAKE_TOKEN_FILE_PATH", "/tmp/t", 1)]
    assert identity.every_variable_a_job_sets_is_read([], env, set()) == []


def check_the_live_tree_sets_no_variable_nothing_reads():
    assert manifest()["problems"]["a_variable_set_and_not_read"] == []


def check_the_fixture_leaves_a_required_variable_unsupplied():
    # No declared gap, because the fixture is the shape the live tree had
    # before anybody wrote one down.
    _c, _co, variables, env, _p, _s = bad_parts()
    found = identity.every_required_variable_is_supplied(variables, env, declared_gap=())
    assert len(found) == 1, found
    assert "monthly_credit_quota" in found[0], found


def check_a_variable_with_a_default_is_never_reported_as_unsupplied():
    found = identity.every_required_variable_is_supplied({"deploy_role_name": True}, [], declared_gap=())
    assert found == []


def check_the_mixed_case_variable_name_is_read():
    """The first spelling of the environment pattern refused a lower case tail.

    It therefore matched no TF_VAR line at all, so every required variable read
    as unsupplied including the four the job really did pass. A rule whose
    first version reported seventeen problems where four were already answered
    is the shape that gets switched off, so the regression is graded here.
    """
    found = identity.workflow_environment(os.path.join(BAD, ".github", "workflows", "ci.yml"))
    names = {name for name, _value, _line in found}
    assert "TF_VAR_organization_name" in names, names


def check_the_live_tree_supplies_every_required_variable():
    assert manifest()["problems"]["a_required_variable_not_supplied"] == []


def check_the_fixture_passes_a_variable_nobody_declared():
    _c, _co, variables, env, _p, _s = bad_parts()
    found = identity.every_variable_a_job_passes_is_declared(variables, env)
    assert len(found) == 1, found
    assert "nobody_declared_this" in found[0], found


def check_the_live_tree_passes_no_variable_nobody_declared():
    assert manifest()["problems"]["a_variable_passed_and_not_declared"] == []


def check_every_excused_object_is_one_the_configuration_creates():
    """A reason attached to a name nothing creates is a reason about nothing."""
    created = manifest()["created"]
    for name in manifest()["unconsumed_on_purpose"]:
        assert name in created, name


def check_every_excused_object_carries_a_reason():
    for name, reason in identity.UNCONSUMED_ON_PURPOSE.items():
        assert len(reason) > 20, name


def check_the_profile_reader_sees_every_env_var_call():
    """It reads one construct rather than YAML, so it says when it missed one."""
    found = manifest()
    assert found["profile_identities_read"] == found["profile_env_var_calls"], found


def check_the_manifest_carries_no_wall_time():
    text = json.dumps(manifest())
    for word in ("seconds_elapsed", "duration", "elapsed", "took_ms"):
        assert word not in text, word


def check_the_created_count_matches_the_created_map():
    found = manifest()
    assert found["created_count"] == len(found["created"])


def check_no_resource_name_was_skipped_as_unresolvable():
    assert manifest()["created_with_a_name_this_reader_cannot_resolve"] == []


def check_the_clone_prefix_has_a_teardown():
    assert identity.every_object_created_elsewhere_has_a_teardown() == []


def check_an_object_created_outside_the_configuration_with_no_teardown_is_refused():
    found = identity.every_object_created_elsewhere_has_a_teardown({"SOMETHING_": "why"}, {})
    assert len(found) == 1, found
    assert "names a teardown" in found[0], found


def check_a_teardown_for_something_nothing_creates_is_refused():
    found = identity.every_object_created_elsewhere_has_a_teardown({}, {"GHOST_": "a.b"})
    assert len(found) == 1, found
    assert "about nothing" in found[0], found


def check_the_named_teardown_function_exists_and_names_the_object():
    """A teardown recorded as a string is not a teardown until something calls it."""
    from orchestration import clone

    for prefix, path in identity.TORN_DOWN_BY.items():
        module, _dot, function = path.rpartition(".")
        assert module.endswith("clone"), path
        statements = getattr(clone, function)(7)
        assert statements, path
        assert any(prefix in s for s in statements), statements


def check_the_live_tree_has_a_teardown_for_everything_outside_the_configuration():
    assert manifest()["problems"]["an_object_with_no_teardown"] == []


def check_a_variable_in_neither_the_job_nor_the_declared_gap_is_refused():
    found = identity.every_required_variable_is_supplied({"brand_new": False}, [], declared_gap=())
    assert len(found) == 1, found
    assert "brand_new" in found[0], found


def check_a_declared_gap_the_job_now_supplies_is_reported_as_stale():
    """A list of deliberate omissions that outlives its reason is the next defect."""
    found = identity.every_required_variable_is_supplied(
        {"x": False}, [("TF_VAR_x", "v", 1)], declared_gap=("x",)
    )
    assert len(found) == 1, found
    assert "stale" in found[0], found


def check_a_declared_gap_for_a_variable_nobody_declares_is_refused():
    found = identity.every_required_variable_is_supplied({}, [], declared_gap=("ghost",))
    assert len(found) == 1, found
    assert "no variable block declares it" in found[0], found


def check_the_declared_gap_and_the_workflow_check_read_the_same_list():
    """One place, because two would drift and the drift would read as agreement."""
    assert identity.UNSUPPLIED_UNTIL_THERE_IS_AN_ACCOUNT
    for name in identity.UNSUPPLIED_UNTIL_THERE_IS_AN_ACCOUNT:
        assert name in manifest()["required_variables"], name
