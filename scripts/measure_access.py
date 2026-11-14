"""What each role sees, and what the columns it still reads give back.

    python3 scripts/measure_access.py

Two arms, because the two questions have different scales.

The first arm asks what a redaction leaves recoverable, and it needs the whole
sample. For every pair a tier formed, it compares the column the review queue
publishes about the matched record against the provider value a masking policy
would be hiding. An equality join means the two are the same string on every row
the tier reached, so the redaction costs the reader nothing and protects nobody.
Nothing about a column called matched_fallback_key says it is a surname, a given
name and a date of birth with pipes between them.

The second arm asks what each role ends up with, and it runs over the committed
seed fixture because that is the part that travels. It applies the design in
screening/access.py to the relations as they are built and counts the rows and
the columns each role is left holding.

The recoveries this finds are compared against the ones the design declares, in
both directions, by tests/test_access.py. A recovery nobody declared is a leak
and a declared recovery nobody measured is a rule resting on an assumption.

The exclusion list is read from the same download the matching measurement
reads, so the two agree on the file by digest rather than by name.
"""

import argparse
import collections
import csv
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screening import access, leie, match  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "measurements", "access.json")
WORK = os.path.join(ROOT, "data", "work")
EXCLUSIONS = os.path.join(ROOT, "data", "raw", "leie_updated.csv")
SEEDS = os.path.join(ROOT, "transform", "seeds")


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def published_about_the_record(records, ordinals):
    """The two columns the candidate model publishes about a matched record.

    Spelled the way the model spells them. matched_npi is null when the record
    says it has no identifier, which is the 11-12 fix, and matched_fallback_key
    is the record's own key joined with pipes.
    """
    out = []
    for ordinal in ordinals:
        row = records[ordinal]
        npi = row.get("NPI", "").strip()
        matched_npi = None if leie.classify_npi(npi) != leie.USABLE_NPI else npi
        key = leie.tier2_key(row)
        out.append(
            {
                "matched_npi": matched_npi,
                "matched_fallback_key": None if key is None else "|".join(key),
            }
        )
    return out


def recovery_arm(providers, states, records):
    """Per tier, how often a published column gives back a withheld value.

    The comparison is against the provider's own value rather than against the
    join condition that produced the pair. Reading the condition would tell you
    the same thing and it would be an argument rather than a measurement, and
    the argument is what was wrong about the surname on the third tier.
    """
    index = match.Index(records)
    counters = collections.defaultdict(lambda: collections.Counter())
    pairs_per_tier = collections.Counter()

    for provider in providers:
        tier, ordinals = match.match_provider(
            provider, index, states.get(provider["provider_id"])
        )
        if tier is None:
            continue
        own_npi = match.provider_identifier(provider)
        own_key = match.provider_name_and_dob(provider)
        for published in published_about_the_record(records, ordinals):
            pairs_per_tier[tier] += 1
            counts = counters[tier]

            if own_npi is not None and published["matched_npi"] == own_npi:
                counts["matched_npi_recovers_the_identifier"] += 1

            fallback = published["matched_fallback_key"]
            if fallback is not None and own_key is not None:
                parts = fallback.split("|")
                if tuple(parts) == own_key:
                    counts["matched_fallback_key_recovers_the_identity"] += 1
                elif len(parts) == 3 and parts[0] == own_key[0] and parts[1] == own_key[1]:
                    # Two of the three. The third tier joins on the surname and
                    # the given name and reaches rows whose dates of birth
                    # disagree, so this is the shape it leaves rather than an
                    # edge case.
                    counts["matched_fallback_key_recovers_the_name_only"] += 1

    return {
        tier: {
            "pairs": pairs_per_tier[tier],
            **{k: v for k, v in sorted(counters[tier].items())},
        }
        for tier in sorted(pairs_per_tier)
    }


def seed_relations():
    """The two published relations as the seed fixture builds them.

    Built here in Python rather than read out of a warehouse. The relations are
    dbt views and dbt is not installable on the machine this runs on, and a
    measurement that only runs where dbt is installed is a measurement the suite
    cannot grade on a clone. The row rules are the ones the models state and
    tests/test_access.py compares the row counts against the models' own tests.
    """
    providers = [
        r for r in read_csv(os.path.join(SEEDS, "raw_credentialing_provider.csv"))
        if r["_fivetran_deleted"].strip().lower() not in ("true", "1")
    ]
    applications = [
        r for r in read_csv(os.path.join(SEEDS, "raw_credentialing_application.csv"))
        if r["_fivetran_deleted"].strip().lower() not in ("true", "1")
    ]
    licences = [
        r for r in read_csv(os.path.join(SEEDS, "raw_credentialing_license.csv"))
        if r["_fivetran_deleted"].strip().lower() not in ("true", "1")
    ]
    exclusions = read_csv(os.path.join(SEEDS, "raw_registry_exclusion.csv"))
    records = [{k.upper(): v for k, v in row.items()} for row in exclusions]

    facility = {}
    for app in applications:
        if app["status"] in ("submitted", "in_verification", "committee_review"):
            facility[app["provider_id"]] = int(app["facility_id"])

    states = {}
    for lic in licences:
        states.setdefault(lic["provider_id"], lic["state"].strip().upper())

    index = match.Index(records)
    queue = []
    candidates = []
    for row in providers:
        provider = {
            "provider_id": row["provider_id"],
            "npi": row["npi"],
            "last_name": row["last_name"],
            "first_name": row["first_name"],
            "date_of_birth": row["date_of_birth"],
        }
        tier, _strongest = match.match_provider(provider, index, states.get(row["provider_id"]))
        rank = None if tier is None else match.TIER_ORDER.index(tier) + 1
        queue.append(
            {
                "provider_id": row["provider_id"],
                "npi": provider["npi"],
                "last_name": provider["last_name"],
                "first_name": provider["first_name"],
                "date_of_birth": provider["date_of_birth"],
                "tier": tier,
                "tier_rank": rank,
                "cleared_without_review": tier is None,
                "facility_id": facility.get(row["provider_id"]),
            }
        )
        # Every tier, not the strongest one. The candidate model unions all
        # three and the queue model picks the strongest out of it, so a
        # relation built from the cascade is the queue under the candidate
        # model's name. One provider in this fixture is reached by two tiers.
        for pair_tier, ordinals in match.match_every_tier(
            provider, index, states.get(row["provider_id"])
        ):
            pair_rank = match.TIER_ORDER.index(pair_tier) + 1
            for published in published_about_the_record(records, ordinals):
                candidates.append(
                    {
                        "provider_id": row["provider_id"],
                        "tier": pair_tier,
                        "tier_rank": pair_rank,
                        "matched_npi": published["matched_npi"],
                        "matched_fallback_key": published["matched_fallback_key"],
                        "facility_id": facility.get(row["provider_id"]),
                    }
                )
    return {"review_queue": queue, "match_candidate": candidates}


def role_arm(relations):
    """Rows and columns per role per relation, by the rule the design states."""
    out = {}
    for role in access.ROLES:
        per_relation = {}
        for name in role.reads:
            rel = access.relation(name)
            rows = relations[name]
            visible = [r for r in rows if access.row_is_visible(role, rel, r)]
            withheld = sorted(access.withheld_from(role, rel))
            conditional = access.conditionally_withheld_from(role, rel)
            per_relation[name] = {
                "rows_in_the_relation": len(rows),
                "rows_this_role_reads": len(visible),
                "columns_in_the_relation": len(rel.columns),
                "columns_withheld": withheld,
                "columns_withheld_conditionally": sorted(conditional),
                "unscoped_rows_reached": sum(
                    1 for r in visible if rel.scope_column and r.get(rel.scope_column) is None
                ),
            }
        out[role.name] = {
            "reads_every_row": role.reads_every_row,
            "relations": per_relation,
        }
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exclusions", default=EXCLUSIONS)
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args(argv)

    measured = ["seed_relations", "roles"]
    result = {
        "measured": measured,
        "unscoped_rows_go_to_every_reviewer": access.UNSCOPED_ROWS_GO_TO_EVERY_REVIEWER,
    }

    provider_path = os.path.join(WORK, "provider.csv")
    licence_path = os.path.join(WORK, "license.csv")
    if os.path.exists(provider_path) and os.path.exists(args.exclusions):
        records = list(leie.read(args.exclusions))
        providers = read_csv(provider_path)
        states = {}
        if os.path.exists(licence_path):
            for lic in read_csv(licence_path):
                states.setdefault(lic["provider_id"], lic["state"].strip().upper())
        result["recovery_at_full_scale"] = {
            "providers": len(providers),
            "exclusion_records": len(records),
            "exclusion_file_sha256": digest(args.exclusions),
            "per_tier": recovery_arm(providers, states, records),
        }
        measured.append("recovery_at_full_scale")
    else:
        # Named rather than skipped quietly. data/work is generated and not
        # committed, so this arm cannot run on a clean clone and a manifest
        # that simply lacked the section would read like a complete one.
        result["recovery_at_full_scale"] = None

    relations = seed_relations()
    result["seed_relations"] = {
        name: {"rows": len(rows)} for name, rows in sorted(relations.items())
    }
    result["roles"] = role_arm(relations)

    result["measured"] = sorted(measured)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1, sort_keys=True)
        handle.write("\n")
    print(json.dumps(result["recovery_at_full_scale"], indent=1, sort_keys=True))
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
