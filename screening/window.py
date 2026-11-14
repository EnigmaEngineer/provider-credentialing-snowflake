"""Whether the screening on a provider's file still stands.

The rule lives here as well as in the warehouse, and the reason is the same one
that put the match tiers in both places. The warehouse SQL has never compiled
against the account this platform is written for, so a rule stated only there
is a rule nothing has evaluated. This one runs.

Three things retire a screening and only the first is the calendar.

The window. The exclusion list is republished monthly, so a screening older
than one cycle was taken against a file that has been replaced.

The file. A cycle re-run against an old download produces screenings dated
today against a digest that is no longer current. The date looks fine.

The attributes. A surname or a date of birth that moved after the screening
leaves an answer about somebody the source no longer describes. This is the one
that needs attribute history to see at all, because the credentialing
application overwrites the row in place.

Nothing here reads the clock. The cycle date comes out of the screening log, so
the same inputs give the same answer on any day, which is what lets a check
over it mean something.
"""

import datetime
from dataclasses import dataclass

# The exclusion list is republished monthly. One cycle is the longest a
# screening can be current for.
DEFAULT_WINDOW_DAYS = 30


@dataclass(frozen=True)
class Event:
    """One screening that was taken."""

    provider_id: int
    screened_on: datetime.date
    exclusion_file_sha256: str
    outcome: str = "cleared"


@dataclass(frozen=True)
class Verdict:
    provider_id: int
    last_screened_on: datetime.date
    days_since_screening: int
    outside_window: bool
    against_a_replaced_file: bool
    attributes_moved: bool

    @property
    def is_void(self):
        return self.outside_window or self.against_a_replaced_file or self.attributes_moved


def days_since(screened_on, as_of):
    """Whole days from the screening to the cycle date."""
    return (as_of - screened_on).days


def outside_window(screened_on, as_of, window_days=DEFAULT_WINDOW_DAYS):
    """True when the screening is older than one cycle, or there is none.

    The absent case is first and it is the one a rule written as arithmetic
    gets wrong. Subtracting from nothing gives nothing, and nothing is not
    greater than thirty, so a provider nobody has ever screened passes a check
    that only knows how to compare days.
    """
    if screened_on is None:
        return True
    return days_since(screened_on, as_of) > window_days


def against_a_replaced_file(event_sha256, current_sha256):
    if event_sha256 is None or current_sha256 is None:
        return False
    return event_sha256.strip().lower() != current_sha256.strip().lower()


def attributes_moved(last_change_on, screened_on):
    """True when an attribute version closed on or after the screening date.

    Not a strict comparison. A screening is dated to the day and a version
    boundary carries a time, so a change on the day of a screening cannot be
    ordered against it. A platform whose job is to not clear the wrong person
    reads an unordered pair as a change after.
    """
    if screened_on is None or last_change_on is None:
        return False
    return last_change_on >= screened_on


def current_cycle(events):
    """The cycle date and the file digest that cycle used.

    Returns the date, the digest and how many distinct digests appeared on that
    date. The third number is not decoration. Two digests on one cycle date
    means two files were in use at once, and then there is no such thing as the
    current one and every verdict below rests on whichever string sorted first.
    """
    if not events:
        return None, None, 0
    as_of = max(e.screened_on for e in events)
    digests = sorted({e.exclusion_file_sha256.strip().lower() for e in events if e.screened_on == as_of})
    return as_of, digests[0], len(digests)


def latest_per_provider(events):
    """The most recent screening for each provider."""
    latest = {}
    for event in events:
        held = latest.get(event.provider_id)
        if held is None or event.screened_on > held.screened_on:
            latest[event.provider_id] = event
    return latest


def verdicts(events, provider_ids, attribute_changes=None, window_days=DEFAULT_WINDOW_DAYS):
    """A verdict per provider id, including the providers with no screening.

    provider_ids is passed in rather than taken from the events, because a
    provider nobody has screened has no event to be found by and is exactly the
    provider this is being asked about.
    """
    as_of, current_sha256, _digests = current_cycle(events)
    latest = latest_per_provider(events)
    changes = attribute_changes or {}
    out = []
    for provider_id in sorted(provider_ids):
        event = latest.get(provider_id)
        screened_on = event.screened_on if event else None
        out.append(
            Verdict(
                provider_id=provider_id,
                last_screened_on=screened_on,
                days_since_screening=None if screened_on is None else days_since(screened_on, as_of),
                outside_window=outside_window(screened_on, as_of, window_days),
                against_a_replaced_file=(
                    False
                    if event is None
                    else against_a_replaced_file(event.exclusion_file_sha256, current_sha256)
                ),
                attributes_moved=attributes_moved(changes.get(provider_id), screened_on),
            )
        )
    return out


def due_for_screening(events, active_provider_ids, attribute_changes=None,
                      window_days=DEFAULT_WINDOW_DAYS):
    """The active providers a cycle has to screen again."""
    return [
        v
        for v in verdicts(events, active_provider_ids, attribute_changes, window_days)
        if v.is_void
    ]
