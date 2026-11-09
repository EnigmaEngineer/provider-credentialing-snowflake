"""Where each registry comes from, and how its bytes are to be read.

The encoding is declared here per source rather than sniffed. Two of the three
files are not in the same encoding and one of them is not valid UTF-8 at all,
so a reader that guesses is a reader that either dies or quietly replaces
characters in the one field the fallback match tiers depend on.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    key: str
    url: str
    local_name: str
    encoding: str
    member: str | None  # the file inside the archive, when the download is one
    what: str


# The monthly NPPES full file is 1,079.11 MB and nothing here downloads it. The
# weekly incremental carries the same record layout, which is what the readers
# and the staging models are written against.
SOURCES = (
    Source(
        key="leie",
        url="https://oig.hhs.gov/exclusions/downloadables/UPDATED.csv",
        local_name="leie_updated.csv",
        encoding="utf-8-sig",
        member=None,
        what="The OIG List of Excluded Individuals and Entities, refreshed monthly.",
    ),
    Source(
        key="nppes_weekly",
        url="https://download.cms.gov/nppes/NPPES_Data_Dissemination_110226_110826_Weekly_V2.zip",
        local_name="nppes_weekly.zip",
        encoding="utf-8",
        member="npidata_pfile_20261102-20261108.csv",
        what="One week of NPI registry adds and changes.",
    ),
    Source(
        key="nppes_deactivated",
        url="https://download.cms.gov/nppes/NPPES_Deactivated_NPI_Report_110926_V2.zip",
        local_name="nppes_deactivation.zip",
        encoding="utf-8",
        member="NPPES Deactivated NPI Report 20261109.xlsx",
        what="NPIs that have been deactivated. A deactivation is a credentialing event.",
    ),
    Source(
        key="cms_enrollment",
        url=(
            "https://data.cms.gov/sites/default/files/2026-09/"
            "b840a66b-6781-4630-9238-d056ecd633ce/PPEF_Enrollment_Extract_2026.09.29.csv"
        ),
        local_name="cms_ppef_enrollment.csv",
        # Eleven of 3,030,022 rows carry cp1252 bytes and are not valid UTF-8.
        # Decoding strictly as UTF-8 aborts the load. Decoding with errors
        # replaced turns ELAN into a name that cannot match. Neither is a load.
        encoding="cp1252",
        member=None,
        what="Medicare fee for service public provider enrollment.",
    ),
)

BY_KEY = {s.key: s for s in SOURCES}


def source(key: str) -> Source:
    try:
        return BY_KEY[key]
    except KeyError:
        raise KeyError("no registry source named %r" % key) from None
