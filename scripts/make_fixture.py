"""Build the committed exclusion fixture out of the real file.

The suite has to run on a clone that has downloaded nothing, so the checks
read a fixture rather than data/raw. Two things about how it is built matter
enough to be in the code rather than in a comment somewhere else.

Real rows are chosen by the repository's own classifier, so the fixture covers
the cases the classifier distinguishes rather than the cases whoever wrote it
remembered. Every date of birth is replaced and every street address is
cleared, because a name beside a date of birth is the pair this project masks
in the warehouse and committing it here would publish exactly that.

Two rows reach the same bucket by different routes and both are kept. A person
with no date of birth cannot form a fallback key. Neither can a person whose
surname arrived as the serialised null, and that one reads as a populated
surname to anything checking only for emptiness.

One case has no real example. No record in the real file carries an NPI that
fails its check digit, so the malformed row is constructed and labelled.

    python3 scripts/make_fixture.py
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screening import leie  # noqa: E402
from screening.registries import source  # noqa: E402

OUT = os.path.join("tests", "fixtures", "leie_sample.csv")

# Constructed, and deliberately not a plausible date. A fixture value that
# looks real is a fixture value somebody will later read as real.
SUBSTITUTE_DOB = "19000101"
SECOND_DOB = "19000202"


def blank_identity(row):
    out = dict(row)
    out["DOB"] = SUBSTITUTE_DOB if (row.get("DOB") or "").strip() not in ("", "0") else row.get("DOB")
    for field in ("ADDRESS", "CITY", "ZIP"):
        out[field] = ""
    return out


def pick(rows):
    """One bucket per answer the classifier can give, plus the fan out cases."""
    want = {
        "tier1": None,
        "tier2": None,
        "individual_no_dob": None,
        "sentinel_surname": None,
        "business": None,
    }
    fanout = []
    seen_npi = {}

    for row in rows:
        kind = leie.classify_npi(row["NPI"])
        if kind == leie.USABLE_NPI:
            npi = row["NPI"].strip()
            if npi in seen_npi and len(fanout) < 2:
                fanout = [seen_npi[npi], row]
            seen_npi.setdefault(npi, row)
            if want["tier1"] is None:
                want["tier1"] = row
        elif leie.tier2_key(row) is not None:
            if want["tier2"] is None:
                want["tier2"] = row
        elif leie.is_individual(row):
            # Two different reasons a person has no key and the fixture needs
            # both. One has no date of birth. The other has a surname that
            # arrived as the serialised null, which reads as a surname to
            # anything that only checks for emptiness.
            if (row.get("LASTNAME") or "").strip().upper() == leie.ABSENT_NAME:
                if want["sentinel_surname"] is None:
                    want["sentinel_surname"] = row
            elif want["individual_no_dob"] is None:
                want["individual_no_dob"] = row
        else:
            if want["business"] is None:
                want["business"] = row
        if all(v is not None for v in want.values()) and fanout:
            break

    missing = [k for k, v in want.items() if v is None]
    if missing or not fanout:
        raise SystemExit(
            "the real file did not supply every case the fixture needs: %r fanout=%d"
            % (missing, len(fanout))
        )
    return want, fanout


def build(rows):
    want, fanout = pick(rows)
    out = []

    # Lopsided on purpose. An inverted predicate has to move the count, and it
    # cannot when each answer has the same number of rows.
    out.append(blank_identity(want["tier1"]))
    out.extend(blank_identity(r) for r in fanout)
    out.append(blank_identity(want["tier2"]))
    out.append(blank_identity(want["individual_no_dob"]))
    out.append(blank_identity(want["sentinel_surname"]))
    out.append(blank_identity(want["business"]))

    # A second row sharing the tier two key of the one above it. Constructed,
    # because the substitute dates of birth are constructed, so a real
    # collision cannot survive into the fixture.
    collide = dict(blank_identity(want["tier2"]))
    collide["EXCLDATE"] = "20200101"
    out.append(collide)

    # The case the real file has no example of.
    malformed = dict(out[0])
    malformed["NPI"] = out[0]["NPI"][:9] + str((int(out[0]["NPI"][9]) + 1) % 10)
    malformed["LASTNAME"] = "CONSTRUCTED"
    malformed["FIRSTNAME"] = "CHECKDIGIT"
    malformed["DOB"] = SECOND_DOB
    out.append(malformed)

    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", default=os.path.join("data", "raw"))
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)

    src = source("leie")
    rows = leie.read(os.path.join(args.raw, src.local_name), encoding=src.encoding)
    built = build(rows)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(leie.COLUMNS))
        w.writeheader()
        for row in built:
            w.writerow({k: row.get(k, "") for k in leie.COLUMNS})
    print("wrote %s, %d rows" % (args.out, len(built)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
