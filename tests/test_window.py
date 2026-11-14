"""The screening currency rule, in both directions.

The three dbt tests over this rule all return nothing on a healthy fixture,
which is also what they return when the rule cannot fire at all. These are the
checks that make it fire.
"""

import csv
import datetime
import json
import os
import re

from screening import window

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SEED = os.path.join(ROOT, "transform", "seeds", "raw_screening_screening_event.csv")
PROJECT = os.path.join(ROOT, "transform", "dbt_project.yml")
MATCHING = os.path.join(ROOT, "measurements", "matching.json")

AS_OF = datetime.date(2026, 11, 1)
CURRENT = "a" * 64
REPLACED = "b" * 64


def event(provider_id, screened_on, sha256=CURRENT):
    return window.Event(provider_id, screened_on, sha256)


def seed_rows():
    with open(SEED, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def check_a_screening_on_the_cycle_date_is_inside_the_window():
    assert window.outside_window(AS_OF, AS_OF, 30) is False


def check_a_screening_exactly_one_window_old_is_still_inside():
    # The boundary belongs to the screening. Thirty days is one cycle and a
    # cycle is what a screening is good for.
    assert window.outside_window(AS_OF - datetime.timedelta(days=30), AS_OF, 30) is False


def check_a_screening_one_day_past_the_window_is_outside():
    assert window.outside_window(AS_OF - datetime.timedelta(days=31), AS_OF, 30) is True


def check_a_provider_nobody_has_screened_is_outside_the_window():
    # The case arithmetic alone gets wrong.
    assert window.outside_window(None, AS_OF, 30) is True


def check_the_window_length_is_not_hard_coded_in_two_places():
    # The rule is stated in SQL and again in Python. They agree because this
    # fails when they stop agreeing, not because somebody remembered.
    text = open(PROJECT, encoding="utf-8").read()
    found = re.search(r"^\s*screening_window_days:\s*([0-9]+)\s*$", text, re.M)
    assert found, "the dbt project states no window length"
    assert int(found.group(1)) == window.DEFAULT_WINDOW_DAYS, (
        found.group(1),
        window.DEFAULT_WINDOW_DAYS,
    )


def check_a_screening_against_a_replaced_file_is_refused_on_the_cycle_date():
    # Dated today and worthless. The window cannot see this one.
    events = [event(1, AS_OF, REPLACED), event(2, AS_OF, CURRENT)]
    answers = {v.provider_id: v for v in window.verdicts(events, [1, 2])}
    assert answers[1].outside_window is False
    assert answers[1].against_a_replaced_file is True
    assert answers[1].is_void is True
    assert answers[2].is_void is False


def check_the_current_digest_is_the_one_the_latest_cycle_used():
    # An older cycle holding a different digest does not make the current one
    # ambiguous, and an older digest is not the current one just because more
    # screenings carry it.
    events = [
        event(1, AS_OF - datetime.timedelta(days=90), REPLACED),
        event(2, AS_OF - datetime.timedelta(days=90), REPLACED),
        event(3, AS_OF, CURRENT),
    ]
    as_of, current, digests = window.current_cycle(events)
    assert as_of == AS_OF
    assert current == CURRENT
    assert digests == 1


def check_two_digests_on_one_cycle_date_are_reported_rather_than_resolved():
    events = [event(1, AS_OF, CURRENT), event(2, AS_OF, REPLACED)]
    _as_of, _current, digests = window.current_cycle(events)
    assert digests == 2


def check_an_attribute_change_after_the_screening_voids_it():
    events = [event(1, AS_OF)]
    changes = {1: AS_OF + datetime.timedelta(days=1)}
    verdict = window.verdicts(events, [1], changes)[0]
    assert verdict.outside_window is False
    assert verdict.against_a_replaced_file is False
    assert verdict.attributes_moved is True
    assert verdict.is_void is True


def check_an_attribute_change_before_the_screening_leaves_it_standing():
    events = [event(1, AS_OF)]
    changes = {1: AS_OF - datetime.timedelta(days=1)}
    assert window.verdicts(events, [1], changes)[0].is_void is False


def check_a_change_on_the_day_of_the_screening_counts_as_after_it():
    # The unordered pair, resolved toward not clearing somebody.
    events = [event(1, AS_OF)]
    assert window.verdicts(events, [1], {1: AS_OF})[0].attributes_moved is True


def check_the_latest_screening_wins_and_not_the_last_row_read():
    events = [event(1, AS_OF), event(1, AS_OF - datetime.timedelta(days=120))]
    assert window.latest_per_provider(events)[1].screened_on == AS_OF
    backwards = list(reversed(events))
    assert window.latest_per_provider(backwards)[1].screened_on == AS_OF


def check_the_active_set_decides_who_is_due_and_not_the_screening_log():
    # Provider 9 is the stale one in the seed fixture and is not active. A rule
    # that reads the log rather than the workflow returns them.
    events = [event(9, AS_OF - datetime.timedelta(days=120), REPLACED), event(1, AS_OF)]
    due = window.due_for_screening(events, [1])
    assert due == [], due
    assert [v.provider_id for v in window.due_for_screening(events, [1, 9])] == [9]


def check_the_seed_names_the_exclusion_file_the_matching_measurement_used():
    # A fixture claiming a screening against a file nobody has is a fixture
    # that proves nothing. The current digest in the seed is the digest of the
    # published list, read out of the manifest rather than typed here.
    with open(MATCHING, encoding="utf-8") as fh:
        published = json.load(fh)["exclusion_sha256"]
    digests = {row["exclusion_file_sha256"] for row in seed_rows()}
    assert published in digests, published
    older = digests - {published}
    assert older, "the seed carries one digest, so nothing in it can be superseded"


def check_the_seed_carries_a_screening_outside_the_window():
    rows = seed_rows()
    dates = [datetime.date.fromisoformat(row["screened_on"]) for row in rows]
    as_of = max(dates)
    stale = [d for d in dates if (as_of - d).days > window.DEFAULT_WINDOW_DAYS]
    assert stale, "every screening in the seed is current, so the window rule grades nothing"
