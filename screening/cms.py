"""Reading the Medicare public enrollment extract.

Two things about this file decide whether anything built on it is honest. It
is not valid UTF-8, and it carries no column saying whether an enrollment is
live. So an NPI appearing here is an NPI that appears here, and nothing more
than that can be read off it.
"""

import csv

COLUMNS = (
    "NPI", "MULTIPLE_NPI_FLAG", "PECOS_ASCT_CNTL_ID", "ENRLMT_ID",
    "PROVIDER_TYPE_CD", "PROVIDER_TYPE_DESC", "STATE_CD", "FIRST_NAME",
    "MDL_NAME", "LAST_NAME", "ORG_NAME",
)

# There is no status, termination or end date column. Anything claiming a
# provider is currently enrolled needs a source this file is not.
NO_STATUS_COLUMN = True


def read(path, encoding="cp1252"):
    """Yield one dict per enrollment row.

    The encoding is an argument with a real default rather than a guess made
    per call. Passing errors="replace" is what a reader does when it wants the
    load to finish, and it damages the name fields the fallback tiers match on,
    so it is not offered.
    """
    csv.field_size_limit(10_000_000)
    with open(path, newline="", encoding=encoding) as fh:
        reader = csv.DictReader(fh)
        got = tuple(reader.fieldnames or ())
        if got != COLUMNS:
            raise ValueError(
                "enrollment extract header is not the one this reader was written for.\n"
                "  expected %r\n  got      %r" % (COLUMNS, got)
            )
        for row in reader:
            yield row


def non_utf8_lines(path):
    """Count the rows a strict UTF-8 load would abort on.

    Worth having as a number rather than as a sentence, because it is eleven
    rows in three million and that is the whole reason nobody finds it.
    """
    bad = 0
    total = 0
    with open(path, "rb") as fh:
        for raw in fh:
            total += 1
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                bad += 1
    return total, bad
