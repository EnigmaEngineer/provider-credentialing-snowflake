"""The committed matching measurement, and the two arms behind it.

The arms are the reason this module exists. The name and state tier reads a
column the generator did not plant until today, and a tier whose answer does
not move between a sample where the column is planted and one where it is not
is a tier reading something other than that column.
"""

import json
import os

from credentialing import generate
from screening import evaluate, leie, match

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "measurements", "matching.json")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "leie_sample.csv")
ARMS = ("state_planted", "state_from_facility")


def manifest():
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


def fixture_rows():
    return list(leie.read(FIXTURE, encoding="utf-8"))


def check_the_manifest_names_every_arm_it_holds_and_holds_every_arm_it_names():
    m = manifest()
    named = m.get("measured")
    assert named, m.keys()
    for arm in named:
        assert arm in m, arm
    for arm in ARMS:
        assert arm in named, arm
    # The other direction. A manifest naming two arms and carrying three has a
    # section nothing grades.
    carried = [k for k in m if isinstance(m[k], dict) and "tiers" in m[k]]
    assert sorted(carried) == sorted(named), (carried, named)


def check_every_arm_reports_all_three_tiers_and_the_cascade():
    m = manifest()
    for arm in ARMS:
        tiers = m[arm]["tiers"]
        for tier in match.TIER_ORDER:
            assert tier in tiers, (arm, tier)
            assert "provider_graded" in tiers[tier], (arm, tier)
            assert "pair_graded" in tiers[tier], (arm, tier)
        assert "cascade" in tiers, arm


def check_the_label_counts_are_the_plan_in_both_arms():
    plan = generate.Plan().as_dict()
    m = manifest()
    for arm in ARMS:
        assert m[arm]["labels"] == plan, (arm, m[arm]["labels"])


def check_planting_the_state_moves_the_state_tier_and_nothing_above_it():
    # The finding, asserted rather than described. The two stronger tiers read
    # no state, so their answers have to be identical across the arms, and the
    # state tier has to reach more providers in the planted arm. A change that
    # moves tier one or tier two here has changed something it should not have.
    m = manifest()
    planted = m["state_planted"]["tiers"]
    control = m["state_from_facility"]["tiers"]
    for tier in (match.TIER1, match.TIER2):
        assert planted[tier] == control[tier], tier
    assert planted[match.TIER3]["flagged"] > control[match.TIER3]["flagged"], (
        planted[match.TIER3]["flagged"],
        control[match.TIER3]["flagged"],
    )


def check_the_control_arm_clears_near_misses_the_planted_arm_holds():
    m = manifest()
    planted = m["state_planted"]["review"][generate.NEAR_MISS]
    control = m["state_from_facility"]["review"][generate.NEAR_MISS]
    assert planted["cleared_with_nobody_looking"] == 0, planted
    assert control["cleared_with_nobody_looking"] > 0, control
    assert planted["providers"] == control["providers"]


def check_the_cascade_precision_is_worse_in_the_arm_that_works():
    # Stated this way round on purpose. The control arm reports the better
    # precision and it is the arm where the review tier reaches almost nobody,
    # so a precision figure read on its own points at the wrong design.
    m = manifest()
    planted = m["state_planted"]["tiers"]["cascade"]["provider_graded"]["precision"]
    control = m["state_from_facility"]["tiers"]["cascade"]["provider_graded"]["precision"]
    assert planted < control, (planted, control)


def check_the_stronger_tiers_pair_grade_perfectly_and_the_review_tier_cannot():
    m = manifest()
    for arm in ARMS:
        tiers = m[arm]["tiers"]
        for tier in (match.TIER1, match.TIER2):
            assert tiers[tier]["pair_graded"]["precision"] == 1.0, (arm, tier)
        # Nothing the review tier flags was planted against a record, so it has
        # no pair to be right about. A figure above zero here means a provider
        # labelled as not being the excluded person was planted against one.
        assert tiers[match.TIER3]["pair_graded"]["true_positive"] == 0, arm


def check_the_queue_split_adds_up_to_the_sample_in_both_arms():
    m = manifest()
    for arm in ARMS:
        queue = m[arm]["queue"]
        assert (
            queue["decided_by_identifier"]
            + queue["sent_to_review"]
            + queue["cleared_with_no_match"]
        ) == queue["providers"] == generate.Plan().total(), (arm, queue)


def check_the_manifest_names_the_exclusion_file_and_the_seed():
    m = manifest()
    assert m["exclusion_file"], m
    assert len(m["exclusion_sha256"]) == 64, m["exclusion_sha256"]
    assert m["exclusion_records"] > 0
    # The sample is a function of the seed and the file. Without both, nothing
    # can reproduce these figures and the committed seed can change without a
    # single check noticing.
    from scripts import measure_matching

    assert m["seed"] == measure_matching.DEFAULT_SEED, (m["seed"], measure_matching.DEFAULT_SEED)


def check_each_arm_says_which_arm_it_is():
    # The label is the only thing in the file that says which arm a block of
    # figures came from. Swapping the two labels leaves every number where it
    # is and makes the whole manifest say the opposite of what it measured.
    m = manifest()
    assert "planted" in m["state_planted"]["arm"], m["state_planted"]["arm"]
    assert "not planted" in m["state_from_facility"]["arm"], m["state_from_facility"]["arm"]


def check_the_whole_thing_runs_on_the_committed_fixture():
    # The fixture is nine rows and carries too few keys for the real plan, so
    # the plan is scaled down here. The point is that every code path the
    # measurement script walks is exercised by the suite on a machine that
    # never downloaded anything.
    rows = fixture_rows()
    plan = generate.Plan(exact_identifier=1, name_and_birth=1, near_miss=1, unrelated=2)
    built = generate.generate(rows, plan=plan)
    labels = {d["provider_id"]: d["label"] for d in built["labels"]}
    planted = {d["provider_id"]: d["planted_against"] for d in built["labels"]}
    states = {row["provider_id"]: row["state"] for row in built["tables"]["license"]}
    index = match.Index(rows)
    results = match.match_all(built["tables"]["provider"], index, states)
    for result in results:
        result["planted_match"] = match.record_identities(rows, result["records"])
    answer = evaluate.per_tier(results, labels, planted, match.TIER_ORDER)
    assert answer[match.TIER1]["flagged"] == 1, answer[match.TIER1]
    assert answer[match.TIER2]["flagged"] == 1, answer[match.TIER2]
    assert answer["cascade"]["excluded_and_cleared"] == 0, answer["cascade"]


def check_the_planting_is_what_decides_the_state_on_the_fixture():
    # Not a comparison of the two arms' tier counts. On nine rows the facility
    # draw happens to give the near miss provider the exclusion record's own
    # state, so both arms reach the state tier and a check comparing the counts
    # passes without the planting doing anything. This grades the planting
    # itself instead: in the planted arm the licence state is the exclusion
    # record's, and in the control arm it is whatever the facility draw gave.
    rows = fixture_rows()
    plan = generate.Plan(exact_identifier=1, name_and_birth=1, near_miss=1, unrelated=2)
    facility_states = {state for _id, _name, state in generate.FACILITIES}
    key_state, _spread = generate.key_states(rows)

    planted = generate.generate(rows, plan=plan, plant_state=True)
    control = generate.generate(rows, plan=plan, plant_state=False)
    labels = {d["provider_id"]: d["label"] for d in planted["labels"]}
    planted_states = {r["provider_id"]: r["state"] for r in planted["tables"]["license"]}
    control_states = {r["provider_id"]: r["state"] for r in control["tables"]["license"]}

    wanted = set(key_state.values())
    fallback = [
        pid for pid, lab in labels.items()
        if lab in (generate.NAME_AND_BIRTH, generate.NEAR_MISS)
    ]
    assert fallback, labels
    for pid in fallback:
        assert planted_states[pid] in wanted, (pid, planted_states[pid], wanted)
        assert control_states[pid] in facility_states, (pid, control_states[pid])
    # At least one of them has to be a state the facilities do not carry, or
    # the two arms are indistinguishable on this fixture and the check above
    # would pass on a generator that plants nothing.
    assert any(planted_states[pid] not in facility_states for pid in fallback), planted_states


def check_the_two_arms_differ_on_the_real_sample():
    # The fixture cannot show this and the manifest can. Stated as a separate
    # check so the fixture check above is not read as evidence of it.
    m = manifest()
    planted = m["state_planted"]["tiers"][match.TIER3]["flagged"]
    control = m["state_from_facility"]["tiers"][match.TIER3]["flagged"]
    assert planted >= control * 2, (planted, control)
