"""What the registries actually contain, measured rather than assumed.

The tiered match design rests on a claim about the exclusion list: that many
records carry no NPI, so matching has to fall back to name and date of birth.
The functions here are what turn that claim into a number, and the number is
what decides how much of the design is the fallback path.
"""

import collections

from . import leie


def exclusion_npi_profile(rows):
    """Count exclusion records by what their NPI column can be used for."""
    out = collections.Counter()
    for row in rows:
        out[leie.classify_npi(row["NPI"])] += 1
        out["records"] += 1
    return dict(out)


def reachability(rows):
    """Which match tier each exclusion record is reachable by at all.

    This is a statement about the data and not about any threshold. A record
    with no NPI and no date of birth cannot be reached by an exact tier however
    the later tiers are tuned, so it is a floor on the review queue rather than
    a number anybody can improve.
    """
    out = collections.Counter()
    for row in rows:
        out["records"] += 1
        if leie.classify_npi(row["NPI"]) == leie.USABLE_NPI:
            out["tier1_exact_npi"] += 1
        elif leie.tier2_key(row) is not None:
            out["tier2_name_and_dob"] += 1
        elif leie.is_individual(row):
            out["name_and_state_only_individual"] += 1
        else:
            out["name_and_state_only_business"] += 1
    return dict(out)


def tier2_key_collisions(rows):
    """How often the fallback key fails to identify one record.

    A key held by more than one record cannot clear either of them, so this is
    a property of the key rather than of whatever it is matched against.
    """
    counts = collections.Counter()
    for row in rows:
        k = leie.tier2_key(row)
        if k is not None:
            counts[k] += 1
    shared = {k: v for k, v in counts.items() if v > 1}
    return {
        # Two different quantities and the design question needs both. The
        # distinct keys say how many providers the tier can tell apart. The
        # records say how many it can reach at all, and that is the number
        # every other figure in this profile is a count of records.
        "distinct_keys": len(counts),
        "records_that_can_form_a_key": sum(counts.values()),
        "keys_held_by_more_than_one_record": len(shared),
        "records_on_a_shared_key": sum(shared.values()),
        "worst_key_record_count": max(counts.values()) if counts else 0,
    }


def npi_fanout(rows):
    """Distinct usable NPIs against the records carrying them.

    One provider can hold several exclusion records. A match keyed on NPI is
    therefore one to many, and anything treating it as one to one inflates
    whatever it counts.
    """
    counts = collections.Counter()
    for row in rows:
        if leie.classify_npi(row["NPI"]) == leie.USABLE_NPI:
            counts[row["NPI"].strip()] += 1
    return {
        "records_with_a_usable_npi": sum(counts.values()),
        "distinct_npis": len(counts),
        "npis_on_more_than_one_record": sum(1 for v in counts.values() if v > 1),
        "worst_npi_record_count": max(counts.values()) if counts else 0,
    }


def overlap(exclusion_npis, other_npis):
    """Set overlap, with both sides sized so the number has a denominator."""
    both = exclusion_npis & other_npis
    return {
        "exclusion_npis": len(exclusion_npis),
        "other_npis": len(other_npis),
        "in_both": len(both),
    }
