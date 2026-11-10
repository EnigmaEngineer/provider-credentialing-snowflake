"""Reading the exclusion list, and deciding what its NPI column actually says.

The column is populated on every row. Most of those values are the single
character zero, which is how this file says it has no NPI for the record. That
is not the same as a null and it is the reason a loader needs to be told about
it: a numeric column holding 0 joins to nothing and reports as fully
populated.
"""

import csv

COLUMNS = (
    "LASTNAME", "FIRSTNAME", "MIDNAME", "BUSNAME", "GENERAL", "SPECIALTY",
    "UPIN", "NPI", "DOB", "ADDRESS", "CITY", "STATE", "ZIP", "EXCLTYPE",
    "EXCLDATE", "REINDATE", "WAIVERDATE", "WVRSTATE",
)

# The sentinel the file uses for "I do not have this". It is shared by NPI,
# REINDATE and WAIVERDATE, so every one of those needs the same treatment.
ABSENT = "0"

# The surname column carries a second sentinel and it is a word rather than a
# digit. Three records hold the four character string NULL, which is a
# serialised null that reached the file as text. A fallback key built on it
# matches every other record serialised the same way.
#
# Only the exact word is treated as absent. NA appears as a given name on three
# records and is left alone, because NA is a name somebody can have and NULL is
# not.
ABSENT_NAME = "NULL"

ABSENT_NPI = "absent"
MALFORMED_NPI = "malformed"
USABLE_NPI = "usable"


def npi_check_digit_ok(npi: str) -> bool:
    """The NPI carries a Luhn check digit computed over 80840 plus its first nine."""
    if len(npi) != 10 or not npi.isdigit():
        return False
    body = "80840" + npi[:9]
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (total + int(npi[9])) % 10 == 0


def classify_npi(value: str | None) -> str:
    """Three answers, not two. A missing NPI and an unusable one are different problems."""
    v = (value or "").strip()
    if v == "" or v == ABSENT:
        return ABSENT_NPI
    if not npi_check_digit_ok(v):
        return MALFORMED_NPI
    return USABLE_NPI


def is_individual(row: dict) -> bool:
    """A business record carries BUSNAME and no person name.

    Two separate questions live near each other here and conflating them puts
    a person in the wrong bucket. Whether this record is about a person is one
    question. Whether a key can be formed that identifies that person is
    another, and a surname that arrived as the serialised null answers no to
    the second while leaving the first alone. Those records carry a given name,
    so they are people reachable by name and state and not businesses.
    """
    last = (row.get("LASTNAME") or "").strip().upper()
    if last and last != ABSENT_NAME:
        return True
    return bool((row.get("FIRSTNAME") or "").strip())


def tier2_key(row: dict) -> tuple[str, str, str] | None:
    """Last name, first name and date of birth, or None when the row cannot form one.

    Returned upper cased because the two sides of the eventual match do not
    agree on case. Returning None rather than a tuple of empty strings matters,
    because a key of three blanks is a key that matches every other row that
    could not form one either.
    """
    last = (row.get("LASTNAME") or "").strip().upper()
    first = (row.get("FIRSTNAME") or "").strip().upper()
    dob = (row.get("DOB") or "").strip()
    if not last or last == ABSENT_NAME:
        return None
    if not first or not dob or dob == ABSENT:
        return None
    return (last, first, dob)


def read(path, encoding="utf-8-sig"):
    """Yield one dict per exclusion record.

    The header is checked against COLUMNS rather than trusted. The file has
    changed shape before, and a reader that takes whatever header it is given
    produces rows with keys nothing downstream asks for.
    """
    with open(path, newline="", encoding=encoding) as fh:
        reader = csv.DictReader(fh)
        got = tuple(reader.fieldnames or ())
        if got != COLUMNS:
            raise ValueError(
                "exclusion list header is not the one this reader was written for.\n"
                "  expected %r\n  got      %r" % (COLUMNS, got)
            )
        for row in reader:
            yield row
