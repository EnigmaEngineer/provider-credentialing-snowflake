"""Checks on the registry reader. The fixtures are zip archives built in the test."""

import io
import os
import tempfile
import zipfile

from screening import nppes

MEMBER = "npidata_pfile_20261102-20261108.csv"


def build_zip(path, header, rows, member=MEMBER):
    buf = io.StringIO()
    buf.write(",".join(header) + "\n")
    for row in rows:
        buf.write(",".join(row) + "\n")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(member, buf.getvalue())


def full_header():
    # A real file is 330 columns wide. The fixture is the needed ones plus one
    # the reader must ignore, so a reader returning everything fails here.
    return list(nppes.NEEDED) + ["Provider Credential Text"]


def check_the_needed_columns_are_returned_and_nothing_else():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "w.zip")
        build_zip(path, full_header(), [["1972902351", "1", "SMITH", "JO", "NY", "", "", "MD"]])
        rows = list(nppes.read_providers(path, MEMBER))
        assert len(rows) == 1, rows
        assert set(rows[0]) == set(nppes.NEEDED), sorted(rows[0])


def check_a_file_missing_a_needed_column_is_refused_and_names_it():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "w.zip")
        header = [c for c in nppes.NEEDED if c != "NPI Deactivation Date"]
        build_zip(path, header, [["1972902351", "1", "SMITH", "JO", "NY", ""]])
        try:
            list(nppes.read_providers(path, MEMBER))
        except ValueError as exc:
            assert "NPI Deactivation Date" in str(exc), str(exc)
        else:
            raise AssertionError("a file missing a needed column was accepted")


def check_an_absent_entity_type_is_a_third_answer():
    # 711 rows of the real weekly file carry neither 1 nor 2. Counting only the
    # two known codes made the parts stop adding up to the total.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "w.zip")
        build_zip(
            path,
            full_header(),
            [
                ["1972902351", nppes.ENTITY_INDIVIDUAL, "SMITH", "JO", "NY", "", "", ""],
                ["1922348218", nppes.ENTITY_ORGANISATION, "", "", "CA", "", "", ""],
                ["1689095580", nppes.ENTITY_ORGANISATION, "", "", "MA", "", "", ""],
                ["1407028269", "", "", "", "TX", "11/08/2026", "", ""],
            ],
        )
        rows = list(nppes.read_providers(path, MEMBER))
        individuals = sum(1 for r in rows if r["Entity Type Code"] == nppes.ENTITY_INDIVIDUAL)
        orgs = sum(1 for r in rows if r["Entity Type Code"] == nppes.ENTITY_ORGANISATION)
        absent = sum(1 for r in rows if not (r["Entity Type Code"] or "").strip())
        assert individuals + orgs + absent == len(rows), (individuals, orgs, absent, len(rows))
        assert (individuals, orgs, absent) == (1, 2, 1), (individuals, orgs, absent)


def check_a_deactivation_date_is_carried_through():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "w.zip")
        build_zip(
            path,
            full_header(),
            [["1407028269", "1", "SMITH", "JO", "TX", "11/08/2026", "", ""]],
        )
        rows = list(nppes.read_providers(path, MEMBER))
        assert rows[0]["NPI Deactivation Date"] == "11/08/2026", rows[0]


def build_deactivation_xlsx(path, rows, member="NPPES Deactivated NPI Report 20261109.xlsx"):
    """A spreadsheet in a zip, which is how the registry publishes this one."""
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    inner = os.path.join(os.path.dirname(path), "inner.xlsx")
    book.save(inner)
    with zipfile.ZipFile(path, "w") as zf:
        zf.write(inner, member)
    return member


def check_the_deactivation_reader_skips_the_title_and_header_rows():
    # The real sheet opens with a title and a header before any identifier, so
    # a reader taking the first row as data returns a row of prose.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "deact.zip")
        member = build_deactivation_xlsx(
            path,
            [
                ["NPPES Deactivated NPI Report", None],
                ["NPI", "NPI Deactivation Date"],
                ["1407028269", "11/08/2026"],
                ["1972902351", "10/01/2026"],
            ],
        )
        got = list(nppes.read_deactivated(path, member))
        assert got == [("1407028269", "11/08/2026"), ("1972902351", "10/01/2026")], got


def check_the_deactivation_reader_drops_a_blank_row():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "deact.zip")
        member = build_deactivation_xlsx(
            path,
            [
                ["NPI", "NPI Deactivation Date"],
                ["1407028269", "11/08/2026"],
                [None, None],
                ["1972902351", "10/01/2026"],
            ],
        )
        got = list(nppes.read_deactivated(path, member))
        assert len(got) == 2, got


def check_the_deactivation_reader_refuses_a_value_that_is_not_an_identifier():
    # The row filter is the whole reason a title row does not become data, so
    # it has to be driven with something that is neither blank nor a number.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "deact.zip")
        member = build_deactivation_xlsx(
            path,
            [
                ["NPI", "NPI Deactivation Date"],
                ["not an npi", "11/08/2026"],
                ["1407028269", "11/08/2026"],
            ],
        )
        got = list(nppes.read_deactivated(path, member))
        assert got == [("1407028269", "11/08/2026")], got


def check_a_numeric_identifier_cell_is_returned_as_a_string():
    # A spreadsheet stores a long run of digits as a number, and a join against
    # a text column then matches nothing.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "deact.zip")
        member = build_deactivation_xlsx(
            path,
            [
                ["NPI", "NPI Deactivation Date"],
                [1407028269, "11/08/2026"],
            ],
        )
        got = list(nppes.read_deactivated(path, member))
        assert got == [("1407028269", "11/08/2026")], got
        assert isinstance(got[0][0], str), type(got[0][0])


def check_the_needed_column_list_is_not_empty_and_names_the_identifier():
    assert nppes.NEEDED, "a reader that needs no columns refuses nothing"
    assert "NPI" in nppes.NEEDED
    assert nppes.ENTITY_INDIVIDUAL != nppes.ENTITY_ORGANISATION


def check_a_reader_handed_an_archive_without_the_member_raises():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "w.zip")
        build_zip(path, full_header(), [["1972902351", "1", "A", "B", "NY", "", "", ""]])
        try:
            list(nppes.read_providers(path, "not-in-the-archive.csv"))
        except KeyError:
            pass
        else:
            raise AssertionError("a missing archive member was accepted")


def check_the_deactivation_reader_takes_the_identifier_from_the_first_column():
    # Both columns hold digits in the real sheet, so a reader taking the wrong
    # one returns dates as identifiers and nothing about the shape complains.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "deact.zip")
        member = build_deactivation_xlsx(
            path,
            [
                ["NPI", "NPI Deactivation Date"],
                ["1407028269", "11082026"],
            ],
        )
        got = list(nppes.read_deactivated(path, member))
        assert got == [("1407028269", "11082026")], got
