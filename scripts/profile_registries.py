"""Measure what the registries contain and write it to measurements/registries.json.

Every figure this repository publishes about the source data comes from here.
The manifest holds counts only. A wall time does not reproduce on another
machine and a count does, so a count is what gets committed.

    python3 scripts/profile_registries.py
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screening import cms, leie, nppes, profile  # noqa: E402
from screening.registries import source  # noqa: E402

RAW = os.path.join("data", "raw")
OUT = os.path.join("measurements", "registries.json")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", default=RAW)
    ap.add_argument("--out", default=OUT)
    ap.add_argument(
        "--skip-enrollment",
        action="store_true",
        help="the enrollment extract is 326 MB and the pass over it is the slow part",
    )
    args = ap.parse_args(argv)

    leie_src = source("leie")
    leie_path = os.path.join(args.raw, leie_src.local_name)
    rows = list(leie.read(leie_path, encoding=leie_src.encoding))

    # A manifest written with a section skipped is still a manifest, and
    # nothing in the file said which pass produced it. Running with
    # --skip-enrollment overwrote a complete manifest with a shorter one that
    # read exactly like a complete one. measured names what this pass covered.
    out = {
        "measured": [],
        "exclusions": {
            "npi_column": profile.exclusion_npi_profile(rows),
            "reachable_by_tier": profile.reachability(rows),
            "tier2_key": profile.tier2_key_collisions(rows),
            "npi_fanout": profile.npi_fanout(rows),
        }
    }

    out["measured"].append("exclusions")

    excl_npis = {
        r["NPI"].strip() for r in rows if leie.classify_npi(r["NPI"]) == leie.USABLE_NPI
    }

    deact_src = source("nppes_deactivated")
    deact_npis = {
        npi
        for npi, _ in nppes.read_deactivated(
            os.path.join(args.raw, deact_src.local_name), deact_src.member
        )
    }
    out["deactivated_overlap"] = profile.overlap(excl_npis, deact_npis)
    out["measured"].append("deactivated_overlap")

    weekly_src = source("nppes_weekly")
    weekly = list(
        nppes.read_providers(
            os.path.join(args.raw, weekly_src.local_name),
            weekly_src.member,
            encoding=weekly_src.encoding,
        )
    )
    # The three entity counts have to add up to the record count. They did not
    # on the first pass, and the 711 rows in the gap carry no entity type at
    # all, which is a third answer rather than a reader dropping rows.
    out["registry_weekly"] = {
        "records": len(weekly),
        "individuals": sum(
            1 for r in weekly if r["Entity Type Code"] == nppes.ENTITY_INDIVIDUAL
        ),
        "organisations": sum(
            1 for r in weekly if r["Entity Type Code"] == nppes.ENTITY_ORGANISATION
        ),
        "entity_type_absent": sum(
            1 for r in weekly if not (r["Entity Type Code"] or "").strip()
        ),
        "carrying_a_deactivation_date": sum(
            1 for r in weekly if (r["NPI Deactivation Date"] or "").strip()
        ),
    }

    out["measured"].append("registry_weekly")

    if not args.skip_enrollment:
        enr_src = source("cms_enrollment")
        enr_path = os.path.join(args.raw, enr_src.local_name)
        total, bad = cms.non_utf8_lines(enr_path)
        enr_npis = {
            r["NPI"].strip()
            for r in cms.read(enr_path, encoding=enr_src.encoding)
            if (r["NPI"] or "").strip()
        }
        out["enrollment"] = {
            "lines": total,
            "lines_not_valid_utf8": bad,
            "distinct_npis": len(enr_npis),
            "has_status_column": not cms.NO_STATUS_COLUMN,
        }
        out["enrollment_overlap"] = profile.overlap(excl_npis, enr_npis)
        out["measured"] += ["enrollment", "enrollment_overlap"]

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
    print(json.dumps(out, indent=2, sort_keys=True))
    print("written to %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
