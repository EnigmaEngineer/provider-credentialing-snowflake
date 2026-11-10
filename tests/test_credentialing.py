"""The generated credentialing workflow, and the rules over the source database.

Everything here reads the committed fixture or the committed measurement. The
generator runs against the small exclusion fixture rather than the download, so
these checks work on a clone, and the plan is scaled down to fit it.
"""

import json
import os

from credentialing import catalog, generate
from screening import leie

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, "fixtures", "leie_sample.csv")
MANIFEST = os.path.join(ROOT, "measurements", "credentialing.json")

# The fixture carries three distinct identifiers and two distinct fallback
# keys, so the plan has to fit inside that. The two keyed buckets end up at one
# each and a count cannot tell them apart, which is worth saying rather than
# leaving as a gap. They are separated by property instead: one shares the
# exclusion record's date of birth and the other does not, and swapping them
# fails both of those checks while leaving every count where it was.
SMALL = generate.Plan(exact_identifier=2, name_and_birth=1, near_miss=1, unrelated=5)


def fixture_rows():
    return list(leie.read(FIXTURE, encoding="utf-8"))


def built(seed=1):
    return generate.generate(fixture_rows(), plan=SMALL, seed=seed)


def manifest():
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


def check_the_same_seed_gives_the_same_rows():
    first = built(seed=7)
    second = built(seed=7)
    assert first == second


def check_a_different_seed_gives_different_rows():
    # Otherwise the seed is decoration and the determinism check above is
    # passing on a generator that ignores it.
    assert built(seed=7) != built(seed=8)


def check_the_label_counts_are_the_plan():
    out = built()
    counts = {}
    for item in out["labels"]:
        counts[item["label"]] = counts.get(item["label"], 0) + 1
    assert counts == SMALL.as_dict(), counts
    assert len(out["tables"]["provider"]) == SMALL.total()


def check_every_label_names_a_provider_that_exists():
    out = built()
    ids = {row["provider_id"] for row in out["tables"]["provider"]}
    labelled = {item["provider_id"] for item in out["labels"]}
    assert ids == labelled, (sorted(ids - labelled), sorted(labelled - ids))


def check_no_label_column_reached_the_tables():
    # A source system does not know which of its providers are excluded. A
    # label in the data would answer the question the warehouse exists to ask.
    out = built()
    for name, rows in sorted(out["tables"].items()):
        for row in rows:
            assert "label" not in row, name


def check_the_planted_identifiers_are_ones_the_classifier_calls_usable():
    out = built()
    labels = {item["provider_id"]: item["label"] for item in out["labels"]}
    planted = [
        row
        for row in out["tables"]["provider"]
        if labels[row["provider_id"]] == generate.EXACT_IDENTIFIER
    ]
    assert len(planted) == SMALL.exact_identifier
    for row in planted:
        assert leie.classify_npi(row["npi"]) == leie.USABLE_NPI, row["npi"]


def check_no_two_planted_providers_share_one_exclusion_record():
    # Two providers claiming one record would make a recall denominator wrong,
    # because the record is found once and both providers count it.
    out = built()
    labels = {item["provider_id"]: item["label"] for item in out["labels"]}
    identifiers = [
        row["npi"]
        for row in out["tables"]["provider"]
        if labels[row["provider_id"]] == generate.EXACT_IDENTIFIER
    ]
    assert len(identifiers) == len(set(identifiers)), identifiers
    keys = [
        (row["last_name"], row["first_name"], row["date_of_birth"])
        for row in out["tables"]["provider"]
        if labels[row["provider_id"]] == generate.NAME_AND_BIRTH
    ]
    assert len(keys) == len(set(keys)), keys


def check_a_near_miss_shares_the_name_and_not_the_date_of_birth():
    out = built()
    labels = {item["provider_id"]: item["label"] for item in out["labels"]}
    by_label = {}
    for row in out["tables"]["provider"]:
        by_label.setdefault(labels[row["provider_id"]], []).append(row)

    exclusion_keys = {
        (last, first, dob) for last, first, dob in generate.exclusion_pools(fixture_rows())[1]
    }
    names = {(last, first) for last, first, _dob in exclusion_keys}

    for row in by_label[generate.NEAR_MISS]:
        pair = (row["last_name"], row["first_name"])
        assert pair in names, pair
        stated = (row["date_of_birth"] or "").replace("-", "")
        matches = [dob for last, first, dob in exclusion_keys if (last, first) == pair]
        assert stated not in matches, (pair, stated, matches)


def check_a_planted_match_shares_both():
    out = built()
    labels = {item["provider_id"]: item["label"] for item in out["labels"]}
    exclusion_keys = {
        (last, first, dob) for last, first, dob in generate.exclusion_pools(fixture_rows())[1]
    }
    found = 0
    for row in out["tables"]["provider"]:
        if labels[row["provider_id"]] != generate.NAME_AND_BIRTH:
            continue
        key = (row["last_name"], row["first_name"], (row["date_of_birth"] or "").replace("-", ""))
        assert key in exclusion_keys, key
        assert row["npi"] is None, row["npi"]
        found += 1
    assert found == SMALL.name_and_birth


def check_the_unrelated_providers_carry_no_identifier_and_an_unlisted_surname():
    # The surnames to avoid are read straight off the fixture rows rather than
    # out of the pools the generator builds. Reading them from the pools asks
    # the generator which surnames it excluded and then checks that it excluded
    # them, which passes however the pools are built. A mutation that emptied
    # the surname in one pool survived against the earlier version of this
    # check for exactly that reason.
    out = built()
    labels = {item["provider_id"]: item["label"] for item in out["labels"]}
    listed = set()
    for row in fixture_rows():
        surname = (row.get("LASTNAME") or "").strip().upper()
        if surname:
            listed.add(surname)
    assert listed, "the fixture carries no surname, so this check graded nothing"
    seen = 0
    for row in out["tables"]["provider"]:
        if labels[row["provider_id"]] != generate.UNRELATED:
            continue
        assert row["npi"] is None, row
        assert row["last_name"] not in listed, row["last_name"]
        seen += 1
    assert seen == SMALL.unrelated


def check_the_plan_refuses_an_exclusion_file_too_small_for_it():
    # The generator asking for more records than the file holds would otherwise
    # draw the same record twice and silently break the answer key.
    too_big = generate.Plan(exact_identifier=9999, name_and_birth=1, near_miss=1, unrelated=1)
    try:
        generate.generate(fixture_rows(), plan=too_big)
    except ValueError as exc:
        assert "usable identifiers" in str(exc), str(exc)
    else:
        raise AssertionError("the generator accepted a plan the file cannot supply")


def check_every_row_points_at_something_that_exists():
    out = built()
    tables = out["tables"]
    providers = {row["provider_id"] for row in tables["provider"]}
    facilities = {row["facility_id"] for row in tables["facility"]}
    applications = {row["application_id"] for row in tables["application"]}
    for row in tables["application"]:
        assert row["provider_id"] in providers, row
        assert row["facility_id"] in facilities, row
    for row in tables["license"]:
        assert row["provider_id"] in providers, row
    for row in tables["verification"]:
        assert row["application_id"] in applications, row
    for row in tables["committee_decision"]:
        assert row["application_id"] in applications, row


def check_an_application_with_no_decision_date_is_one_of_the_active_statuses():
    out = built()
    for row in out["tables"]["application"]:
        if row["decided_on"] is None:
            assert row["status"] in generate.ACTIVE_STATUSES, row
        else:
            assert row["status"] in generate.TERMINAL_STATUSES, row


def check_every_primary_key_in_every_table_is_unique():
    out = built()
    keys = {
        "provider": "provider_id",
        "facility": "facility_id",
        "application": "application_id",
        "license": "license_id",
        "verification": "verification_id",
        "committee_decision": "decision_id",
    }
    for name, column in sorted(keys.items()):
        values = [row[column] for row in out["tables"][name]]
        assert len(values) == len(set(values)), name


def check_the_tables_the_rules_cover_are_the_tables_the_generator_builds():
    out = built()
    assert sorted(out["tables"]) == sorted(catalog.TABLES), sorted(out["tables"])


def check_the_committed_catalog_passes_every_rule():
    got = catalog.check_all(manifest()["catalog"])
    firing = {name: problems for name, problems in got.items() if problems}
    assert not firing, firing


def check_the_source_database_publishes_every_table_it_holds():
    cat = manifest()["catalog"]
    assert sorted(cat) == sorted(catalog.TABLES), sorted(cat)
    for name in sorted(cat):
        assert cat[name]["in_publication"], name


def check_the_tables_whose_deletes_matter_carry_more_than_the_key():
    cat = manifest()["catalog"]
    for name in catalog.DELETE_CHANGES_AN_ANSWER:
        assert cat[name]["replica_identity"] in (catalog.FULL, catalog.INDEX), (name, cat[name])
    # And the ones that do not are left on the default rather than all of them
    # being set, because a rule every table satisfies is a rule that decided
    # nothing.
    others = [n for n in catalog.TABLES if n not in catalog.DELETE_CHANGES_AN_ANSWER]
    assert any(cat[n]["replica_identity"] == catalog.DEFAULT for n in others), cat


# A catalog written to break every rule. The same job as the broken
# configuration fixture. Without it a passing rule set is a rule set pointed at
# nothing.
BROKEN_CATALOG = {
    "application": {"replica_identity": "n", "has_primary_key": True, "in_publication": True},
    "committee_decision": {"replica_identity": "d", "has_primary_key": True, "in_publication": True},
    "facility": {"replica_identity": "d", "has_primary_key": False, "in_publication": True},
    "license": {"replica_identity": "d", "has_primary_key": True, "in_publication": False},
    "provider": {"replica_identity": "d", "has_primary_key": True, "in_publication": False},
    "spare_table_nobody_declared": {
        "replica_identity": "d",
        "has_primary_key": True,
        "in_publication": True,
    },
}


def check_every_rule_fires_on_the_broken_catalog():
    got = catalog.check_all(BROKEN_CATALOG)
    silent = sorted(name for name, problems in got.items() if not problems)
    assert not silent, silent


def check_the_broken_catalog_is_missing_a_table_and_carrying_a_spare():
    # Both directions of the coverage rule, because one of them alone passes on
    # a catalog that names a table it does not hold.
    problems = catalog.every_table_is_present(BROKEN_CATALOG)
    joined = " ".join(problems)
    assert "verification is not in the catalog answer" in joined, problems
    assert "spare_table_nobody_declared" in joined, problems


# What psql returns for the catalog query, as text. Two rows, a blank line and
# trailing whitespace, because that is the shape the real output arrives in.
CATALOG_OUTPUT = """
 provider|d|1|1
committee_decision|f|1|1

facility|d|0|0
"""


def check_the_catalog_answer_is_read_the_way_psql_returns_it():
    # Nothing else in the suite calls this. The rules are graded against the
    # committed answer, so without this the function that produces that answer
    # is the one piece of the chain nothing reads.
    asked = []

    def runner(sql):
        asked.append(sql)
        return CATALOG_OUTPUT

    got = catalog.read(runner)
    assert asked == [catalog.CATALOG_SQL], asked
    assert got == {
        "provider": {"replica_identity": "d", "has_primary_key": True, "in_publication": True},
        "committee_decision": {
            "replica_identity": "f",
            "has_primary_key": True,
            "in_publication": True,
        },
        "facility": {"replica_identity": "d", "has_primary_key": False, "in_publication": False},
    }, got


def check_a_blank_line_in_the_catalog_answer_is_not_a_table():
    # psql prints one. Without the skip the split raises and the whole
    # measurement dies on something harmless.
    got = catalog.read(lambda _sql: "\n\n  \n")
    assert got == {}, got


def check_a_zero_count_is_read_as_absent_and_not_as_present():
    # The two counts are the only numbers in the answer and both decide a
    # boolean. A comparison that accepted zero would report a table with no
    # primary key as having one, which is the rule this file exists to run.
    got = catalog.read(lambda _sql: "t|d|0|0")
    assert got["t"]["has_primary_key"] is False, got
    assert got["t"]["in_publication"] is False, got
    got = catalog.read(lambda _sql: "t|d|1|2")
    assert got["t"]["has_primary_key"] is True, got
    assert got["t"]["in_publication"] is True, got


def check_a_row_with_the_wrong_number_of_fields_is_refused():
    # Rather than silently producing a table whose identity is a count. The
    # query is in this module and so is the reader, so a mismatch means one of
    # them changed without the other.
    for line in ("t|d|1", "t|d|1|1|1"):
        try:
            catalog.read(lambda _sql, body=line: body)
        except ValueError:
            pass
        else:
            raise AssertionError("read accepted a row shaped %r" % line)


def check_the_write_rule_reports_both_reasons_a_source_stops_accepting_a_delete():
    # The rule has two arms and the broken catalog fires only one of them at a
    # time, so a mutation that disabled the second arm left the rule still
    # returning something and every check above still passing. Both arms are
    # named here.
    nothing_identity = {
        "t": {"replica_identity": "n", "has_primary_key": True, "in_publication": True}
    }
    problems = catalog.the_source_can_still_write(nothing_identity)
    assert len(problems) == 1, problems
    assert "replica identity is nothing" in problems[0], problems

    no_key = {
        "t": {"replica_identity": "d", "has_primary_key": False, "in_publication": True}
    }
    problems = catalog.the_source_can_still_write(no_key)
    assert len(problems) == 1, problems
    assert "no primary key and the default identity" in problems[0], problems

    # And the arm that must stay quiet. A table with a primary key on the
    # default identity accepts its deletes, which is measured and is why the
    # tables whose deletes do not change an answer are left there.
    fine = {
        "t": {"replica_identity": "d", "has_primary_key": True, "in_publication": True}
    }
    assert catalog.the_source_can_still_write(fine) == []

    # An unpublished table is nothing this rule has anything to say about,
    # whatever its identity. Its own rule covers it.
    unpublished = {
        "t": {"replica_identity": "n", "has_primary_key": False, "in_publication": False}
    }
    assert catalog.the_source_can_still_write(unpublished) == []


def check_a_licence_does_not_expire_before_it_was_issued():
    for row in built()["tables"]["license"]:
        assert row["expires_on"] > row["issued_on"], row


def check_a_decision_date_is_never_before_the_application_was_submitted():
    for row in built()["tables"]["application"]:
        if row["decided_on"] is not None:
            assert row["decided_on"] > row["submitted_on"], row


def check_a_verification_is_requested_no_earlier_than_the_application():
    out = built()
    submitted = {row["application_id"]: row["submitted_on"] for row in out["tables"]["application"]}
    for row in out["tables"]["verification"]:
        assert row["requested_at"][:10] >= submitted[row["application_id"]], row


def check_a_verification_with_no_completion_time_carries_no_result():
    # And the other way. A result without a completion time is a verification
    # that answered before it was done, which downstream would read as a
    # finished primary source check.
    for row in built()["tables"]["verification"]:
        if row["completed_at"] is None:
            assert row["result"] is None, row
        else:
            assert row["result"] is not None, row
            assert row["completed_at"] > row["requested_at"], row


def check_a_verification_names_a_source_the_generator_knows():
    seen = set()
    for row in built()["tables"]["verification"]:
        assert row["source"] in generate.VERIFICATION_SOURCES, row
        seen.add(row["source"])
    # And more than one, otherwise a sample of size one would pass the line
    # above while producing a workflow where every check came from one place.
    assert len(seen) > 1, seen


def check_no_application_carries_two_verifications_from_one_source():
    # A primary source check happens once per application. Two rows from one
    # source is a double count, and a recall figure later would read it as two
    # independent confirmations.
    seen = set()
    for row in built()["tables"]["verification"]:
        pair = (row["application_id"], row["source"])
        assert pair not in seen, pair
        seen.add(pair)


def check_a_committee_decision_agrees_with_the_application_it_decided():
    out = built()
    status = {row["application_id"]: row["status"] for row in out["tables"]["application"]}
    decided = set()
    for row in out["tables"]["committee_decision"]:
        app = row["application_id"]
        decided.add(app)
        assert status[app] in generate.TERMINAL_STATUSES, (row, status[app])
        if status[app] == "approved":
            assert row["decision"] == "approved", row
        elif status[app] == "denied":
            assert row["decision"] == "denied", row
        else:
            assert row["decision"] == "deferred", row
    # An application still in the workflow has not been to committee.
    for row in out["tables"]["application"]:
        if row["status"] in generate.ACTIVE_STATUSES:
            assert row["application_id"] not in decided, row


def check_only_an_approval_carries_an_effective_date():
    # A denial or a deferral with an effective date reads as a privilege that
    # started, which is the direction of error this platform exists to catch.
    for row in built()["tables"]["committee_decision"]:
        if row["decision"] == "approved":
            assert row["effective_from"] == row["meeting_on"], row
        else:
            assert row["effective_from"] is None, row
        assert row["effective_to"] is None, row


def check_a_meeting_happens_no_earlier_than_the_application():
    out = built()
    submitted = {row["application_id"]: row["submitted_on"] for row in out["tables"]["application"]}
    for row in out["tables"]["committee_decision"]:
        assert row["meeting_on"] > submitted[row["application_id"]], row


def check_every_generated_provider_is_an_individual_with_a_specialty():
    # The organisation branch of the schema has no generator behind it yet.
    # Saying so here means a later run that adds one finds this check rather
    # than discovering the gap downstream.
    for row in built()["tables"]["provider"]:
        assert row["provider_type"] == "individual", row
        assert row["primary_specialty"] in generate.SPECIALTIES, row
        assert row["business_name"] is None, row
        assert row["created_at"] == row["updated_at"], row


def check_every_facility_the_applications_point_at_is_one_of_the_declared_ones():
    out = built()
    declared = {row[0] for row in generate.FACILITIES}
    assert {row["facility_id"] for row in out["tables"]["facility"]} == declared
    used = {row["facility_id"] for row in out["tables"]["application"]}
    assert used <= declared, used
    assert len(used) > 1, used


def check_a_surname_pool_overlapping_the_exclusion_list_is_filtered():
    # The pool shipped with the generator happens to share no surname with the
    # real file, so the filtering never does anything and a mutation to it
    # survives. These two reach it by swapping the pool for one that overlaps,
    # which is the only way to exercise a guard written for a pool somebody
    # changes later.
    listed = sorted(
        {
            (row.get("LASTNAME") or "").strip().upper()
            for row in fixture_rows()
            if (row.get("LASTNAME") or "").strip()
        }
    )
    assert len(listed) >= 2, listed

    safe = "QUILLEN"
    assert safe not in listed, listed
    original = generate.SURNAMES
    try:
        generate.SURNAMES = tuple(listed) + (safe,)
        out = generate.generate(fixture_rows(), plan=SMALL, seed=3)
    finally:
        generate.SURNAMES = original

    labels = {item["provider_id"]: item["label"] for item in out["labels"]}
    surnames = {
        row["last_name"]
        for row in out["tables"]["provider"]
        if labels[row["provider_id"]] == generate.UNRELATED
    }
    assert surnames == {safe}, surnames


def check_a_surname_pool_entirely_inside_the_exclusion_list_is_refused():
    # Rather than quietly planting providers that collide with the list they
    # are supposed to be absent from, which would make a precision figure wrong
    # in the direction that looks good.
    listed = tuple(
        sorted(
            {
                (row.get("LASTNAME") or "").strip().upper()
                for row in fixture_rows()
                if (row.get("LASTNAME") or "").strip()
            }
        )
    )
    original = generate.SURNAMES
    try:
        generate.SURNAMES = listed
        generate.generate(fixture_rows(), plan=SMALL, seed=3)
    except ValueError as exc:
        assert "every surname in the pool" in str(exc), str(exc)
    else:
        raise AssertionError("the generator accepted a pool entirely inside the exclusion list")
    finally:
        generate.SURNAMES = original


def check_the_generator_accepts_rows_that_can_only_be_walked_once():
    # The readers in this repository yield. The rows are walked twice, so a
    # generator handed straight in used to produce an empty avoid list on the
    # second walk and nothing said so.
    from_iterator = generate.generate(iter(fixture_rows()), plan=SMALL, seed=11)
    from_list = generate.generate(fixture_rows(), plan=SMALL, seed=11)
    assert from_iterator == from_list


def check_the_avoid_list_covers_a_surname_no_tier_can_reach():
    # The two planting pools hold only records a tier can reach. A person
    # reachable by name and state alone is in neither, and their surname has to
    # be in the avoid list anyway.
    rows = fixture_rows()
    listed = generate.excluded_surnames(rows)
    _with_identifier, with_key = generate.exclusion_pools(rows)
    pooled = {last for last, _first, _dob in with_key}
    beyond = listed - pooled
    assert beyond, "the fixture has no surname outside the planting pools, so this graded nothing"
    for surname in sorted(beyond):
        assert surname in listed, surname
