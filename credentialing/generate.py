"""Generating the credentialing workflow, with the overlaps recorded as labels.

No public set of credentialing applications exists, so the workflow side of
this platform is generated. A generator that only produced plausible rows would
be useless here, because the thing the platform has to be measured on is
whether it finds the providers who are on the exclusion list and leaves the
rest alone. So the generator plants overlaps against the real registry and
writes down what it planted.

Four kinds of provider, and the names describe what the matcher should do with
them rather than how they were built:

    exact_identifier    the identifier is one that appears on an exclusion
                        record. This is the only kind that may be cleared
                        without a person looking at it.
    name_and_birth      no usable identifier, and the name and date of birth
                        are those of an exclusion record.
    near_miss           the name is an exclusion record's name and the date of
                        birth is not. This one has to reach a person. It is the
                        bucket that decides whether a tier is worth running,
                        because a tier that cannot separate these from
                        name_and_birth is a tier that clears the wrong people.
    unrelated           appears nowhere in the exclusion list.

The labels are returned beside the rows and never stored in the database. A
credentialing application does not know which of its providers are excluded.
That is the question the warehouse is being built to answer, and a label column
in the source would answer it for free and measure nothing.

Deterministic for a given seed and a given exclusion file. Nothing here reads
the clock.
"""

import datetime
import random

from screening import leie

EXACT_IDENTIFIER = "exact_identifier"
NAME_AND_BIRTH = "name_and_birth"
NEAR_MISS = "near_miss"
UNRELATED = "unrelated"

# The workflow statuses an application moves through. Terminal and non terminal
# are separated because a screening window only applies to a provider who is
# currently active, which is what a later check has to be able to ask.
ACTIVE_STATUSES = ("submitted", "in_verification", "committee_review")
TERMINAL_STATUSES = ("approved", "denied", "withdrawn")

VERIFICATION_SOURCES = (
    "oig_leie",
    "npdb",
    "state_board",
    "nppes",
    "sanctions_monitoring",
)

SPECIALTIES = (
    "FAMILY MEDICINE",
    "INTERNAL MEDICINE",
    "NURSE PRACTITIONER",
    "PHYSICAL THERAPY",
    "PSYCHIATRY",
    "RADIOLOGY",
)

FACILITIES = (
    (1, "RIVER BEND MEDICAL CENTER", "NC"),
    (2, "LAKESHORE SURGICAL HOSPITAL", "AZ"),
    (3, "PINE HOLLOW CLINIC NETWORK", "FL"),
    (4, "WESTGATE BEHAVIORAL HEALTH", "NY"),
)

# Surname and given name pools for the providers that must not match anything.
# Short on purpose. A long pool hides a collision with the exclusion list
# behind its own variety, and the generator checks for that collision rather
# than assuming the pool is clean.
SURNAMES = (
    "ANSELL", "BRIDGEFORD", "CALLOWAY", "DUNMORE", "ELSWORTH", "FAIRBROOK",
    "GRANTLEY", "HOLLAND", "IVERSON", "JARDINE", "KESTREL", "LOWDEN",
    "MARCHANT", "NEWBURY", "OAKSHOTT", "PENHALE", "QUILLEN", "REDMAYNE",
)
GIVEN_NAMES = (
    "ADRIAN", "BEATRIX", "CORMAC", "DELPHINE", "EAMON", "FENELLA",
    "GARETH", "HESTER", "IVO", "JOCELYN", "KENDRICK", "LUCINDA",
)

EPOCH = datetime.date(2026, 1, 1)


class Plan:
    """How many of each kind of provider to plant.

    Held as an object rather than passed as four integers because the totals
    get written to a manifest and read back by the checks, and a positional
    tuple of four counts is the shape that gets reordered by accident.
    """

    def __init__(self, exact_identifier=40, name_and_birth=60, near_miss=50, unrelated=350):
        self.exact_identifier = exact_identifier
        self.name_and_birth = name_and_birth
        self.near_miss = near_miss
        self.unrelated = unrelated

    def total(self):
        return self.exact_identifier + self.name_and_birth + self.near_miss + self.unrelated

    def as_dict(self):
        return {
            EXACT_IDENTIFIER: self.exact_identifier,
            NAME_AND_BIRTH: self.name_and_birth,
            NEAR_MISS: self.near_miss,
            UNRELATED: self.unrelated,
        }


def excluded_surnames(rows):
    """Every surname anywhere in the exclusion list.

    Separate from the planting pools and that separation is the point. The
    pools hold only the records a tier can reach, so a surname belonging to
    somebody reachable by name and state alone is in neither of them. Building
    the avoid list out of the pools leaves those surnames available to a
    provider labelled as appearing nowhere in the list, and a name tier would
    then flag that provider correctly while the answer key calls it a false
    positive.
    """
    out = set()
    for row in rows:
        surname = (row.get("LASTNAME") or "").strip().upper()
        if surname:
            out.add(surname)
    return out


def exclusion_pools(rows):
    """Split the exclusion list into the two pools the planting draws from.

    Both pools hold distinct values rather than one entry per record, and that
    is the whole point of this function rather than a tidy up. One identifier
    sits on more than one exclusion record and so does one fallback key.
    Sampling from a list of records would draw the same identifier twice, two
    planted providers would claim the same exclusion record, and the recall
    denominator would count it once while two providers expected to find it.

    Only the identifier and the key come back. The surname used to ride along
    with the identifier and the avoid list is built from every row now, so
    nothing read it. A value nothing reads is a value a mutation pass cannot
    reach, which is how it was found.

    Sorted so a given exclusion file always yields the same pools whatever
    order it was read in.
    """
    with_identifier = set()
    with_key = set()
    for row in rows:
        if leie.classify_npi(row.get("NPI")) == leie.USABLE_NPI:
            with_identifier.add(row["NPI"].strip())
        key = leie.tier2_key(row)
        if key is not None:
            with_key.add(key)
    return sorted(with_identifier), sorted(with_key)


def key_states(rows):
    """The state each fallback key's records sit in, and how many disagree.

    The planting needs this because the provider table carries no state. The
    state is on the licence, and until today the generator drew it from the
    four facilities, so a provider planted against an exclusion record in
    California was given a licence in New York. A tier reading name and state
    then missed it, and the number that came back was a property of the
    facility draw rather than of the tier.

    A key can sit on records in more than one state. The lowest state code is
    taken so a given file always plants the same one, and the count of keys
    that disagree is returned beside it, because a planted provider on such a
    key can be matched to a record in a state it was not planted with.
    """
    seen = {}
    for row in rows:
        key = leie.tier2_key(row)
        if key is None:
            continue
        state = (row.get("STATE") or "").strip().upper()
        if not state:
            continue
        seen.setdefault(key, set()).add(state)
    chosen = {key: min(states) for key, states in seen.items()}
    spread = sum(1 for states in seen.values() if len(states) > 1)
    return chosen, spread


def _shift_birth(dob, days):
    """Move a date of birth far enough that no sane comparison calls it equal.

    The exclusion file writes a date of birth as eight digits. A value that
    cannot be parsed is returned unchanged, because a near miss built on a
    value this function did not understand is not a near miss.
    """
    try:
        parsed = datetime.datetime.strptime(dob, "%Y%m%d").date()
    except ValueError:
        return None
    return (parsed + datetime.timedelta(days=days)).strftime("%Y%m%d")


def _as_date(eight_digits):
    if not eight_digits:
        return None
    try:
        return datetime.datetime.strptime(eight_digits, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def generate(exclusion_rows, plan=None, seed=20261110, plant_state=True):
    """Build the whole workflow. Returns the tables and the labels.

    The return value is a dict of table name to list of row dicts, plus a
    labels list of provider identifier and label. Nothing is written here. The
    caller decides whether that goes into Postgres or into a file, which is
    what lets the same rows be loaded into a real database and compared against
    a committed copy.
    """
    plan = plan or Plan()
    rng = random.Random(seed)
    # The control arm. With the state unplanted a planted provider keeps the
    # licence state the facility draw gave it, which is what this generator did
    # until 2026-11-12. It is kept rather than deleted so the name and state
    # tier can be measured against a sample where nothing planted the field it
    # reads. A tier that scores the same under both arms is a tier reading
    # something other than the state.
    if not plant_state:
        seed_note = "state not planted"
    else:
        seed_note = "state planted from the exclusion record"
    # Read once into a list, because the rows are walked twice and the readers
    # in this repository yield rather than return. A generator handed here
    # would be empty on the second walk, the avoid list would come back empty,
    # and the only sign of it would be a planted provider sharing a surname
    # with the list it is labelled as being absent from.
    exclusion_rows = list(exclusion_rows)
    with_identifier, with_key = exclusion_pools(exclusion_rows)

    if len(with_identifier) < plan.exact_identifier:
        raise ValueError(
            "exclusion file carries %d usable identifiers and the plan wants %d"
            % (len(with_identifier), plan.exact_identifier)
        )
    if len(with_key) < plan.name_and_birth + plan.near_miss:
        raise ValueError(
            "exclusion file carries %d tier two keys and the plan wants %d"
            % (len(with_key), plan.name_and_birth + plan.near_miss)
        )

    providers = []
    labels = []
    # The state the planting gave a provider, keyed by provider identifier. The
    # licence loop below reads it.
    planted_state = {}
    next_id = 1

    # Drawn without replacement. Two planted providers sharing one exclusion
    # record would make the recall denominator wrong, because the record is
    # found once and two providers claim it.
    key_state, keys_spanning_states = key_states(exclusion_rows)
    picked_identifiers = rng.sample(with_identifier, plan.exact_identifier)
    picked_keys = rng.sample(with_key, plan.name_and_birth + plan.near_miss)
    match_keys = picked_keys[: plan.name_and_birth]
    miss_keys = picked_keys[plan.name_and_birth :]

    def add(npi, last, first, dob, label, planted_against="", state=None,
            provider_type="individual", business=None):
        nonlocal next_id
        created = EPOCH + datetime.timedelta(days=rng.randrange(0, 300))
        providers.append(
            {
                "provider_id": next_id,
                "npi": npi,
                "last_name": last,
                "first_name": first,
                "middle_name": None,
                "business_name": business,
                "date_of_birth": dob,
                "provider_type": provider_type,
                "primary_specialty": rng.choice(SPECIALTIES),
                "created_at": created.isoformat() + "T09:00:00+00:00",
                "updated_at": created.isoformat() + "T09:00:00+00:00",
            }
        )
        # The planted record travels with the label. Without it a precision
        # figure can only ask whether the right provider was flagged, and a
        # tier that flags the right provider against the wrong record scores
        # as correct. The value is the identifier or the pipe joined fallback
        # key the row was built from, and it is empty for a provider that was
        # planted against nothing.
        labels.append(
            {
                "provider_id": next_id,
                "label": label,
                "planted_against": planted_against,
            }
        )
        if state is not None and plant_state:
            planted_state[next_id] = state
        next_id += 1

    # The identifier is the exclusion record's. The name is not, which is the
    # realistic case: the registry and the application disagree on spelling and
    # the identifier is the only thing they agree on.
    #
    # No state is planted here. The identifier tier is the only route to this
    # provider and it reads no state, so a state taken from the exclusion
    # record would change no answer anywhere. A function that produced one was
    # written and then removed for that reason.
    for npi in picked_identifiers:
        add(
            npi,
            rng.choice(SURNAMES),
            rng.choice(GIVEN_NAMES),
            _as_date("19%02d%02d%02d" % (rng.randrange(50, 90), rng.randrange(1, 13), rng.randrange(1, 29))),
            EXACT_IDENTIFIER,
            planted_against=npi,
        )

    # Name and date of birth copied whole, and no identifier at all. This is
    # the provider the fallback tier exists for.
    for last, first, dob in match_keys:
        add(
            None,
            last,
            first,
            _as_date(dob),
            NAME_AND_BIRTH,
            planted_against="|".join((last, first, dob)),
            state=key_state.get((last, first, dob)),
        )

    # Same name, a date of birth two years and a day away. Anything that calls
    # this a match on a date comparison is matching on the name alone.
    for last, first, dob in miss_keys:
        shifted = _shift_birth(dob, 731)
        if shifted is None:
            raise ValueError("cannot build a near miss from date of birth %r" % dob)
        # Planted against nothing on purpose. This provider is not the excluded
        # person, so there is no pair for a match to be right about, and any
        # tier reaching them has made a mistake even where a review is the
        # right handling. The state is the exclusion record's, because a tier
        # that cannot be reached cannot be measured.
        add(
            None,
            last,
            first,
            _as_date(shifted),
            NEAR_MISS,
            state=key_state.get((last, first, dob)),
        )

    # The providers that must not match. Their surnames are checked against
    # every surname in the exclusion list rather than against the two planting
    # pools, which hold only the records a tier can reach.
    listed = excluded_surnames(exclusion_rows)
    unrelated_surnames = [s for s in SURNAMES if s not in listed]
    if not unrelated_surnames:
        raise ValueError("every surname in the pool appears in the exclusion list")
    for _ in range(plan.unrelated):
        add(
            None,
            rng.choice(unrelated_surnames),
            rng.choice(GIVEN_NAMES),
            _as_date("19%02d%02d%02d" % (rng.randrange(50, 90), rng.randrange(1, 13), rng.randrange(1, 29))),
            UNRELATED,
        )

    facilities = [{"facility_id": f, "name": n, "state": s} for f, n, s in FACILITIES]
    applications = []
    licenses = []
    verifications = []
    decisions = []

    for provider in providers:
        pid = provider["provider_id"]
        submitted = EPOCH + datetime.timedelta(days=rng.randrange(0, 300))
        active = rng.random() < 0.4
        status = rng.choice(ACTIVE_STATUSES if active else TERMINAL_STATUSES)
        app_id = pid
        applications.append(
            {
                "application_id": app_id,
                "provider_id": pid,
                "facility_id": rng.choice(FACILITIES)[0],
                "application_type": "initial" if rng.random() < 0.6 else "recredential",
                "status": status,
                "submitted_on": submitted.isoformat(),
                "decided_on": None if active else (submitted + datetime.timedelta(days=rng.randrange(20, 90))).isoformat(),
            }
        )

        issued = submitted - datetime.timedelta(days=rng.randrange(400, 2000))
        # The draw is made for every provider and then overridden for the
        # planted ones. Keeping the draw is deliberate: the generated workflow
        # has a committed manifest of row counts, and every number after this
        # point in the sequence moves if a draw is skipped. A planted provider
        # takes the state of the exclusion record it was built from, because
        # the name and state tier cannot be measured on a state nobody planted.
        licence_state = rng.choice(FACILITIES)[2]
        licenses.append(
            {
                "license_id": pid,
                "provider_id": pid,
                "state": planted_state.get(pid, licence_state),
                "license_number": "L%07d" % (rng.randrange(1, 9999999)),
                "issued_on": issued.isoformat(),
                "expires_on": (issued + datetime.timedelta(days=1095)).isoformat(),
                "status": "active" if rng.random() < 0.9 else "lapsed",
            }
        )

        for offset, source in enumerate(rng.sample(VERIFICATION_SOURCES, rng.randrange(2, 5))):
            requested = submitted + datetime.timedelta(days=offset)
            done = rng.random() < 0.8
            verifications.append(
                {
                    "verification_id": len(verifications) + 1,
                    "application_id": app_id,
                    "source": source,
                    "requested_at": requested.isoformat() + "T12:00:00+00:00",
                    "completed_at": (requested + datetime.timedelta(days=3)).isoformat() + "T12:00:00+00:00" if done else None,
                    "result": rng.choice(("clear", "clear", "clear", "hit")) if done else None,
                }
            )

        if not active:
            meeting = submitted + datetime.timedelta(days=rng.randrange(20, 90))
            decision = "approved" if status == "approved" else ("denied" if status == "denied" else "deferred")
            decisions.append(
                {
                    "decision_id": len(decisions) + 1,
                    "application_id": app_id,
                    "meeting_on": meeting.isoformat(),
                    "decision": decision,
                    "effective_from": meeting.isoformat() if decision == "approved" else None,
                    "effective_to": None,
                }
            )

    return {
        "arm": seed_note,
        "keys_spanning_more_than_one_state": keys_spanning_states,
        "tables": {
            "facility": facilities,
            "provider": providers,
            "application": applications,
            "license": licenses,
            "verification": verifications,
            "committee_decision": decisions,
        },
        "labels": labels,
    }
