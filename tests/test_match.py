"""The tiers, and what each one refuses.

Every tier here gets a case it matches and a case it refuses. A predicate
tested only where it says yes is a predicate nothing graded.
"""

from screening import leie, match


def _exclusion(**kwargs):
    row = {name: "" for name in leie.COLUMNS}
    row.update(kwargs)
    return row


def _provider(pid=1, npi=None, last="HOLLAND", first="HESTER", dob="1970-02-14"):
    return {
        "provider_id": pid,
        "npi": npi,
        "last_name": last,
        "first_name": first,
        "date_of_birth": dob,
    }


PERSON = _exclusion(LASTNAME="HOLLAND", FIRSTNAME="HESTER", DOB="19700214", STATE="TX", NPI="0")
BUSINESS = _exclusion(BUSNAME="AMERICAN THERAPEUTIC CORP", NPI="1215968847", STATE="FL")
SENTINEL_NAME = _exclusion(LASTNAME="NULL", FIRSTNAME="ANGELA", DOB="19000101", STATE="NC", NPI="0")


def check_the_index_holds_one_entry_per_record_and_not_per_key():
    twice = [PERSON, dict(PERSON)]
    index = match.Index(twice)
    key = ("HOLLAND", "HESTER", "19700214")
    assert index.by_name_and_dob[key] == [0, 1], index.by_name_and_dob[key]
    assert index.record_count == 2


def check_a_business_record_forms_no_name_key():
    index = match.Index([BUSINESS])
    assert index.by_name_and_dob == {}, index.by_name_and_dob
    assert index.by_name_and_state == {}, index.by_name_and_state
    assert list(index.by_identifier) == ["1215968847"]


def check_the_serialised_null_surname_forms_no_name_key():
    index = match.Index([SENTINEL_NAME])
    assert index.by_name_and_dob == {}, index.by_name_and_dob
    assert index.by_name_and_state == {}, index.by_name_and_state


def check_a_record_with_no_state_is_not_reachable_by_the_state_tier():
    no_state = _exclusion(LASTNAME="HOLLAND", FIRSTNAME="HESTER", DOB="19700214", NPI="0")
    index = match.Index([no_state])
    assert index.by_name_and_state == {}, index.by_name_and_state
    assert ("HOLLAND", "HESTER", "19700214") in index.by_name_and_dob


def check_the_three_spellings_of_an_absent_identifier_answer_the_same():
    for value in (None, "", "   ", "0"):
        assert match.provider_identifier(_provider(npi=value)) is None, value
    assert match.provider_identifier(_provider(npi="  1215968847 ")) == "1215968847"


def check_a_date_that_is_not_eight_digits_forms_no_key():
    for dob in (None, "", "1970", "70-02-14", "1970-02-1x"):
        assert match.provider_name_and_dob(_provider(dob=dob)) is None, dob
    assert match.provider_name_and_dob(_provider()) == ("HOLLAND", "HESTER", "19700214")


def check_a_blank_state_forms_no_name_and_state_key():
    assert match.provider_name_and_state(_provider(), "") is None
    assert match.provider_name_and_state(_provider(), None) is None
    assert match.provider_name_and_state(_provider(), " tx ") == ("HOLLAND", "HESTER", "TX")


def check_the_identifier_tier_wins_when_two_tiers_reach_one_provider():
    both = _exclusion(
        LASTNAME="HOLLAND", FIRSTNAME="HESTER", DOB="19700214", STATE="TX", NPI="1215968847"
    )
    index = match.Index([both])
    tier, hits = match.match_provider(_provider(npi="1215968847"), index, "TX")
    assert tier == match.TIER1, tier
    assert hits == (0,)


def check_the_name_tier_wins_over_the_state_tier_when_the_dates_agree():
    index = match.Index([PERSON])
    tier, _hits = match.match_provider(_provider(), index, "TX")
    assert tier == match.TIER2, tier


def check_a_near_miss_reaches_the_state_tier_and_not_the_name_tier():
    index = match.Index([PERSON])
    tier, hits = match.match_provider(_provider(dob="1972-02-14"), index, "TX")
    assert tier == match.TIER3, tier
    assert hits == (0,)


def check_a_near_miss_in_another_state_reaches_no_tier():
    index = match.Index([PERSON])
    tier, hits = match.match_provider(_provider(dob="1972-02-14"), index, "NC")
    assert tier is None, tier
    assert hits == ()


def check_a_provider_with_no_identifier_is_not_counted_as_a_tier_one_miss():
    index = match.Index([BUSINESS])
    tier, _hits = match.match_provider(_provider(npi="0"), index, "FL")
    assert tier is None, tier


def check_match_all_keeps_the_order_it_was_given():
    index = match.Index([PERSON])
    # The middle one shares no surname with the record, so no tier reaches it.
    providers = [_provider(pid=3), _provider(pid=1, last="GRANTLEY"), _provider(pid=2)]
    results = match.match_all(providers, index, {3: "TX", 1: "TX", 2: "TX"})
    assert [r["provider_id"] for r in results] == [3, 1, 2]
    assert [r["tier"] for r in results] == [match.TIER2, None, match.TIER2]


def check_match_all_passes_each_provider_its_own_state():
    # The state tier is the only consumer of that mapping, so a version of
    # match_all that discards it still answers correctly for every provider the
    # two stronger tiers reach. One provider here is reachable only by state
    # and the other is reachable by nothing.
    index = match.Index([PERSON])
    providers = [_provider(pid=1, dob="1972-02-14"), _provider(pid=2, dob="1972-02-14")]
    results = match.match_all(providers, index, {1: "TX", 2: "NC"})
    assert [r["tier"] for r in results] == [match.TIER3, None], results


def check_a_provider_with_no_state_still_reaches_the_stronger_tiers():
    index = match.Index([PERSON])
    results = match.match_all([_provider()], index, states={})
    assert results[0]["tier"] == match.TIER2, results


def check_record_identities_carry_both_the_identifier_and_the_key():
    both = _exclusion(
        LASTNAME="HOLLAND", FIRSTNAME="HESTER", DOB="19700214", STATE="TX", NPI="1215968847"
    )
    rows = [both, BUSINESS]
    assert match.record_identities(rows, (0,)) == frozenset(
        {"1215968847", "HOLLAND|HESTER|19700214"}
    )
    assert match.record_identities(rows, (1,)) == frozenset({"1215968847"})
    assert match.record_identities(rows, ()) == frozenset()


def check_the_tier_order_is_strongest_first():
    assert match.TIER_ORDER == (match.TIER1, match.TIER2, match.TIER3)
