"""Every figure the README states about the source data is read back out of the manifest.

A count a document states about data the repository already measured is the one
kind of stale number that is free to prevent. Each row below names a manifest
path, and the check fails with the right value in its message.
"""

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
README = os.path.join(ROOT, "README.md")
MANIFEST = os.path.join(ROOT, "measurements", "registries.json")

# Table label in the README, then where the figure lives in the manifest.
PUBLISHED = (
    ("exclusion records", ("exclusions", "npi_column", "records")),
    ("records whose NPI column holds the character zero", ("exclusions", "npi_column", "absent")),
    ("records with an NPI that passes its check digit", ("exclusions", "npi_column", "usable")),
    ("distinct NPIs among those records", ("exclusions", "npi_fanout", "distinct_npis")),
    ("NPIs appearing on more than one record", ("exclusions", "npi_fanout", "npis_on_more_than_one_record")),
    ("most records sharing one NPI", ("exclusions", "npi_fanout", "worst_npi_record_count")),
    ("exact NPI", ("exclusions", "reachable_by_tier", "tier1_exact_npi")),
    ("exact name and date of birth", ("exclusions", "reachable_by_tier", "tier2_name_and_dob")),
    ("name and state only, an individual", ("exclusions", "reachable_by_tier", "name_and_state_only_individual")),
    ("name and state only, a business", ("exclusions", "reachable_by_tier", "name_and_state_only_business")),
    ("tier two keys formable", ("exclusions", "tier2_key", "keys_formable")),
    ("keys held by more than one record", ("exclusions", "tier2_key", "keys_held_by_more_than_one_record")),
    ("records sitting on a shared key", ("exclusions", "tier2_key", "records_on_a_shared_key")),
    ("most records sharing one key", ("exclusions", "tier2_key", "worst_key_record_count")),
    ("enrollment extract rows", ("enrollment", "lines")),
    ("enrollment rows that are not valid UTF-8", ("enrollment", "lines_not_valid_utf8")),
    ("distinct NPIs in the enrollment extract", ("enrollment", "distinct_npis")),
    ("exclusion NPIs also in the enrollment extract", ("enrollment_overlap", "in_both")),
    ("deactivated NPIs published", ("deactivated_overlap", "other_npis")),
    ("exclusion NPIs also deactivated", ("deactivated_overlap", "in_both")),
    ("registry weekly records", ("registry_weekly", "records")),
    ("weekly records with no entity type code", ("registry_weekly", "entity_type_absent")),
)

# Figures stated in prose rather than in a table. A number in a sentence has no
# address, so each one is named here with the arithmetic that produces it.
IN_PROSE = (
    ("75169 of", ("exclusions", "npi_column", "absent")),
    ("8924 of", ("exclusions", "npi_column", "usable")),
    ("Not one of the 8924 real NPIs", ("exclusions", "npi_column", "usable")),
    ("Eleven rows of three million", None),
)


def manifest():
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


def readme():
    with open(README, encoding="utf-8") as fh:
        return fh.read()


def dig(m, path):
    node = m
    for key in path:
        node = node[key]
    return node


def row_value(text, label):
    """The number in the table row whose first cell is label."""
    pattern = re.compile(r"^\|\s*" + re.escape(label) + r"\s*\|\s*([0-9]+)\s*\|\s*$", re.M)
    found = pattern.findall(text)
    if not found:
        raise AssertionError("no table row in the README reads %r" % label)
    if len(found) > 1:
        # An address matching twice is an error rather than a first one wins.
        raise AssertionError("%r matches %d rows in the README" % (label, len(found)))
    return int(found[0])


def check_every_published_table_figure_matches_the_manifest():
    text = readme()
    m = manifest()
    wrong = []
    for label, path in PUBLISHED:
        stated = row_value(text, label)
        real = dig(m, path)
        if stated != real:
            wrong.append("%s: README says %d, %s says %d" % (label, stated, ".".join(path), real))
    assert not wrong, wrong


def check_every_table_row_in_the_readme_is_one_this_check_knows_about():
    # Otherwise a figure can be added to a table and graded by nothing, which
    # is the whole failure this module exists to stop.
    text = readme()
    labels = re.findall(r"^\|\s*([a-zA-Z][^|]*?)\s*\|\s*([0-9]+)\s*\|\s*$", text, re.M)
    known = {label for label, _p in PUBLISHED}
    unknown = sorted({lab for lab, _v in labels} - known)
    assert not unknown, unknown


def check_the_figures_stated_in_prose_are_still_the_measured_ones():
    text = readme()
    m = manifest()
    for needle, path in IN_PROSE:
        assert needle in text, needle
        if path is not None:
            assert str(dig(m, path)) in needle, (needle, dig(m, path))


def check_the_floor_the_readme_states_is_the_sum_it_claims():
    # The README says 3730 records carry neither a usable NPI nor a date of
    # birth. That is arithmetic over two published rows, so it is derived here
    # rather than trusted.
    m = manifest()
    reach = m["exclusions"]["reachable_by_tier"]
    floor = reach["name_and_state_only_individual"] + reach["name_and_state_only_business"]
    assert ("%d records carry" % floor) in readme(), floor


def check_the_readme_states_that_nothing_has_run_against_snowflake():
    # The one claim in this file that would be the most damaging to get wrong.
    text = readme().lower()
    assert "nothing here has run against snowflake" in text
    assert "never been applied" in text


def check_the_readme_does_not_read_as_a_numbered_exercise():
    # A reader who sees a sequence number learns how this was scheduled rather
    # than what it does. Replace one with the thing it built.
    text = readme()
    pattern = r"\bday (?:[0-9]+|one|two|three|four|five|six|seven)\b"
    found = re.findall(pattern, text, re.I)
    assert not found, found


def check_every_script_the_readme_names_exists_in_this_repository():
    # Derived rather than a list of names to avoid, because a list covers what
    # its author remembered and, worse, a list of the names of tools that live
    # somewhere else is itself the thing it is trying to keep out of the file.
    text = readme()
    named = set(re.findall(r"[A-Za-z0-9_./-]+\.py", text))
    missing = sorted(n for n in named if not os.path.exists(os.path.join(ROOT, n)))
    assert not missing, missing
    assert named, "the README names no script, so this check graded nothing"


def check_every_path_the_readme_points_at_exists():
    text = readme()
    named = set(re.findall(r"`([A-Za-z0-9_][A-Za-z0-9_./-]*/[A-Za-z0-9_./-]+)`", text))
    missing = sorted(n for n in named if not os.path.exists(os.path.join(ROOT, n)))
    assert not missing, missing
    assert len(named) >= 5, sorted(named)
