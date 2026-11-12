"""Run the tiers over the real exclusion list and grade them against the plan.

    python3 scripts/measure_matching.py

Reads the downloaded exclusion list, regenerates the credentialing workflow
from it with the committed seed, matches every provider and writes
measurements/matching.json.

Needs no database. The generator returns the rows and the labels in memory, so
the grading does not depend on Postgres having loaded anything, and the answer
it writes is reproducible on any machine holding the same exclusion file. The
file's digest goes into the manifest for that reason.
"""

import argparse
import collections
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from credentialing import generate  # noqa: E402
from screening import evaluate, leie, match  # noqa: E402
from screening.registries import source  # noqa: E402

OUT = os.path.join("measurements", "matching.json")


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_exclusions(explicit=None):
    src = source("leie")
    path = explicit or os.path.join("data", "raw", src.local_name)
    encoding = src.encoding
    if not os.path.exists(path):
        path = os.path.join("tests", "fixtures", "leie_sample.csv")
        encoding = "utf-8"
        print("no downloaded exclusion list, measuring against the fixture at %s" % path)
    return path, encoding


DEFAULT_SEED = 20261110


def arm(rows, plant_state):
    """One measurement arm over an already read exclusion list."""
    built = generate.generate(rows, seed=DEFAULT_SEED, plant_state=plant_state)
    providers = built["tables"]["provider"]
    labels = {d["provider_id"]: d["label"] for d in built["labels"]}
    planted = {d["provider_id"]: d.get("planted_against", "") for d in built["labels"]}
    states = {row["provider_id"]: row["state"] for row in built["tables"]["license"]}

    index = match.Index(rows)
    results = match.match_all(providers, index, states)
    for result in results:
        result["planted_match"] = match.record_identities(rows, result["records"])

    tiers = evaluate.per_tier(
        results, labels, planted_against=planted, tier_order=match.TIER_ORDER
    )
    return {
        "arm": built["arm"],
        "index": {
            "identifiers": len(index.by_identifier),
            "name_and_dob_keys": len(index.by_name_and_dob),
            "name_and_state_keys": len(index.by_name_and_state),
        },
        "keys_spanning_more_than_one_state": built["keys_spanning_more_than_one_state"],
        "labels": dict(collections.Counter(labels.values())),
        "review": evaluate.held_for_review(results, labels),
        "tiers": tiers,
        "queue": evaluate.auto_clearable(results, labels),
    }


def run(exclusion_path, encoding):
    rows = list(leie.read(exclusion_path, encoding=encoding))
    return {
        "exclusion_file": os.path.basename(exclusion_path),
        "exclusion_sha256": digest(exclusion_path),
        "exclusion_records": len(rows),
        # The sample is deterministic for a given seed and a given file, so a
        # manifest that names neither cannot be reproduced from.
        "seed": DEFAULT_SEED,
        # Two arms. The second is the control, and it is the behaviour this
        # repository shipped yesterday: the licence state drawn from the four
        # facilities rather than taken from the exclusion record. A tier whose
        # answer does not move between the arms is not reading the state.
        "state_planted": arm(rows, True),
        "state_from_facility": arm(rows, False),
        "measured": ["state_planted", "state_from_facility"],
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclusions", default=None)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)

    path, encoding = load_exclusions(args.exclusions)
    measured = run(path, encoding)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(measured, fh, indent=1, sort_keys=True)
        fh.write("\n")

    print("wrote %s" % args.out)
    for name in ("state_planted", "state_from_facility"):
        print("%s:" % name)
        _report(measured[name])
    return 0


def _report(measured):
    for tier in match.TIER_ORDER:
        answer = measured["tiers"][tier]
        provider = answer["provider_graded"]
        pair = answer.get("pair_graded") or {}
        print(
            "  %-20s flagged %4d  precision %s  pair precision %s  recall %s"
            % (
                tier,
                answer["flagged"],
                _fmt(provider["precision"]),
                _fmt(pair.get("precision")),
                _fmt(provider["recall"]),
            )
        )
        print("      drawn from %s" % answer["flagged_by_label"])
    casc = measured["tiers"]["cascade"]
    print(
        "  cascade              flagged %4d  precision %s  recall %s"
        % (
            casc["flagged"],
            _fmt(casc["provider_graded"]["precision"]),
            _fmt(casc["provider_graded"]["recall"]),
        )
    )
    print("  excluded and cleared with nobody looking: %d" % casc["excluded_and_cleared"])
    for bucket, answer in sorted(measured["review"].items()):
        print(
            "  %-14s held for review %3d of %3d, cleared %3d"
            % (
                bucket,
                answer["held_for_review"],
                answer["providers"],
                answer["cleared_with_nobody_looking"],
            )
        )


def _fmt(value):
    return "    n/a" if value is None else "%7.4f" % value


if __name__ == "__main__":
    raise SystemExit(main())
