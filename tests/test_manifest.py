"""Checks on the committed measurement manifest.

The manifest is the only place a figure about the source data is allowed to
come from, so the checks here are about whether it can be trusted rather than
about whether the numbers are nice.
"""

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(os.path.dirname(HERE), "measurements", "registries.json")

EXPECTED_SECTIONS = (
    "exclusions",
    "deactivated_overlap",
    "registry_weekly",
    "enrollment",
    "enrollment_overlap",
)

# A committed figure has to come out the same on another machine. A count does
# and a duration does not, so a duration does not go in here.
TIMING_WORDS = re.compile(r"(seconds|millis|ms$|_ms|duration|elapsed|wall|latency|took)", re.I)


def manifest():
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


def walk(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items():
            yield path + (k,), v
            yield from walk(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, path + (str(i),))


def check_the_manifest_parses():
    assert isinstance(manifest(), dict)


def check_the_manifest_says_which_pass_produced_it():
    # A pass run with a section skipped writes a shorter file that reads
    # exactly like a complete one. This key is what separates them.
    m = manifest()
    assert "measured" in m, sorted(m)
    assert isinstance(m["measured"], list)
    assert m["measured"], "measured is empty, so no section was recorded"


def check_every_section_named_as_measured_is_present():
    m = manifest()
    missing = [s for s in m["measured"] if s not in m]
    assert not missing, missing


def check_every_section_present_is_named_as_measured():
    # The other direction, which is what catches a section written by an older
    # pass and left behind.
    m = manifest()
    sections = [k for k in m if k != "measured"]
    unclaimed = [s for s in sections if s not in m["measured"]]
    assert not unclaimed, unclaimed


def check_the_committed_manifest_is_the_complete_pass():
    m = manifest()
    missing = [s for s in EXPECTED_SECTIONS if s not in m["measured"]]
    assert not missing, "the committed manifest was written with these skipped: %r" % (missing,)


def check_no_figure_in_the_manifest_is_a_wall_time():
    for path, value in walk(manifest()):
        key = path[-1]
        assert not TIMING_WORDS.search(str(key)), ".".join(path)


def check_every_leaf_figure_is_a_whole_number_or_a_flag():
    for path, value in walk(manifest()):
        if isinstance(value, (dict, list)):
            continue
        assert isinstance(value, (int, bool, str)), (".".join(path), type(value))
        if isinstance(value, float):
            raise AssertionError(".".join(path))


def check_the_exclusion_npi_counts_add_up_to_the_record_count():
    npi = manifest()["exclusions"]["npi_column"]
    parts = sum(v for k, v in npi.items() if k != "records")
    assert parts == npi["records"], npi


def check_the_reachability_counts_add_up_to_the_record_count():
    reach = manifest()["exclusions"]["reachable_by_tier"]
    parts = sum(v for k, v in reach.items() if k != "records")
    assert parts == reach["records"], reach


def check_the_weekly_entity_counts_add_up_to_the_record_count():
    # They did not on the first pass. The 711 rows in the gap carry no entity
    # type at all, and counting only the two documented codes lost them.
    w = manifest()["registry_weekly"]
    parts = w["individuals"] + w["organisations"] + w["entity_type_absent"]
    assert parts == w["records"], w


def check_a_deactivation_count_cannot_exceed_the_record_count():
    w = manifest()["registry_weekly"]
    assert 0 <= w["carrying_a_deactivation_date"] <= w["records"], w


def check_every_overlap_is_no_larger_than_either_side():
    m = manifest()
    for name in ("deactivated_overlap", "enrollment_overlap"):
        o = m[name]
        assert o["in_both"] <= o["exclusion_npis"], (name, o)
        assert o["in_both"] <= o["other_npis"], (name, o)


def check_the_fan_out_figures_are_consistent_with_each_other():
    f = manifest()["exclusions"]["npi_fanout"]
    assert f["distinct_npis"] <= f["records_with_a_usable_npi"], f
    assert f["npis_on_more_than_one_record"] <= f["distinct_npis"], f
    if f["npis_on_more_than_one_record"] > 0:
        assert f["worst_npi_record_count"] >= 2, f
        assert f["records_with_a_usable_npi"] > f["distinct_npis"], f


def check_the_enrollment_extract_is_recorded_as_having_no_status_column():
    e = manifest()["enrollment"]
    assert e["has_status_column"] is False, e
    # The eleven rows are the whole reason the encoding is declared per source.
    assert e["lines_not_valid_utf8"] > 0, e
    assert e["lines_not_valid_utf8"] < e["lines"], e


def check_the_exclusion_list_is_mostly_without_an_npi():
    # The claim the tiered design rests on, as a check rather than a sentence.
    # If a future refresh moves this the design argument has to be rewritten,
    # and a failing check is how anybody would find out.
    npi = manifest()["exclusions"]["npi_column"]
    assert npi["absent"] > npi["records"] * 0.5, npi
