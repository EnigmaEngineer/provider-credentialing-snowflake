"""Credits per monthly cycle, derived rather than observed.

Writes measurements/credits.json. Nothing here was measured on an account.
Every number comes from the committed configuration and the published billing
rules, so every number re-derives on any machine from the repository alone.

Re-run this on any day that changes a warehouse size, a cluster count, an
auto_suspend, the dbt profile's warehouse, or the stages in the monthly cycle.
Those are the only inputs.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestration import cycle  # noqa: E402
from screening import credits, identity, tfread  # noqa: E402

# Which stage is executed by what. The four dbt stages resolve their warehouse
# from the profile, so that one is read rather than written here. The other
# two are executed by something that is not dbt and the reason is recorded
# beside each, because a stage silently left out of a cost model is the way a
# cost model comes out low.
NOT_RUN_BY_DBT = {
    "land_registry_files": (
        "snowpipe",
        "auto ingest from the external stage. Snowpipe is serverless and its credits are not on the warehouse rate table, so no rate here applies to it",
    ),
    "replicate_credentialing": (
        "fivetran",
        "the Fivetran destination writes with the warehouse named by var.loading_warehouse, which is an account specific value this repository does not hold",
    ),
}


def measure(root):
    entries = tfread.read_dir(os.path.join(root, "infra"))
    warehouses = {}
    for _file, b in entries:
        if b.kind != "resource" or not b.labels or b.labels[0] != "snowflake_warehouse":
            continue
        name = b.value("name")
        size = b.value("warehouse_size")
        warehouses[name] = {
            "address": b.address,
            "size": size,
            "auto_suspend_seconds": b.value("auto_suspend"),
            "max_cluster_count": b.value("max_cluster_count"),
            "rate_per_hour_one_cluster": credits.rate_per_hour(size),
            "ceiling_per_hour": credits.ceiling_per_hour(size, b.value("max_cluster_count")),
        }

    profile_pairs, _calls = identity.profile_identities(
        os.path.join(root, "transform", "profiles", "profiles.yml")
    )
    profile = dict(profile_pairs)
    dbt_warehouse = profile.get("SNOWFLAKE_WAREHOUSE")

    stages = [s.name for s in cycle.plan()]
    assignment = {}
    for name in stages:
        if name in NOT_RUN_BY_DBT:
            engine, why = NOT_RUN_BY_DBT[name]
            assignment[name] = {"engine": engine, "warehouse": None, "why": why}
        else:
            assignment[name] = {
                "engine": "dbt",
                "warehouse": dbt_warehouse,
                "why": "the dbt profile's SNOWFLAKE_WAREHOUSE fallback, read out of the profile rather than written here",
            }

    on_a_warehouse = {}
    for name, where in assignment.items():
        if where["warehouse"]:
            on_a_warehouse.setdefault(where["warehouse"], []).append(name)

    per_warehouse = {}
    for name, names in sorted(on_a_warehouse.items()):
        if name not in warehouses:
            raise SystemExit("the cycle runs on %s and no resource creates it" % name)
        wh = warehouses[name]
        low, high = credits.resumption_bounds(len(names))
        per_warehouse[name] = {
            "stages": sorted(names),
            "stage_count": len(names),
            "resumptions_low": low,
            "resumptions_high": high,
            "floor_credits_low": round(credits.floor_credits(low, wh["size"]), 6),
            "floor_credits_high": round(credits.floor_credits(high, wh["size"]), 6),
            "auto_suspend_seconds": wh["auto_suspend_seconds"],
        }

    monitor = {}
    for _file, b in entries:
        if b.kind == "resource" and b.labels and b.labels[0] == "snowflake_resource_monitor":
            monitor = {
                "name": b.value("name"),
                "quota_is_a_literal": b.value("credit_quota") is not None,
                "quota": b.value("credit_quota"),
                "frequency": b.value("frequency"),
                "suspend_trigger": b.value("suspend_trigger"),
                "suspend_immediate_trigger": b.value("suspend_immediate_trigger"),
            }

    floor_low = round(sum(v["floor_credits_low"] for v in per_warehouse.values()), 6)
    floor_high = round(sum(v["floor_credits_high"] for v in per_warehouse.values()), 6)

    return {
        "derived_not_observed": True,
        "warehouses": warehouses,
        "warehouse_count": len(warehouses),
        "account_ceiling_per_hour": sum(w["ceiling_per_hour"] for w in warehouses.values()),
        "account_ceiling_if_clusters_were_ignored": sum(
            w["rate_per_hour_one_cluster"] for w in warehouses.values()
        ),
        "cycle_stages": stages,
        "stage_count": len(stages),
        "stages_with_a_derivable_rate": sum(v["stage_count"] for v in per_warehouse.values()),
        "stage_count_with_no_derivable_rate": len(NOT_RUN_BY_DBT),
        "measured": [
            "warehouses",
            "stage_assignment",
            "per_warehouse",
            "monitor",
            "sourced_facts",
        ],
        "stage_assignment": assignment,
        "per_warehouse": per_warehouse,
        "cycle_floor_credits_low": floor_low,
        "cycle_floor_credits_high": floor_high,
        "stages_with_no_derivable_rate": sorted(NOT_RUN_BY_DBT),
        "monitor": monitor,
        "sourced_facts": {
            key: {"value": credits.fact(key).value, "quote": credits.fact(key).quote, "url": credits.fact(key).url}
            for key in sorted(credits.SOURCED_FACTS)
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    result = measure(args.root)
    out = args.out or os.path.join(args.root, "measurements", "credits.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")
    # Printed in the shape the README quotes, so the block there is this
    # command's output rather than a transcription of it. A gate compares the
    # two and a figure that moved without the document moving fails.
    print("warehouse             size    clusters  credits/hour  auto_suspend")
    for name in sorted(result["warehouses"]):
        w = result["warehouses"][name]
        print("%-21s %-7s %8d %13d %13d"
              % (name, w["size"], w["max_cluster_count"], w["ceiling_per_hour"], w["auto_suspend_seconds"]))
    print("account ceiling %d credits an hour, and %d read off the sizes alone"
          % (result["account_ceiling_per_hour"], result["account_ceiling_if_clusters_were_ignored"]))
    for name in sorted(result["per_warehouse"]):
        v = result["per_warehouse"][name]
        print("%s carries %d stages" % (name, v["stage_count"]))
        print("resumptions   %d if every gap is under auto_suspend, %d if every gap is over it"
              % (v["resumptions_low"], v["resumptions_high"]))
        print("floor         %.4f credits                        %.4f credits"
              % (v["floor_credits_low"], v["floor_credits_high"]))
    print("no derivable rate for %s" % ", ".join(result["stages_with_no_derivable_rate"]))
    print("the monitor quota is a literal: %s" % result["monitor"].get("quota_is_a_literal"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
