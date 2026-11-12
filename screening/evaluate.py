"""Grading the matcher against the planted answer key.

Two gradings, and the gap between them is the point.

**Provider grading** asks whether a tier flagged a provider the answer key
says is on the exclusion list. It is the number a precision and recall table
normally reports.

**Pair grading** asks whether the tier matched that provider to the record it
was planted against. A tier can be right about the provider and wrong about
the record, and provider grading scores that as correct. A provider carrying
an excluded person's identifier and, by an accident of the generator's surname
pool, somebody else's surname is reachable by two tiers for two reasons, and
only one of them is about that person.

The positive class is "this provider is the excluded person". So the near miss
bucket is a negative. Same name, date of birth two years and a day away. That
is a different person and a tier calling them a match has made a mistake, even
though the right handling is a review rather than a clearance.
"""

from credentialing.generate import (
    EXACT_IDENTIFIER,
    NAME_AND_BIRTH,
    NEAR_MISS,
    UNRELATED,
)

from . import match

# The answer key's positive set. A provider in either bucket is the excluded
# person. The other two buckets are not that person, whatever a tier says.
TRULY_EXCLUDED = (EXACT_IDENTIFIER, NAME_AND_BIRTH)
NOT_EXCLUDED = (NEAR_MISS, UNRELATED)


def _rates(tp, fp, fn):
    """Precision and recall, with the denominator returned rather than hidden.

    A rate on its own cannot be read. A precision of 1.0 over two flagged
    providers and a precision of 1.0 over two hundred are different claims and
    the number is the same, so the counts travel with it.
    """
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": (tp / (tp + fp)) if (tp + fp) else None,
        "recall": (tp / (tp + fn)) if (tp + fn) else None,
    }


def per_tier(results, labels, planted_against=None, tier_order=()):
    """Precision and recall for each tier, counted over providers.

    `results` is what `match.match_all` returned. `labels` maps a provider
    identifier to its bucket name. `planted_against` maps a provider identifier
    to the identifier or key it was planted on, and when it is supplied every
    tier gains a pair graded answer beside the provider graded one.

    Recall's denominator is every truly excluded provider and not only the ones
    a tier could reach. A tier that reaches a tenth of the list has a recall of
    about a tenth, and that is the number the design question needs. Reporting
    recall against the reachable subset makes every tier look complete.
    """
    by_provider = {r["provider_id"]: r for r in results}
    excluded = [pid for pid, lab in labels.items() if lab in TRULY_EXCLUDED]
    out = {}

    for tier in tier_order:
        flagged = [pid for pid, r in by_provider.items() if r["tier"] == tier]
        tp = [pid for pid in flagged if labels.get(pid) in TRULY_EXCLUDED]
        fp = [pid for pid in flagged if labels.get(pid) in NOT_EXCLUDED]
        fn = [pid for pid in excluded if by_provider[pid]["tier"] != tier]
        answer = {"flagged": len(flagged), "provider_graded": _rates(len(tp), len(fp), len(fn))}

        if planted_against is not None:
            answer["pair_graded"] = _rates(
                sum(1 for pid in tp if _hit_the_planted_record(by_provider[pid], planted_against.get(pid))),
                len(fp) + sum(1 for pid in tp if not _hit_the_planted_record(by_provider[pid], planted_against.get(pid))),
                len(fn),
            )

        # The buckets the tier drew its flags from, so a precision figure can be
        # read against what it was carried by rather than taken on its own.
        answer["flagged_by_label"] = _count_labels(flagged, labels)
        out[tier] = answer

    out["cascade"] = _cascade(by_provider, labels, excluded)
    return out


def _hit_the_planted_record(result, planted):
    """Did this match reach the record the provider was planted on?

    `planted` is the identifier or the pipe joined fallback key the generator
    drew from, and `result` carries the record ordinals the tier matched. The
    comparison is on the record's own values rather than on the ordinal,
    because a key can sit on several records and planting named the key.
    """
    # One test rather than two. A null and an empty string are both "planted
    # against nothing" and spelling them separately left a mutation site whose
    # two forms return the same answer on every input this function can see.
    if not planted:
        return False
    return planted in (result.get("planted_match") or ())


def _count_labels(provider_ids, labels):
    out = {}
    for pid in provider_ids:
        lab = labels.get(pid, "unlabelled")
        out[lab] = out.get(lab, 0) + 1
    return out


def _cascade(by_provider, labels, excluded):
    """The whole cascade read as one classifier, which is what runs in production.

    A provider reaching any tier is a provider that does not get cleared
    automatically, so the cascade's positive is "flagged at all" and its
    negative is "cleared with nobody looking". That second number is the one
    that matters, because it is the set of providers the platform lets through.
    """
    flagged = [pid for pid, r in by_provider.items() if r["tier"] is not None]
    tp = [pid for pid in flagged if labels.get(pid) in TRULY_EXCLUDED]
    fp = [pid for pid in flagged if labels.get(pid) in NOT_EXCLUDED]
    fn = [pid for pid in excluded if by_provider[pid]["tier"] is None]
    answer = {"flagged": len(flagged), "provider_graded": _rates(len(tp), len(fp), len(fn))}
    answer["flagged_by_label"] = _count_labels(flagged, labels)
    answer["cleared_without_review"] = len(by_provider) - len(flagged)
    # An excluded provider that nothing flagged is the failure this platform
    # exists to prevent, so it is named rather than left to be derived from a
    # recall figure.
    answer["excluded_and_cleared"] = len(fn)
    return answer


def held_for_review(results, labels):
    """What a review tier has to be graded on, which is not precision.

    Graded as a classifier for "is this the excluded person", the name and
    state tier scores zero precision and zero recall, and both numbers are
    right. Every provider it flags is somebody who shares an excluded person's
    name and is not that person. Nothing it flags is a true positive and it
    finds none of the true positives, by construction, because anything whose
    date of birth agreed was already taken by the tier above it.

    The question the tier exists to answer is a different one. Of the providers
    who look like an excluded person and are not, how many did it stop from
    being cleared with nobody looking? That is a recall over the near miss
    bucket and it is the number that decides whether the tier is worth running.

    The cost side is counted here too. A review queue is paid for in people's
    time, so the providers who appear nowhere in the exclusion list and were
    sent to a person anyway are the price of the tier.
    """
    by_provider = {r["provider_id"]: r for r in results}
    out = {}
    for bucket in (NEAR_MISS, UNRELATED):
        pids = [pid for pid, lab in labels.items() if lab == bucket]
        held = [pid for pid in pids if by_provider[pid]["tier"] is not None]
        out[bucket] = {
            "providers": len(pids),
            "held_for_review": len(held),
            "cleared_with_nobody_looking": len(pids) - len(held),
            "held_share": (len(held) / len(pids)) if pids else None,
        }
    return out


def auto_clearable(results, labels):
    """How much of the sample the identifier tier can decide on its own.

    The design claim is that only an identifier match may clear or stop a
    provider without a person looking. This counts what that leaves, which is
    the size of the review queue as a share of the whole sample rather than as
    a share of the matches.
    """
    decided = sum(1 for r in results if r["tier"] == match.TIER1)
    reviewed = sum(
        1 for r in results if r["tier"] is not None and r["tier"] != match.TIER1
    )
    return {
        "providers": len(results),
        "decided_by_identifier": decided,
        "sent_to_review": reviewed,
        "cleared_with_no_match": len(results) - decided - reviewed,
        "labels_present": len(labels),
    }
