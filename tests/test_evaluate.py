"""Grading the grader.

The numbers this module produces are the ones a reader of the README trusts, so
the arithmetic gets its own checks and so does the thing the arithmetic is
about: a tier can be right about the provider and wrong about the record, and
provider grading cannot see the difference.
"""

from credentialing import generate
from screening import evaluate, match


def _result(pid, tier, planted_match=()):
    return {
        "provider_id": pid,
        "tier": tier,
        "records": (),
        "planted_match": frozenset(planted_match),
    }


def check_a_rate_with_no_denominator_is_none_rather_than_zero():
    answer = evaluate._rates(0, 0, 0)
    assert answer["precision"] is None, answer
    assert answer["recall"] is None, answer


def check_the_counts_travel_with_the_rate():
    answer = evaluate._rates(3, 1, 2)
    assert answer["true_positive"] == 3 and answer["false_positive"] == 1
    assert answer["false_negative"] == 2
    assert abs(answer["precision"] - 0.75) < 1e-9
    assert abs(answer["recall"] - 0.6) < 1e-9


def check_a_near_miss_is_a_negative_in_the_answer_key():
    assert generate.NEAR_MISS in evaluate.NOT_EXCLUDED
    assert generate.NEAR_MISS not in evaluate.TRULY_EXCLUDED
    assert generate.UNRELATED in evaluate.NOT_EXCLUDED
    assert set(evaluate.TRULY_EXCLUDED) == {generate.EXACT_IDENTIFIER, generate.NAME_AND_BIRTH}


def check_pair_grading_catches_a_match_to_the_wrong_record():
    labels = {1: generate.EXACT_IDENTIFIER, 2: generate.EXACT_IDENTIFIER}
    planted = {1: "1215968847", 2: "1972902351"}
    results = [
        _result(1, match.TIER1, {"1215968847"}),
        # Flagged, genuinely excluded, and matched to somebody else's record.
        _result(2, match.TIER1, {"1558922021"}),
    ]
    answer = evaluate.per_tier(results, labels, planted, (match.TIER1,))[match.TIER1]
    assert answer["provider_graded"]["precision"] == 1.0, answer["provider_graded"]
    assert answer["pair_graded"]["precision"] == 0.5, answer["pair_graded"]
    assert answer["pair_graded"]["true_positive"] == 1


def check_the_pair_graded_false_positives_are_the_matches_that_missed():
    # Two hits and one miss, so the hit count and the miss count differ. One of
    # each leaves the two halves of that sum interchangeable, which is how the
    # version without the negation survived a mutation pass.
    labels = {n: generate.EXACT_IDENTIFIER for n in (1, 2, 3)}
    planted = {1: "A", 2: "B", 3: "C"}
    results = [
        _result(1, match.TIER1, {"A"}),
        _result(2, match.TIER1, {"B"}),
        _result(3, match.TIER1, {"Z"}),
    ]
    answer = evaluate.per_tier(results, labels, planted, (match.TIER1,))[match.TIER1]
    assert answer["pair_graded"]["true_positive"] == 2, answer["pair_graded"]
    assert answer["pair_graded"]["false_positive"] == 1, answer["pair_graded"]
    assert answer["provider_graded"]["false_positive"] == 0, answer["provider_graded"]


def check_a_tier_that_reached_one_of_three_excluded_providers_misses_two():
    # One true positive and one false negative is symmetric, so the inverted
    # comparison produces the same recall. Three excluded providers with one
    # found makes the two counts differ.
    labels = {
        1: generate.EXACT_IDENTIFIER,
        2: generate.NAME_AND_BIRTH,
        3: generate.NAME_AND_BIRTH,
        4: generate.UNRELATED,
    }
    results = [
        _result(1, match.TIER1),
        _result(2, None),
        _result(3, match.TIER2),
        _result(4, None),
    ]
    answer = evaluate.per_tier(results, labels, None, (match.TIER1,))[match.TIER1]
    assert answer["provider_graded"]["true_positive"] == 1, answer
    assert answer["provider_graded"]["false_negative"] == 2, answer
    assert answer["provider_graded"]["recall"] == 1 / 3, answer


def check_pair_grading_is_absent_when_no_answer_key_was_given():
    labels = {1: generate.EXACT_IDENTIFIER}
    results = [_result(1, match.TIER1, {"1215968847"})]
    answer = evaluate.per_tier(results, labels, None, (match.TIER1,))[match.TIER1]
    assert "pair_graded" not in answer, answer


def check_a_provider_planted_against_nothing_can_never_pair_grade_true():
    for planted in (None, ""):
        assert evaluate._hit_the_planted_record(_result(1, match.TIER3, {"X"}), planted) is False


def check_the_pair_test_answers_both_ways_round():
    # Asymmetric on purpose. A symmetric pair of cases is satisfied by the
    # comparison written backwards, which is how the inverted version of this
    # function survived a mutation pass.
    hit = _result(1, match.TIER1, {"1215968847", "HOLLAND|HESTER|19700214"})
    assert evaluate._hit_the_planted_record(hit, "1215968847") is True
    assert evaluate._hit_the_planted_record(hit, "HOLLAND|HESTER|19700214") is True
    assert evaluate._hit_the_planted_record(hit, "1558922021") is False
    assert evaluate._hit_the_planted_record(_result(1, match.TIER1, set()), "1215968847") is False


def check_recall_counts_every_excluded_provider_and_not_only_the_reachable_ones():
    labels = {
        1: generate.EXACT_IDENTIFIER,
        2: generate.NAME_AND_BIRTH,
        3: generate.UNRELATED,
    }
    results = [_result(1, match.TIER1), _result(2, None), _result(3, None)]
    answer = evaluate.per_tier(results, labels, None, (match.TIER1,))[match.TIER1]
    assert answer["provider_graded"]["recall"] == 0.5, answer["provider_graded"]
    assert answer["provider_graded"]["false_negative"] == 1


def check_the_flagged_buckets_are_reported_beside_the_rate():
    labels = {1: generate.NEAR_MISS, 2: generate.NEAR_MISS, 3: generate.UNRELATED}
    results = [_result(1, match.TIER3), _result(2, match.TIER3), _result(3, None)]
    answer = evaluate.per_tier(results, labels, None, (match.TIER3,))[match.TIER3]
    assert answer["flagged_by_label"] == {generate.NEAR_MISS: 2}, answer["flagged_by_label"]
    assert answer["provider_graded"]["precision"] == 0.0


def check_the_cascade_names_an_excluded_provider_that_nothing_flagged():
    labels = {1: generate.NAME_AND_BIRTH, 2: generate.UNRELATED}
    results = [_result(1, None), _result(2, None)]
    casc = evaluate.per_tier(results, labels, None, ())["cascade"]
    assert casc["excluded_and_cleared"] == 1, casc
    assert casc["cleared_without_review"] == 2, casc
    assert casc["provider_graded"]["recall"] == 0.0


def check_the_review_grading_counts_the_near_misses_a_tier_held():
    labels = {1: generate.NEAR_MISS, 2: generate.NEAR_MISS, 3: generate.UNRELATED}
    results = [_result(1, match.TIER3), _result(2, None), _result(3, None)]
    answer = evaluate.held_for_review(results, labels)
    assert answer[generate.NEAR_MISS]["held_for_review"] == 1
    assert answer[generate.NEAR_MISS]["cleared_with_nobody_looking"] == 1
    assert answer[generate.NEAR_MISS]["held_share"] == 0.5
    assert answer[generate.UNRELATED]["held_for_review"] == 0


def check_the_queue_split_is_the_three_counts_and_not_only_their_total():
    # The sum cannot fail. The third field is defined as the total minus the
    # other two, so a check that only adds them up passes whatever the first
    # two say. Four mutations of this function survived on exactly that.
    labels = {
        1: generate.EXACT_IDENTIFIER,
        2: generate.EXACT_IDENTIFIER,
        3: generate.NEAR_MISS,
        4: generate.UNRELATED,
        5: generate.UNRELATED,
        6: generate.UNRELATED,
    }
    results = [
        _result(1, match.TIER1),
        _result(2, match.TIER1),
        _result(3, match.TIER3),
        _result(4, None),
        _result(5, None),
        _result(6, None),
    ]
    answer = evaluate.auto_clearable(results, labels)
    # Three different numbers, so swapping any two of them fails.
    assert answer["providers"] == 6, answer
    assert answer["decided_by_identifier"] == 2, answer
    assert answer["sent_to_review"] == 1, answer
    assert answer["cleared_with_no_match"] == 3, answer
    assert answer["labels_present"] == 6, answer


def check_a_provider_at_the_identifier_tier_is_not_counted_as_reviewed():
    labels = {1: generate.EXACT_IDENTIFIER}
    answer = evaluate.auto_clearable([_result(1, match.TIER1)], labels)
    assert answer["sent_to_review"] == 0, answer
    assert answer["decided_by_identifier"] == 1, answer


def check_the_cascade_counts_the_flagged_buckets_the_right_way_round():
    # A mixed flagged set, so the two comprehensions cannot be swapped. With
    # nothing flagged, or with every flagged provider in one bucket, the
    # inverted version of either one produces the same answer.
    labels = {
        1: generate.NAME_AND_BIRTH,
        2: generate.EXACT_IDENTIFIER,
        3: generate.NEAR_MISS,
        4: generate.UNRELATED,
    }
    results = [
        _result(1, match.TIER2),
        _result(2, match.TIER1),
        _result(3, match.TIER3),
        _result(4, None),
    ]
    casc = evaluate.per_tier(results, labels, None, ())["cascade"]
    assert casc["flagged"] == 3, casc
    assert casc["provider_graded"]["true_positive"] == 2, casc
    assert casc["provider_graded"]["false_positive"] == 1, casc
    assert abs(casc["provider_graded"]["precision"] - 2 / 3) < 1e-9, casc
    # One provider of the four reached no tier, so this is a count and not the
    # total minus the flagged written twice.
    assert casc["cleared_without_review"] == 1, casc
    assert casc["excluded_and_cleared"] == 0, casc


def check_the_cascade_clears_more_than_it_flags_when_most_providers_match_nothing():
    labels = {n: generate.UNRELATED for n in range(1, 6)}
    labels[1] = generate.NAME_AND_BIRTH
    results = [_result(1, match.TIER2)] + [_result(n, None) for n in range(2, 6)]
    casc = evaluate.per_tier(results, labels, None, ())["cascade"]
    assert casc["flagged"] == 1, casc
    assert casc["cleared_without_review"] == 4, casc
