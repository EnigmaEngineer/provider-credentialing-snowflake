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
# Three manifests now, because the document publishes figures about the
# registries, about the generated credentialing workflow and about what
# replication carries. Each row below names which one it reads.
MANIFESTS = {
    "registries": os.path.join(ROOT, "measurements", "registries.json"),
    "credentialing": os.path.join(ROOT, "measurements", "credentialing.json"),
    "replication": os.path.join(ROOT, "measurements", "replication.json"),
    "targets": os.path.join(ROOT, "measurements", "targets.json"),
    "matching": os.path.join(ROOT, "measurements", "matching.json"),
    "agreement": os.path.join(ROOT, "measurements", "matching_agreement.json"),
}

# Table label in the README, then the manifest and the path within it.
PUBLISHED = (
    ("exclusion records", ("registries", "exclusions", "npi_column", "records")),
    ("records whose NPI column holds the character zero", ("registries", "exclusions", "npi_column", "absent")),
    ("records with an NPI that passes its check digit", ("registries", "exclusions", "npi_column", "usable")),
    ("distinct NPIs among those records", ("registries", "exclusions", "npi_fanout", "distinct_npis")),
    ("NPIs appearing on more than one record", ("registries", "exclusions", "npi_fanout", "npis_on_more_than_one_record")),
    ("most records sharing one NPI", ("registries", "exclusions", "npi_fanout", "worst_npi_record_count")),
    ("exact NPI", ("registries", "exclusions", "reachable_by_tier", "tier1_exact_npi")),
    ("exact name and date of birth", ("registries", "exclusions", "reachable_by_tier", "tier2_name_and_dob")),
    ("name and state only, an individual", ("registries", "exclusions", "reachable_by_tier", "name_and_state_only_individual")),
    ("name and state only, a business", ("registries", "exclusions", "reachable_by_tier", "name_and_state_only_business")),
    ("records that can form a tier two key", ("registries", "exclusions", "tier2_key", "records_that_can_form_a_key")),
    ("distinct tier two keys", ("registries", "exclusions", "tier2_key", "distinct_keys")),
    ("keys held by more than one record", ("registries", "exclusions", "tier2_key", "keys_held_by_more_than_one_record")),
    ("records sitting on a shared key", ("registries", "exclusions", "tier2_key", "records_on_a_shared_key")),
    ("most records sharing one key", ("registries", "exclusions", "tier2_key", "worst_key_record_count")),
    ("enrollment extract rows", ("registries", "enrollment", "lines")),
    ("enrollment rows that are not valid UTF-8", ("registries", "enrollment", "lines_not_valid_utf8")),
    ("distinct NPIs in the enrollment extract", ("registries", "enrollment", "distinct_npis")),
    ("exclusion NPIs also in the enrollment extract", ("registries", "enrollment_overlap", "in_both")),
    ("deactivated NPIs published", ("registries", "deactivated_overlap", "other_npis")),
    ("exclusion NPIs also deactivated", ("registries", "deactivated_overlap", "in_both")),
    ("registry weekly records", ("registries", "registry_weekly", "records")),
    ("weekly records with no entity type code", ("registries", "registry_weekly", "entity_type_absent")),
    ("providers generated", ("credentialing", "rows_loaded", "provider")),
    ("providers carrying an identifier from the exclusion list", ("credentialing", "labels", "exact_identifier")),
    ("providers carrying a name and date of birth from one", ("credentialing", "labels", "name_and_birth")),
    ("providers carrying that name and a different date of birth", ("credentialing", "labels", "near_miss")),
    ("providers appearing nowhere in the exclusion list", ("credentialing", "labels", "unrelated")),
    ("credentialing applications", ("credentialing", "rows_loaded", "application")),
    ("state licences", ("credentialing", "rows_loaded", "license")),
    ("primary source verifications", ("credentialing", "rows_loaded", "verification")),
    ("committee decisions", ("credentialing", "rows_loaded", "committee_decision")),
    ("providers in the sample", ("matching", "state_planted", "queue", "providers")),
    ("flagged by the identifier tier", ("matching", "state_planted", "tiers", "tier1_identifier", "flagged")),
    ("flagged by the name and date of birth tier", ("matching", "state_planted", "tiers", "tier2_name_and_dob", "flagged")),
    ("flagged by the name and state tier", ("matching", "state_planted", "tiers", "tier3_name_state", "flagged")),
    ("providers cleared with nobody looking", ("matching", "state_planted", "tiers", "cascade", "cleared_without_review")),
    ("excluded providers nothing flagged", ("matching", "state_planted", "tiers", "cascade", "excluded_and_cleared")),
    ("providers compared", ("agreement", "providers")),
    ("candidate pairs at the strongest tier", ("agreement", "sql_candidate_pairs_at_strongest_tier")),
    ("pairs only in the SQL", ("agreement", "pairs_only_in_sql")),
    ("pairs only in Python", ("agreement", "pairs_only_in_python")),
    ("providers whose tier disagrees", ("agreement", "providers_whose_tier_disagrees")),
)

# The two arm table, which carries one label and two numbers per row, so the
# single column reader above cannot address it.
ARM_ROWS = (
    ("state planted from the exclusion record", "state_planted"),
    ("state drawn from the facilities", "state_from_facility"),
)

# Rates stated in prose. A rate has no table row and rounding it by hand is how
# a figure stops matching its manifest, so each one is recomputed here.
RATES = (
    ("falls from 0.99 to 0.67", ("state_from_facility", "state_planted")),
)

# Figures stated in prose rather than in a table. A number in a sentence has no
# address, so each one is named here with the arithmetic that produces it.
IN_PROSE = (
    ("75169 of", ("registries", "exclusions", "npi_column", "absent")),
    ("8924 of", ("registries", "exclusions", "npi_column", "usable")),
    ("Not one of the 8924 real NPIs", ("registries", "exclusions", "npi_column", "usable")),
    ("Eleven rows of three million", None),
)


def manifest(name="registries"):
    with open(MANIFESTS[name], encoding="utf-8") as fh:
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
    loaded = {name: manifest(name) for name in MANIFESTS}
    wrong = []
    for label, address in PUBLISHED:
        which, path = address[0], address[1:]
        stated = row_value(text, label)
        real = dig(loaded[which], path)
        if stated != real:
            wrong.append(
                "%s: README says %d, %s.%s says %d" % (label, stated, which, ".".join(path), real)
            )
    assert not wrong, wrong


def check_every_manifest_this_check_reads_was_written_by_a_complete_run():
    # A narrowed pass writes a shorter file that reads exactly like a whole
    # one. Every manifest carries a list of what it covered, and the two
    # directions are checked because one of them alone passes on a file that
    # names a section it does not hold.
    for name in sorted(MANIFESTS):
        m = manifest(name)
        named = m.get("measured")
        assert named, "%s carries no measured list" % name
        for section in named:
            assert section in m, (name, section)


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
    for needle, address in IN_PROSE:
        assert needle in text, needle
        if address is not None:
            which, path = address[0], address[1:]
            value = dig(manifest(which), path)
            assert str(value) in needle, (needle, value)


def check_the_floor_the_readme_states_is_the_sum_it_claims():
    # The README says 3730 records carry neither a usable NPI nor a date of
    # birth. That is arithmetic over two published rows, so it is derived here
    # rather than trusted.
    m = manifest("registries")
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


# What each replica identity put in the log, as the README publishes it. The
# values are words rather than numbers so the numeric row check cannot reach
# them, which is why this table gets a check of its own.
REPLICATION_ROWS = {
    "pk_default": ("default", "yes", ["IN", "UN", "DK"]),
    "pk_full": ("full", "yes", ["IN", "UO", "DO"]),
    "pk_index": ("index", "yes", ["IN", "UK", "DK"]),
    "no_pk": ("default", "no", ["IN"]),
    "identity_nothing": ("nothing", "yes", ["IN"]),
}

IDENTITY_LETTER = {"default": "d", "full": "f", "index": "i", "nothing": "n"}


def check_the_replication_table_says_what_the_measurement_says():
    m = manifest("replication")
    wrong = []
    for name, (identity, has_key, wal) in sorted(REPLICATION_ROWS.items()):
        got = m["catalog"][name]
        if got["replica_identity"] != IDENTITY_LETTER[identity]:
            wrong.append("%s identity: README says %s, manifest says %s" % (name, identity, got["replica_identity"]))
        if got["has_primary_key"] != (has_key == "yes"):
            wrong.append("%s primary key: README says %s" % (name, has_key))
        if m["wal_per_table"].get(name) != wal:
            wrong.append("%s log: README says %r, manifest says %r" % (name, wal, m["wal_per_table"].get(name)))
    assert not wrong, wrong


def check_every_arm_the_readme_names_was_actually_measured():
    # The two directions. An arm in the document that never ran, and an arm
    # that ran and is not in the document, are different failures and only one
    # of them is caught by checking a value.
    m = manifest("replication")
    named = set(REPLICATION_ROWS)
    measured = set(m["arms"])
    assert named == measured, (sorted(named - measured), sorted(measured - named))
    text = readme()
    for name in sorted(named):
        assert name in text, name


def check_the_readme_quotes_the_refusal_the_measurement_recorded():
    # The quoted error is the strongest claim in the document. It is compared
    # against the message the server actually returned rather than kept as a
    # sentence somebody typed.
    m = manifest("replication")
    real = m["statements"]["no_pk"]["delete"]["error"]
    assert real, "the measurement recorded no refusal for the table with no primary key"
    text = " ".join(readme().split())
    assert " ".join(real.split()) in text, real


def check_no_staging_model_uses_the_filter_that_drops_live_rows():
    # The suite cannot run dbt, so it reads the models as text. That is a
    # weaker check than running them and it is the one that works on a clone.
    models = os.path.join(ROOT, "transform", "models")
    offenders = []
    seen = 0
    for root, _dirs, files in os.walk(models):
        for name in sorted(files):
            if not name.endswith(".sql"):
                continue
            seen += 1
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                body = fh.read()
            for line in body.splitlines():
                stripped = line.strip()
                if stripped.startswith("--"):
                    continue
                if "not_deleted_naive" in stripped or re.search(r"not\s+_fivetran_deleted", stripped):
                    offenders.append("%s: %s" % (name, stripped))
    assert seen, "no staging model was read, so this check graded nothing"
    assert not offenders, offenders


# Where each staging model and each source has to resolve on the warehouse
# target. The models are written to the analytics database and read from the
# raw one, and a configuration that reads the database it writes into produces
# a name just as readily.
ANALYTICS_DATABASE = "SCREENING_ANALYTICS"
RAW_DATABASE = "SCREENING_RAW"
STAGING_SCHEMA = "staging"


def check_the_warehouse_target_resolved_every_model_into_the_analytics_database():
    answers = manifest("targets")["resolved"]["snowflake"]
    assert answers["adapter"] == "snowflake", answers["adapter"]
    assert answers["models"], "no model resolved, so this check graded nothing"
    wrong = []
    for name, relation in sorted(answers["models"].items()):
        expected = "%s.%s.%s" % (ANALYTICS_DATABASE, STAGING_SCHEMA, name)
        if relation != expected:
            wrong.append("%s resolved to %s" % (name, relation))
    assert not wrong, wrong


def check_the_warehouse_target_resolved_every_source_into_the_raw_database():
    answers = manifest("targets")["resolved"]["snowflake"]
    assert answers["sources"], "no source resolved, so this check graded nothing"
    wrong = [
        "%s resolved to %s" % (name, relation)
        for name, relation in sorted(answers["sources"].items())
        if not relation.startswith(RAW_DATABASE + ".")
    ]
    assert not wrong, wrong


def check_no_relation_name_agrees_across_the_two_targets():
    # A name that agrees is a name one of the targets did not resolve, which is
    # what reading the other target's manifest looks like. The manifest records
    # the list and the measurement refuses to write a stale one, so this is the
    # committed half of that guard.
    m = manifest("targets")
    assert m["names_agreeing_across_targets"] == [], m["names_agreeing_across_targets"]
    assert sorted(m["targets"]) == ["duckdb", "snowflake"], m["targets"]
    for target in m["targets"]:
        assert m["resolved"][target]["adapter"] == target, target


def check_the_schema_is_not_the_configured_name_written_twice():
    # The defect the comparison found, pinned so it cannot come back quietly.
    answers = manifest("targets")["resolved"]
    for target in sorted(answers):
        for name, relation in sorted(answers[target]["models"].items()):
            doubled = "%s_%s" % (STAGING_SCHEMA, STAGING_SCHEMA)
            assert doubled not in relation, (target, name, relation)


def check_the_two_arm_table_matches_the_manifest():
    text = readme()
    m = manifest("matching")
    for label, arm in ARM_ROWS:
        pattern = re.compile(
            r"^\|\s*" + re.escape(label) + r"\s*\|\s*([0-9]+)\s*\|\s*([0-9]+)\s*\|\s*$", re.M
        )
        found = pattern.findall(text)
        assert len(found) == 1, (label, found)
        flagged, cleared = (int(v) for v in found[0])
        assert flagged == m[arm]["tiers"]["tier3_name_state"]["flagged"], (label, flagged)
        assert cleared == m[arm]["review"]["near_miss"]["cleared_with_nobody_looking"], (
            label,
            cleared,
        )


def check_the_prose_rates_are_the_measured_ones_rounded():
    text = readme()
    m = manifest("matching")
    for needle, arms in RATES:
        assert needle in text, needle
        stated = re.findall(r"0\.[0-9]{2}", needle)
        assert len(stated) == len(arms), (needle, stated)
        for said, arm in zip(stated, arms):
            real = m[arm]["tiers"]["cascade"]["provider_graded"]["precision"]
            assert said == "%.2f" % real, (arm, said, real)


def check_the_readme_says_the_review_tier_held_every_near_miss():
    text = readme()
    m = manifest("matching")
    held = m["state_planted"]["review"]["near_miss"]["held_for_review"]
    total = m["state_planted"]["review"]["near_miss"]["providers"]
    assert "%d of %d in the planted" % (held, total) in text, (held, total)


def check_the_readme_states_the_pair_disagreement_the_comparison_found():
    # The number of pairs the first run disagreed on is not in any manifest,
    # because the manifest holds the answer after the fix. It is stated in the
    # README and in the changelog, and this check keeps the two figures in the
    # sentence consistent with the committed pair count rather than with each
    # other.
    text = readme()
    m = manifest("agreement")
    pairs = m["sql_candidate_pairs_at_strongest_tier"]
    assert "disagreed on 103 of" in text, "the README no longer states the first run's gap"
    assert "the %d pairs" % pairs in text, pairs
    assert m["pairs_only_in_sql"] == 0 and m["pairs_only_in_python"] == 0, m
