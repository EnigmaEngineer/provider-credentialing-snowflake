"""Checks on the enrollment reader, built around the encoding.

Eleven rows of three million in the real extract are not valid UTF-8. The
fixtures here are tiny and constructed, because the point is the branch and not
the scale.
"""

import csv
import os
import tempfile

from screening import cms

HEADER = ",".join(cms.COLUMNS)


def write(path, body_lines, encoding="cp1252"):
    with open(path, "w", newline="", encoding=encoding) as fh:
        fh.write(HEADER + "\n")
        for line in body_lines:
            fh.write(line + "\n")


def check_a_header_that_is_not_the_expected_one_is_refused():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "wrong.csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(["NPI", "STATE_CD"])
        try:
            list(cms.read(path, encoding="utf-8"))
        except ValueError as exc:
            assert "header" in str(exc), str(exc)
        else:
            raise AssertionError("a two column file was accepted")


def check_a_cp1252_name_is_read_whole():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "enr.csv")
        write(path, ["1972902351,N,1,E1,14-08,FAMILY PRACTICE,NY,COURTNEY,ÉLAN,MCCALL,"])
        rows = list(cms.read(path))
        assert len(rows) == 1, rows
        assert rows[0]["MDL_NAME"] == "ÉLAN", rows[0]["MDL_NAME"]


def check_the_same_bytes_read_as_utf8_raise_rather_than_damage_the_name():
    # The two wrong answers are an aborted load and a replaced character. A
    # replaced character is the worse one, because the name still looks like a
    # name and no longer matches anything.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "enr.csv")
        write(path, ["1972902351,N,1,E1,14-08,FAMILY PRACTICE,NY,COURTNEY,ÉLAN,MCCALL,"])
        try:
            list(cms.read(path, encoding="utf-8"))
        except UnicodeDecodeError:
            pass
        else:
            raise AssertionError("a cp1252 byte decoded as utf-8 without raising")

        lenient = open(path, encoding="utf-8", errors="replace").read()
        assert "�" in lenient
        assert "ÉLAN" not in lenient


def check_non_utf8_lines_counts_the_body_and_not_the_header():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "enr.csv")
        write(
            path,
            [
                "1972902351,N,1,E1,14-08,FAMILY PRACTICE,NY,A,ÉLAN,B,",
                "1922348218,N,2,E2,14-50,NURSE PRACTITIONER,CA,C,,D,",
                "1689095580,N,3,E3,14-50,NURSE PRACTITIONER,MA,E,ÁX,F,",
            ],
        )
        total, bad = cms.non_utf8_lines(path)
        assert total == 4, total
        assert bad == 2, bad


def check_a_file_that_is_wholly_utf8_reports_no_bad_lines():
    # The control. Without it the counter could return the line count and the
    # check above would still pass.
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "enr.csv")
        write(
            path,
            [
                "1972902351,N,1,E1,14-08,FAMILY PRACTICE,NY,A,B,C,",
                "1922348218,N,2,E2,14-50,NURSE PRACTITIONER,CA,D,E,F,",
            ],
            encoding="utf-8",
        )
        total, bad = cms.non_utf8_lines(path)
        assert (total, bad) == (3, 0), (total, bad)


def check_the_reader_states_that_the_extract_has_no_status_column():
    # The constant is what stops a later day reading an NPI in this file as a
    # live enrollment. There is no column that would support that.
    assert cms.NO_STATUS_COLUMN is True
    for name in cms.COLUMNS:
        assert "STATUS" not in name.upper(), name
        assert "TERM" not in name.upper(), name
        assert "END" not in name.upper(), name


def check_a_reader_handed_a_missing_file_raises_rather_than_returning_nothing():
    # A generator that yields nothing for a path that does not exist makes
    # every count over it zero and every check on it pass.
    try:
        list(cms.read("/does/not/exist.csv"))
    except OSError:
        pass
    else:
        raise AssertionError("a missing enrollment file was accepted")
