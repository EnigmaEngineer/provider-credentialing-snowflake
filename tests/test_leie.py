"""Checks on the exclusion list reader and the profile it produces.

Everything here runs against tests/fixtures/leie_sample.csv, which is built by
make_fixture.py out of the real file with every date of birth replaced. The
provenance note beside it says what was changed and why.
"""

import csv
import os
import tempfile

from screening import leie, profile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "leie_sample.csv")

# Read off the real file by scripts/profile_registries.py. Pinned here so a
# change in the classifier that moves them has to be deliberate.
REAL_RECORDS = 84093
REAL_ABSENT = 75169
REAL_USABLE = 8924


def fixture_rows():
    return list(leie.read(FIXTURE, encoding="utf-8"))


def check_the_fixture_is_readable():
    rows = fixture_rows()
    assert len(rows) == 9, len(rows)


def check_a_header_that_is_not_the_expected_one_is_refused():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "wrong.csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["LASTNAME", "FIRSTNAME", "NPI"])
            w.writerow(["A", "B", "0"])
        try:
            list(leie.read(path, encoding="utf-8"))
        except ValueError as exc:
            assert "header" in str(exc), str(exc)
        else:
            raise AssertionError("a three column file was accepted")


def check_absence_is_the_character_zero_and_not_an_empty_string():
    # This is the whole reason the classifier exists. The real file populates
    # the column on every row and says nothing by writing zero into it.
    assert leie.classify_npi("0") == leie.ABSENT_NPI
    assert leie.classify_npi("") == leie.ABSENT_NPI
    assert leie.classify_npi(None) == leie.ABSENT_NPI
    assert leie.classify_npi("  0  ") == leie.ABSENT_NPI


# Real identifiers out of the exclusion list, pinned as literals. Asking the
# classifier which rows it calls usable and then checking their check digits is
# circular, because the check digit is why it called them usable. These three
# are chosen for what they do to the doubling step: the first has a digit that
# doubles to exactly ten, the second doubles past ten and never to ten, and the
# third has no digit that doubles past nine at all. Without the first, moving
# the boundary from nine to ten changes an answer and nothing notices.
VALID_IDENTIFIERS = ("1972902351", "1215968847", "1801231436")


def check_each_pinned_identifier_passes_its_check_digit():
    for npi in VALID_IDENTIFIERS:
        assert leie.npi_check_digit_ok(npi), npi
        assert leie.classify_npi(npi) == leie.USABLE_NPI, npi


def check_moving_one_digit_of_a_pinned_identifier_breaks_it():
    # The other side. Without this the function could return True for anything.
    for npi in VALID_IDENTIFIERS:
        for pos in range(10):
            moved = npi[:pos] + str((int(npi[pos]) + 1) % 10) + npi[pos + 1 :]
            if moved == npi:
                continue
            assert not leie.npi_check_digit_ok(moved), (npi, pos, moved)


def check_the_doubling_step_is_reached_by_the_pinned_identifiers():
    # Naming what each vector is for, so a later edit cannot quietly drop the
    # one that matters. The first has a digit doubling to exactly ten, which is
    # the only input that separates a boundary of nine from a boundary of ten.
    def doubles(npi):
        body = "80840" + npi[:9]
        return [int(c) * 2 for i, c in enumerate(reversed(body)) if i % 2 == 0]

    assert 10 in doubles(VALID_IDENTIFIERS[0]), doubles(VALID_IDENTIFIERS[0])
    assert max(doubles(VALID_IDENTIFIERS[1])) > 10, doubles(VALID_IDENTIFIERS[1])
    assert 10 not in doubles(VALID_IDENTIFIERS[1]), doubles(VALID_IDENTIFIERS[1])
    assert max(doubles(VALID_IDENTIFIERS[2])) <= 9, doubles(VALID_IDENTIFIERS[2])


def check_a_usable_npi_from_the_fixture_passes_its_check_digit():
    rows = fixture_rows()
    usable = [r["NPI"] for r in rows if leie.classify_npi(r["NPI"]) == leie.USABLE_NPI]
    assert usable, "the fixture carries no usable NPI"
    for npi in usable:
        assert leie.npi_check_digit_ok(npi), npi


def check_the_check_digit_refuses_a_value_one_digit_away():
    # Without this the function could return True for everything and the check
    # above would still pass.
    rows = fixture_rows()
    good = next(
        r["NPI"] for r in rows if leie.classify_npi(r["NPI"]) == leie.USABLE_NPI
    )
    moved = good[:9] + str((int(good[9]) + 1) % 10)
    assert moved != good
    assert not leie.npi_check_digit_ok(moved), moved
    assert leie.classify_npi(moved) == leie.MALFORMED_NPI


def check_the_check_digit_refuses_the_wrong_length_and_non_digits():
    assert not leie.npi_check_digit_ok("12345")
    assert not leie.npi_check_digit_ok("12345678901")
    assert not leie.npi_check_digit_ok("19729O2351")


def check_the_fixture_reaches_the_malformed_branch():
    # No record in the real file fails its check digit, so the only way this
    # branch is ever exercised is a constructed row.
    rows = fixture_rows()
    kinds = {leie.classify_npi(r["NPI"]) for r in rows}
    assert kinds == {leie.ABSENT_NPI, leie.USABLE_NPI, leie.MALFORMED_NPI}, kinds


def check_a_tier_two_key_is_none_when_any_part_is_missing():
    assert leie.tier2_key({"LASTNAME": "A", "FIRSTNAME": "B", "DOB": ""}) is None
    assert leie.tier2_key({"LASTNAME": "A", "FIRSTNAME": "B", "DOB": "0"}) is None
    assert leie.tier2_key({"LASTNAME": "", "FIRSTNAME": "B", "DOB": "19000101"}) is None
    assert leie.tier2_key({"LASTNAME": "A", "FIRSTNAME": "", "DOB": "19000101"}) is None
    assert leie.tier2_key({}) is None


def check_a_tier_two_key_upper_cases_both_names():
    k = leie.tier2_key({"LASTNAME": "smith", "FIRSTNAME": "jo", "DOB": "19000101"})
    assert k == ("SMITH", "JO", "19000101"), k


def check_a_business_record_is_not_an_individual():
    rows = fixture_rows()
    businesses = [r for r in rows if not leie.is_individual(r)]
    individuals = [r for r in rows if leie.is_individual(r)]
    assert businesses, "the fixture carries no business record"
    assert individuals, "the fixture carries no individual record"
    for r in businesses:
        assert (r["BUSNAME"] or "").strip(), r


# The exact answer for the committed fixture, every bucket. The sum checks
# below are invariant under moving a row from one bucket to another, and two of
# these buckets happen to hold the same count, so a rule that swapped them
# would leave every sum where it was.
FIXTURE_PROFILE = {
    "npi_column": {"records": 9, "absent": 5, "usable": 3, "malformed": 1},
    "reachable": {
        "records": 9,
        "tier1_exact_npi": 3,
        "tier2_name_and_dob": 3,
        # Two people and two different reasons neither can form a key. One has
        # no date of birth. The other's surname arrived as the serialised null.
        "name_and_state_only_individual": 2,
        "name_and_state_only_business": 1,
    },
    "tier2": {
        # Two quantities rather than one. Three records can form a key and
        # they land on two distinct keys, so the pair that collides is visible
        # in the difference between these two numbers and in nothing else.
        "distinct_keys": 2,
        "records_that_can_form_a_key": 3,
        "keys_held_by_more_than_one_record": 1,
        "records_on_a_shared_key": 2,
        "worst_key_record_count": 2,
    },
    "fanout": {
        "records_with_a_usable_npi": 3,
        "distinct_npis": 2,
        "npis_on_more_than_one_record": 1,
        "worst_npi_record_count": 2,
    },
}


def check_the_npi_profile_is_exactly_this_for_the_fixture():
    got = profile.exclusion_npi_profile(fixture_rows())
    assert got == FIXTURE_PROFILE["npi_column"], got


def check_the_reachability_is_exactly_this_for_the_fixture():
    got = profile.reachability(fixture_rows())
    assert got == FIXTURE_PROFILE["reachable"], got


def check_the_tier_two_collisions_are_exactly_this_for_the_fixture():
    got = profile.tier2_key_collisions(fixture_rows())
    assert got == FIXTURE_PROFILE["tier2"], got


def check_the_fan_out_is_exactly_this_for_the_fixture():
    got = profile.npi_fanout(fixture_rows())
    assert got == FIXTURE_PROFILE["fanout"], got


def check_the_overlap_helper_is_not_symmetric_in_its_denominators():
    # Two sides of different sizes, so swapping the arguments changes the
    # answer and a mutant that swaps them dies.
    got = profile.overlap({"a", "b", "c"}, {"b"})
    assert got["exclusion_npis"] == 3, got
    assert got["other_npis"] == 1, got
    assert got["in_both"] == 1, got


def check_an_empty_overlap_is_reported_as_zero_rather_than_omitted():
    got = profile.overlap({"a"}, {"z"})
    assert got == {"exclusion_npis": 1, "other_npis": 1, "in_both": 0}, got


def check_the_npi_profile_parts_add_up_to_the_record_count():
    rows = fixture_rows()
    got = profile.exclusion_npi_profile(rows)
    parts = got[leie.ABSENT_NPI] + got[leie.USABLE_NPI] + got.get(leie.MALFORMED_NPI, 0)
    assert parts == got["records"], got


def check_the_reachability_parts_add_up_and_are_not_all_equal():
    rows = fixture_rows()
    got = profile.reachability(rows)
    parts = (
        got.get("tier1_exact_npi", 0)
        + got.get("tier2_name_and_dob", 0)
        + got.get("name_and_state_only_individual", 0)
        + got.get("name_and_state_only_business", 0)
    )
    assert parts == got["records"], got
    # Lopsided on purpose. With one row per answer an inverted rule leaves
    # every count where it was and the check above still passes.
    counts = [
        got.get("tier1_exact_npi", 0),
        got.get("tier2_name_and_dob", 0),
        got.get("name_and_state_only_individual", 0),
        got.get("name_and_state_only_business", 0),
    ]
    assert len(set(counts)) > 1, counts


def check_the_fan_out_on_npi_is_counted_rather_than_assumed():
    rows = fixture_rows()
    got = profile.npi_fanout(rows)
    assert got["records_with_a_usable_npi"] > got["distinct_npis"], got
    assert got["npis_on_more_than_one_record"] >= 1, got
    assert got["worst_npi_record_count"] >= 2, got


def check_a_shared_tier_two_key_is_reported():
    rows = fixture_rows()
    got = profile.tier2_key_collisions(rows)
    assert got["keys_held_by_more_than_one_record"] >= 1, got
    assert got["records_on_a_shared_key"] >= 2, got
    assert got["distinct_keys"] < got["records_that_can_form_a_key"], got
    assert got["records_that_can_form_a_key"] < len(rows), got


def check_the_overlap_helper_carries_both_denominators():
    got = profile.overlap({"a", "b", "c"}, {"b", "z"})
    assert got == {"exclusion_npis": 3, "other_npis": 2, "in_both": 1}, got


def check_the_pinned_real_file_counts_still_add_up():
    # These three are the figures the README publishes. They are pinned as a
    # statement about the real file and the sum is the only thing checkable
    # without the download.
    assert REAL_ABSENT + REAL_USABLE == REAL_RECORDS
    assert REAL_ABSENT > REAL_USABLE * 8


def check_the_profile_functions_report_zero_rather_than_one_on_no_rows():
    # The fallback arm of each maximum. Handed nothing, the right answer is
    # zero, and nothing else in the suite reaches that branch.
    assert profile.exclusion_npi_profile([]) == {}
    assert profile.reachability([]) == {}
    assert profile.tier2_key_collisions([]) == {
        "distinct_keys": 0,
        "records_that_can_form_a_key": 0,
        "keys_held_by_more_than_one_record": 0,
        "records_on_a_shared_key": 0,
        "worst_key_record_count": 0,
    }
    assert profile.npi_fanout([]) == {
        "records_with_a_usable_npi": 0,
        "distinct_npis": 0,
        "npis_on_more_than_one_record": 0,
        "worst_npi_record_count": 0,
    }


def check_whether_a_record_is_about_a_person_is_decided_by_both_name_columns():
    # Written against dicts rather than fixture rows, because the cases that
    # separate the two clauses do not occur in the real file and a fixture row
    # for each would be two constructed rows carrying nothing else.
    #
    # The fixture masks both clauses. Every record in it that has a surname
    # also has a given name, so a rule reading either column alone agrees with
    # the right answer on all nine rows. A mutation pass found that and this is
    # the answer to it.
    cases = (
        # surname, given name, is this about a person
        ("AAKER", "DEBHANNA", True),
        ("AAKER", "", True),
        ("", "DEBHANNA", True),
        ("", "", False),
        # The serialised null is not a surname. With a given name beside it the
        # record is still about a person, and without one there is no name at
        # all.
        (leie.ABSENT_NAME, "ANGELA", True),
        (leie.ABSENT_NAME, "", False),
        (leie.ABSENT_NAME.lower(), "", False),
        # A surname that merely contains the word is a surname.
        ("NULLINGTON", "", True),
    )
    wrong = []
    for last, first, expected in cases:
        row = {"LASTNAME": last, "FIRSTNAME": first, "BUSNAME": "SOME CLINIC INC"}
        got = leie.is_individual(row)
        if got is not expected:
            wrong.append((last, first, got, expected))
    assert not wrong, wrong


def check_a_serialised_null_surname_forms_no_fallback_key():
    # The key is what clears a provider without a person looking, so a key
    # built on the word would clear everyone whose surname arrived the same way.
    row = {"LASTNAME": leie.ABSENT_NAME, "FIRSTNAME": "ANGELA", "DOB": "19710329"}
    assert leie.tier2_key(row) is None, leie.tier2_key(row)
    row["LASTNAME"] = "AAKER"
    assert leie.tier2_key(row) == ("AAKER", "ANGELA", "19710329"), leie.tier2_key(row)


def check_the_doubling_boundary_in_the_check_digit_cannot_be_reached():
    # A mutation pass moves this boundary and the suite stays green. That is an
    # equivalent mutant rather than a gap, and the reason is arithmetic: the
    # value tested has just been doubled, so it is always even and the boundary
    # sits on an odd number nothing can produce.
    #
    # Proved here rather than argued in a comment, because the next person to
    # see that survivor will otherwise go looking for a missing check.
    doubled = {2 * digit for digit in range(10)}
    assert 9 not in doubled, sorted(doubled)
    assert max(doubled) == 18 and min(doubled) == 0, sorted(doubled)
