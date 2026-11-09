"""Reading the NPI registry, out of the archive rather than out of an unpacked copy.

The weekly incremental and the monthly full file share a record layout, so the
readers here are written against the weekly one and the monthly file is a
bigger input to the same code. The deactivation report is a spreadsheet rather
than a delimited file, which is a third format in a set of three sources.
"""

import csv
import io
import zipfile

# The registry file is 330 columns wide. Only the ones a screening match needs
# are named, and read_providers refuses a file that is missing any of them
# rather than returning rows with keys that are silently absent.
NEEDED = (
    "NPI",
    "Entity Type Code",
    "Provider Last Name (Legal Name)",
    "Provider First Name",
    "Provider Business Practice Location Address State Name",
    "NPI Deactivation Date",
    "NPI Reactivation Date",
)

ENTITY_INDIVIDUAL = "1"
ENTITY_ORGANISATION = "2"


def read_providers(archive_path, member, encoding="utf-8"):
    """Yield one dict per NPI record, cut down to NEEDED."""
    with zipfile.ZipFile(archive_path) as zf:
        with zf.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding=encoding, newline="")
            reader = csv.DictReader(text)
            got = set(reader.fieldnames or ())
            missing = [c for c in NEEDED if c not in got]
            if missing:
                raise ValueError(
                    "registry file is missing columns this reader needs: %r" % (missing,)
                )
            for row in reader:
                yield {c: row[c] for c in NEEDED}


def read_deactivated(archive_path, member):
    """Yield (npi, deactivation date) out of the deactivation spreadsheet.

    openpyxl is a real dependency for exactly this one file. It is declared
    rather than imported optionally, because a screening cycle that cannot see
    a deactivation is a screening cycle missing a credentialing event.
    """
    import openpyxl

    with zipfile.ZipFile(archive_path) as zf:
        data = zf.read(member)
    book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheet = book[book.sheetnames[0]]
    for row in sheet.iter_rows(values_only=True):
        if not row or row[0] is None:
            continue
        npi = str(row[0]).strip()
        if not npi.isdigit():
            continue  # the sheet opens with a title and a header row
        yield npi, row[1]
    book.close()
