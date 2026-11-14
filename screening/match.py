"""Matching a credentialing provider against the exclusion list, in tiers.

Three tiers, strongest first. A provider is assigned to the first tier that
matches it, because an identifier hit does not also need a name review. The
order is the whole design: it decides which queue a provider lands in and
therefore whether a person has to look at it.

    tier1_identifier    the provider's identifier is one an exclusion record
                        carries. The only tier that may clear or stop a
                        provider without a person looking.
    tier2_name_and_dob  no usable identifier on either side, and the surname,
                        given name and date of birth agree.
    tier3_name_state    the surname, given name and state agree, and the dates
                        of birth do not. This tier never decides anything. It
                        is the review queue.

What the tiers read is what the staging layer publishes and not a recomputation
of it. `npi_is_absent` and `fallback_key` are columns in
`stg_registry__exclusion`, and the two spellings of this logic have to agree,
so the shapes are kept close on purpose.

An exclusion record is identified here by its ordinal in the file it was read
from. The file carries no identifier of its own, so this one is derived, and it
is stable only for a given file. Anything persisting it has to persist the
file's digest beside it.
"""

import collections

from . import leie

TIER1 = "tier1_identifier"
TIER2 = "tier2_name_and_dob"
TIER3 = "tier3_name_state"

# Strongest first. The cascade walks this order and stops at the first hit.
TIER_ORDER = (TIER1, TIER2, TIER3)


class Index:
    """The exclusion list arranged for lookup, built once and read many times.

    Three dictionaries rather than one, because the three tiers ask different
    questions and a single composite key would answer none of them. Each maps
    to a list of record ordinals, not to one ordinal, because every one of
    these keys is held by more than one record somewhere in the real file.
    """

    def __init__(self, rows):
        self.by_identifier = collections.defaultdict(list)
        self.by_name_and_dob = collections.defaultdict(list)
        self.by_name_and_state = collections.defaultdict(list)
        self.record_count = 0

        for ordinal, row in enumerate(rows):
            self.record_count += 1
            if leie.classify_npi(row.get("NPI")) == leie.USABLE_NPI:
                self.by_identifier[row["NPI"].strip()].append(ordinal)
            key = leie.tier2_key(row)
            if key is not None:
                self.by_name_and_dob[key].append(ordinal)
            name_state = _name_and_state(row)
            if name_state is not None:
                self.by_name_and_state[name_state].append(ordinal)


def _name_and_state(row):
    """Surname, given name and state, or None when the record cannot form one.

    A business record has no person name and so cannot be reached by this tier
    at all. That is not a tuning problem: there is no surname to compare. The
    exclusion list carries 2,869 of them and they are a floor on the review
    queue rather than a number anybody can improve.

    None rather than a tuple of blanks, for the same reason the fallback key
    returns None. A tuple of three empty strings matches every other record
    that could not form one either.
    """
    last = (row.get("LASTNAME") or "").strip().upper()
    first = (row.get("FIRSTNAME") or "").strip().upper()
    state = (row.get("STATE") or "").strip().upper()
    if not last or last == leie.ABSENT_NAME:
        return None
    if not first or not state:
        return None
    return (last, first, state)


def provider_identifier(provider):
    """The provider's identifier, or None when it carries none it can be used.

    Three spellings of absent reach this function and all three have to answer
    the same way. A null. An empty string. And the character zero, which is
    what the registry files write and what the credentialing application
    copies when it has nothing better. The staging layer publishes this as
    `npi_is_absent` and this is the same question asked in Python.
    """
    value = (provider.get("npi") or "").strip()
    if value == "" or value == leie.ABSENT:
        return None
    return value


def provider_name_and_dob(provider):
    """The provider's fallback key, in the shape the exclusion list forms it.

    The exclusion file writes a date of birth as eight digits and the
    credentialing database stores a date. They are compared as eight digits
    here, because that is the form the file publishes and converting the other
    way needs a parse that can fail on the side that has no reason to fail.
    """
    last = (provider.get("last_name") or "").strip().upper()
    first = (provider.get("first_name") or "").strip().upper()
    dob = _eight_digits(provider.get("date_of_birth"))
    if not last or not first or dob is None:
        return None
    return (last, first, dob)


def _eight_digits(value):
    """A date stored as YYYY-MM-DD, as the eight digits the exclusion file uses."""
    text = (value or "").strip()
    if not text:
        return None
    digits = text.replace("-", "")
    if len(digits) != 8 or not digits.isdigit():
        return None
    return digits


def provider_name_and_state(provider, state):
    last = (provider.get("last_name") or "").strip().upper()
    first = (provider.get("first_name") or "").strip().upper()
    st = (state or "").strip().upper()
    if not last or not first or not st:
        return None
    return (last, first, st)


def match_provider(provider, index, state=None):
    """Walk the tiers strongest first and stop at the first one that hits.

    Returns the tier name and the exclusion record ordinals it matched, or
    (None, ()) when no tier reaches this provider.

    The identifier tier is skipped entirely when the provider carries no usable
    identifier, which is not the same as the tier missing. A provider with no
    identifier was never a candidate for it, and counting that as a tier one
    miss makes the tier look worse than it is on data where most providers have
    nothing to match on.
    """
    ident = provider_identifier(provider)
    if ident is not None:
        hits = index.by_identifier.get(ident)
        if hits:
            return TIER1, tuple(hits)

    key = provider_name_and_dob(provider)
    if key is not None:
        hits = index.by_name_and_dob.get(key)
        if hits:
            return TIER2, tuple(hits)

    name_state = provider_name_and_state(provider, state)
    if name_state is not None:
        hits = index.by_name_and_state.get(name_state)
        if hits:
            # A provider whose date of birth agrees with one of these records
            # was already caught by tier two, so anything arriving here
            # disagrees on the date or has no date on one side. That is the
            # review queue and it is not a decision.
            return TIER3, tuple(hits)

    return None, ()


def match_every_tier(provider, index, state=None):
    """Every pair every tier can form, rather than the strongest tier's pairs.

    The cascade above answers which queue a provider lands in. This answers
    what a reviewer working that decision can see, and they are different
    questions. int_screening__match_candidate emits all three tiers and the
    model's own comment says why: a second tier pair is still worth keeping
    for somebody reviewing a first tier decision.

    Added 2026-11-14. The access measurement built the candidate relation out
    of match_provider and came back with four rows where the warehouse has
    five, because one provider is reached by the second tier and the third.
    Nothing in this module could produce the warehouse's answer, so the
    Python side had only ever been able to reimplement the queue.

    Returns a tuple of (tier, ordinals) for each tier that reaches the
    provider, in tier order.
    """
    out = []
    ident = provider_identifier(provider)
    if ident is not None:
        hits = index.by_identifier.get(ident)
        if hits:
            out.append((TIER1, tuple(hits)))

    key = provider_name_and_dob(provider)
    if key is not None:
        hits = index.by_name_and_dob.get(key)
        if hits:
            out.append((TIER2, tuple(hits)))

    name_state = provider_name_and_state(provider, state)
    if name_state is not None:
        hits = index.by_name_and_state.get(name_state)
        if hits:
            out.append((TIER3, tuple(hits)))

    return tuple(out)


def match_all(providers, index, states=None):
    """One result per provider, in the order the providers arrived.

    `states` maps a provider identifier to the state the match should use. The
    provider table carries no state of its own. It is on the licence, which is
    a separate table, and taking it from there rather than inventing a column
    is the reason this is a parameter.
    """
    states = states or {}
    out = []
    for provider in providers:
        tier, hits = match_provider(provider, index, states.get(provider["provider_id"]))
        out.append(
            {
                "provider_id": provider["provider_id"],
                "tier": tier,
                "records": hits,
            }
        )
    return out


def record_identities(rows, ordinals):
    """What the matched records are identified by, in planting's own vocabulary.

    The generator plants a provider against an identifier or against a fallback
    key, so grading a match on the pair rather than on the provider needs the
    matched records expressed the same way. A record contributes its identifier
    when it carries a usable one and its pipe joined key when it can form one,
    and a record can contribute both.

    `rows` has to be the same list the index was built from, because the
    ordinals are positions in it.
    """
    out = set()
    for ordinal in ordinals:
        row = rows[ordinal]
        if leie.classify_npi(row.get("NPI")) == leie.USABLE_NPI:
            out.add(row["NPI"].strip())
        key = leie.tier2_key(row)
        if key is not None:
            out.add("|".join(key))
    return frozenset(out)
