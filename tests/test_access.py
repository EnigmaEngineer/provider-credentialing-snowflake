"""Checks on who reads what, and on the two places that rule is written down.

The design in screening/access.py is the statement of intent. The
configuration in infra/policies.tf is the enforcement. The manifest in
measurements/access.json is what applying the design to the relations
produced. Each of the three can be wrong in a way the other two would catch,
so the checks here compare them against each other rather than each against
itself.

The pair that matters most is the measured recovery against the declared one,
in both directions. A recovery the measurement found and the design does not
declare is a column reading whole that nobody meant to publish. A recovery the
design declares and the measurement never found is a rule resting on an
argument about a join rather than on a count.
"""

import json
import os

from screening import access, tfread

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INFRA = os.path.join(ROOT, "infra")
MANIFEST = os.path.join(ROOT, "measurements", "access.json")

# The table every policy body in this schema reads to decide who it lets
# through. The role names used to be an inline list in each of five bodies and
# the prose gate refused the list, which is how they ended up in one place.
EXEMPT_TABLE = "policy_exempt_role"


def manifest():
    with open(MANIFEST, encoding="utf-8") as handle:
        return json.load(handle)


def _policies(entries):
    return {b.address: b for _n, b in entries if b.kind == "resource" and b.labels
            and b.labels[0] in ("snowflake_masking_policy", "snowflake_row_access_policy")}


def _views(entries):
    return {b.address: b for _n, b in entries if b.kind == "resource" and b.labels
            and b.labels[0] == "snowflake_view"}


def check_every_relation_in_the_design_has_a_view_that_publishes_it():
    entries = tfread.read_dir(INFRA)
    names = {address.split(".")[-1] for address in _views(entries)}
    for rel in access.RELATIONS:
        assert rel.name in names, (
            "the design publishes %s and no snowflake_view resource is named for it" % rel.name
        )


def check_every_view_that_publishes_a_relation_is_in_the_design():
    # The other direction. A view in the enforcement schema that the design
    # says nothing about is a relation whose withheld set is nobody's answer.
    entries = tfread.read_dir(INFRA)
    declared = {rel.name for rel in access.RELATIONS}
    for address in _views(entries):
        name = address.split(".")[-1]
        assert name in declared, (
            "%s publishes a relation the access design does not describe" % address
        )


def check_every_withheld_column_is_attached_to_a_masking_policy():
    """A column the design withholds and the configuration leaves alone.

    The count is what this compares. The reader returns the policy references
    a view makes and how many column blocks it has, and a view withholding
    four columns with three column blocks has one reading whole.
    """
    entries = tfread.read_dir(INFRA)
    views = _views(entries)
    for rel in access.RELATIONS:
        role = access.role("SCREENING_ANALYST")
        withheld = access.withheld_from(role, rel)
        if not withheld:
            continue
        address = "snowflake_view.%s" % rel.name
        assert address in views, address
        got = views[address].count_nested("column")
        assert got >= len(withheld), (
            "%s withholds %d columns from the analyst and the view has %d column blocks"
            % (rel.name, len(withheld), got)
        )


def check_every_conditional_column_is_attached_with_its_deciding_column():
    entries = tfread.read_dir(INFRA)
    views = _views(entries)
    role = access.role("SCREENING_ANALYST")
    for rel in access.RELATIONS:
        conditional = access.conditionally_withheld_from(role, rel)
        address = "snowflake_view.%s" % rel.name
        if not conditional:
            continue
        got = views[address].count_nested_arg("using")
        assert got >= len(conditional), (
            "%s has %d conditional columns and the view sets using %d times"
            % (rel.name, len(conditional), got)
        )


def check_every_policy_body_reads_the_exempt_list_and_names_no_role_inline():
    """A Snowflake policy is one body for every reader, so the body is the list.

    This is not the BigQuery union shape. A masking policy on a column applies
    to every role that reads the column, and the body decides per role. So a
    role left out of a body is masked, and a role left out of the row access
    policy body reads whatever the predicate gives it rather than nothing.
    Either way the omission is the grant or the refusal, which is the
    2026-11-01 rule, and the body is where it has to be read.

    What this asserts is that the list is read from one place. A role name
    written into a body is a sixth copy of a fact that already has a home, and
    the way that goes wrong is a role added to four bodies out of five.
    """
    bodies = 0
    for name in sorted(os.listdir(INFRA)):
        if not name.endswith(".tf"):
            continue
        with open(os.path.join(INFRA, name), encoding="utf-8") as handle:
            text = handle.read()
        if "snowflake_masking_policy" not in text and "snowflake_row_access_policy" not in text:
            continue
        bodies += 1
        assert EXEMPT_TABLE in text, (
            "%s declares policies and never reads %s, so each body carries its own "
            "idea of who is exempt" % (name, EXEMPT_TABLE)
        )
        for role in (r.name for r in access.ROLES):
            assert "'%s'" % role not in text, (
                "%s writes %s into a policy body as a literal, and the exempt list is a "
                "table for exactly that reason" % (name, role)
            )
    assert bodies == 1, bodies


def check_the_reviewer_is_exempt_from_the_masks_and_not_from_the_rows():
    """The one role whose two answers go opposite ways.

    A reviewer decides whether this provider is that excluded person, so they
    read the identity whole. They have no business in another facility, so
    they read fewer rows than anybody. A design that treated exemption as one
    switch would get one of the two wrong.
    """
    reviewer = access.role("SCREENING_REVIEWER")
    assert set(reviewer.sees_whole) == set(access.QUANTITIES), reviewer.sees_whole
    assert reviewer.reads_every_row is False
    analyst = access.role("SCREENING_ANALYST")
    assert analyst.sees_whole == ()
    assert analyst.reads_every_row is True


def check_the_loader_reads_nothing_in_the_enforcement_layer():
    loader = access.role("SCREENING_LOADER")
    assert loader.reads == (), loader.reads


def check_every_measured_recovery_is_declared_in_the_design():
    """The direction that catches a leak.

    A column the measurement found gives back a withheld value, and the design
    does not say it can, is a column that reads whole for a role nobody meant
    to publish it to.
    """
    got = manifest()
    scale = got.get("recovery_at_full_scale")
    if scale is None:
        raise AssertionError(
            "the manifest has no full scale arm, so this check grades nothing. "
            "Run scripts/measure_access.py where data/work exists."
        )
    declared = set()
    for rel in access.RELATIONS:
        for rec in rel.recoveries:
            if rec.is_conditional:
                for value in rec.holds_when:
                    declared.add((value, rec.measured_as))
    for tier, counts in scale["per_tier"].items():
        rank = access.match_rank(tier)
        for key, count in counts.items():
            if key == "pairs" or count == 0:
                continue
            assert (rank, key) in declared, (
                "%s on %s was measured %d times and the design declares no recovery for it"
                % (key, tier, count)
            )


def check_every_declared_recovery_was_measured():
    """And the direction that catches a rule resting on an argument.

    The third tier recovery was missing from the design until the measurement
    counted it. This check is what would have failed if the measurement had
    been written and the design left alone, and it is the half that stops a
    conditional policy being written from a join condition somebody read.
    """
    got = manifest()
    scale = got.get("recovery_at_full_scale")
    assert scale is not None, "no full scale arm in the manifest"
    measured = set()
    for tier, counts in scale["per_tier"].items():
        rank = access.match_rank(tier)
        for key, count in counts.items():
            if key != "pairs" and count > 0:
                measured.add((rank, key))
    for rel in access.RELATIONS:
        for rec in rel.recoveries:
            if not rec.is_conditional:
                continue
            for value in rec.holds_when:
                assert (value, rec.measured_as) in measured, (
                    "the design declares %s recovers %s at tier rank %d and the measurement "
                    "never counted one" % (rec.columns, rec.quantity, value)
                )


def check_every_pair_a_tier_formed_gives_back_what_the_mask_would_hide():
    """The figure the day turned on, asserted rather than quoted.

    Every pair, not most of them. The join condition is an equality on the
    column the mask would hide, so the published column is the hidden value on
    every row the tier reached. A number below the pair count would mean the
    equality does not hold somewhere and the claim needs rewriting.
    """
    scale = manifest()["recovery_at_full_scale"]
    per_tier = scale["per_tier"]
    recovered = {
        "tier1_identifier": "matched_npi_recovers_the_identifier",
        "tier2_name_and_dob": "matched_fallback_key_recovers_the_identity",
        "tier3_name_state": "matched_fallback_key_recovers_the_name_only",
    }
    for tier, key in recovered.items():
        assert tier in per_tier, tier
        pairs = per_tier[tier]["pairs"]
        assert pairs > 0, tier
        assert per_tier[tier].get(key) == pairs, (
            "%s: %d of %d pairs recover the withheld value, and the claim is every one"
            % (tier, per_tier[tier].get(key, 0), pairs)
        )


def check_the_manifest_names_every_section_it_holds():
    """Both directions over the measured list, per the 2026-11-09 rule."""
    got = manifest()
    named = set(got["measured"])
    sections = {k for k in got if k not in ("measured", "unscoped_rows_go_to_every_reviewer")}
    assert named == sections, (sorted(named - sections), sorted(sections - named))


def check_every_role_in_the_design_is_in_the_manifest():
    got = manifest()
    assert set(got["roles"]) == {r.name for r in access.ROLES}


def check_the_reviewer_reads_fewer_rows_than_the_analyst():
    """The row filter doing something, measured rather than configured.

    A row access policy that let everything through would pass every check
    about its own configuration. This one compares the counts.
    """
    got = manifest()["roles"]
    for name in ("review_queue", "match_candidate"):
        analyst = got["SCREENING_ANALYST"]["relations"][name]
        reviewer = got["SCREENING_REVIEWER"]["relations"][name]
        assert analyst["rows_this_role_reads"] == analyst["rows_in_the_relation"]
        assert reviewer["rows_this_role_reads"] < analyst["rows_this_role_reads"], (
            "%s: the reviewer reads %d of %d rows, which is the whole relation, so the "
            "policy is not filtering" % (name, reviewer["rows_this_role_reads"],
                                         analyst["rows_in_the_relation"])
        )


def check_the_unscoped_bucket_is_counted_rather_than_discovered():
    """A provider with no facility reaches every reviewer, and the count is published.

    The decision is in screening/access.py with the reason. What this asserts
    is that the number is in the manifest, because a bucket whose size nobody
    publishes is one somebody finds by noticing duplicated work.
    """
    got = manifest()
    assert got["unscoped_rows_go_to_every_reviewer"] is True
    reviewer = got["roles"]["SCREENING_REVIEWER"]["relations"]
    for name in ("review_queue", "match_candidate"):
        assert "unscoped_rows_reached" in reviewer[name], name


# The two arms against each other. Added after the Python arm came back with
# four candidate rows where the warehouse has five, which is the whole reason
# the warehouse arm exists.

WAREHOUSE = os.path.join(ROOT, "measurements", "access_warehouse.json")


def warehouse():
    with open(WAREHOUSE, encoding="utf-8") as handle:
        return json.load(handle)


def python_arm():
    """The relations the Python builder produces, in the warehouse's shape.

    Imported here rather than at the top of the module because the script
    lives in scripts/ and the suite is not a package that reaches it. The
    comparison needs the same code the measurement ran, not a copy of it.
    """
    import importlib.util

    path = os.path.join(ROOT, "scripts", "measure_access.py")
    spec = importlib.util.spec_from_file_location("measure_access", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_both_arms_agree_on_every_row_of_every_relation():
    """Pair grained, which is the finest grain either arm produces.

    A count comparison would have passed on the day the Python arm was wrong,
    because it was wrong by one row out of five and the queue agreed. The
    comparison is over the columns the warehouse manifest names rather than
    over every column, and the manifest names them so this check does not
    carry its own list.
    """
    theirs = warehouse()
    mine = python_arm().seed_relations()
    for name, got in sorted(theirs["relations"].items()):
        keys = theirs["compared_columns"][name]
        rows = sorted(
            [("" if r.get(k) is None else str(r.get(k))) for k in keys] for r in mine[name]
        )
        assert rows == got["compared"], (
            name,
            [r for r in rows if r not in got["compared"]],
            [r for r in got["compared"] if r not in rows],
        )


def check_the_warehouse_relations_carry_the_columns_the_design_names():
    """Both directions, from the warehouse's own column list.

    A column the design does not know about is in no recovery set, so it reads
    whole for every role and nothing complains. A column the design names and
    the view does not have is a mask attached to nothing.
    """
    theirs = warehouse()
    for name, got in sorted(theirs["relations"].items()):
        assert got["columns_the_design_does_not_know"] == [], (name, got)
        assert got["columns_the_design_expects_and_the_view_lacks"] == [], (name, got)


def check_a_provider_can_appear_at_more_than_one_tier_in_the_candidate_relation():
    """The property the Python arm did not have, pinned so it cannot go back.

    One provider reached by two tiers is what separates the candidate relation
    from the queue. If this fixture ever stops carrying one, the comparison
    above passes on two arms that are both the queue.
    """
    theirs = warehouse()
    keys = theirs["compared_columns"]["match_candidate"]
    rows = theirs["relations"]["match_candidate"]["compared"]
    at = keys.index("provider_id")
    rank = keys.index("tier_rank")
    seen = {}
    for row in rows:
        seen.setdefault(row[at], set()).add(row[rank])
    assert any(len(v) > 1 for v in seen.values()), seen


def check_the_warehouse_arm_names_the_engine_that_produced_it():
    theirs = warehouse()
    assert theirs["engine"].startswith("duckdb "), theirs["engine"]
    assert set(theirs["measured"]) == {
        k for k in theirs if k not in ("engine", "measured")
    }


# The design's own functions, with the answers written out.
#
# Added after a mutation pass on screening/access.py came back 16 killed and
# 15 survived. Every survivor was in a predicate the suite only ever reached
# through measurements/access.json, and a committed manifest cannot disagree
# with code that has been changed since it was written. The pattern that keeps
# the suite runnable on a clean clone is a script writing a manifest and the
# checks reading it, and the cost of that pattern is exactly this: the logic
# that produced the file is ungraded unless something calls it.


def check_the_analyst_withholds_the_four_queue_columns_and_no_others():
    role = access.role("SCREENING_ANALYST")
    got = access.withheld_from(role, access.relation("review_queue"))
    assert got == {"npi", "last_name", "first_name", "date_of_birth"}, got


def check_the_analyst_withholds_both_matched_columns_and_no_others():
    role = access.role("SCREENING_ANALYST")
    got = access.withheld_from(role, access.relation("match_candidate"))
    assert got == {"matched_npi", "matched_fallback_key"}, got


def check_a_role_that_sees_both_quantities_withholds_nothing():
    for name in ("SCREENING_TRANSFORMER", "SCREENING_REVIEWER"):
        role = access.role(name)
        for rel in access.RELATIONS:
            assert access.withheld_from(role, rel) == set(), (name, rel.name)


def check_the_conditional_columns_carry_the_ranks_the_tiers_publish():
    """The union, and the deciding column, both written out.

    matched_npi at the first tier and matched_fallback_key at the second and
    the third. The third is the one the measurement added, so an answer of
    just the second here is the design before it was corrected.
    """
    role = access.role("SCREENING_ANALYST")
    got = access.conditionally_withheld_from(role, access.relation("match_candidate"))
    assert got == {
        "matched_npi": ("tier_rank", (1,)),
        "matched_fallback_key": ("tier_rank", (2, 3)),
    }, got


def check_the_queue_columns_are_withheld_unconditionally():
    # A column on the queue is the provider's own value on every row, so
    # nothing about the row decides. A conditional answer here would mean a
    # policy written with a using clause it does not need.
    role = access.role("SCREENING_ANALYST")
    got = access.conditionally_withheld_from(role, access.relation("review_queue"))
    assert got == {}, got


def check_visible_columns_is_the_relation_minus_the_withheld_ones_in_order():
    role = access.role("SCREENING_ANALYST")
    rel = access.relation("review_queue")
    got = access.visible_columns(role, rel)
    assert got == (
        "provider_id",
        "npi_is_absent",
        "tier",
        "tier_rank",
        "records_matched",
        "distinct_records_matched",
        "cleared_without_review",
        "facility_id",
    ), got
    # The order is the relation's own, because a reader comparing two roles
    # side by side is comparing lists.
    assert list(got) == [c for c in rel.columns if c in got]


def check_a_row_in_an_assigned_facility_reaches_the_reviewer():
    reviewer = access.role("SCREENING_REVIEWER")
    rel = access.relation("review_queue")
    assert access.row_is_visible(reviewer, rel, {"facility_id": 1}) is True


def check_a_row_in_another_facility_does_not_reach_the_reviewer():
    reviewer = access.role("SCREENING_REVIEWER")
    rel = access.relation("review_queue")
    assert access.row_is_visible(reviewer, rel, {"facility_id": 2}) is False
    assert access.row_is_visible(reviewer, rel, {"facility_id": 99}) is False


def check_a_row_with_no_facility_reaches_every_reviewer():
    """The decision, asserted rather than left in a comment.

    A provider with no live application has no facility. The cheap body sends
    them to nobody and this one sends them to everybody, and the difference is
    a provider screened against nothing who is never looked at.
    """
    reviewer = access.role("SCREENING_REVIEWER")
    for rel in access.RELATIONS:
        assert access.row_is_visible(reviewer, rel, {"facility_id": None}) is True
    assert access.UNSCOPED_ROWS_GO_TO_EVERY_REVIEWER is True


def check_a_role_that_reads_every_row_is_not_filtered_by_the_facility():
    for name in ("SCREENING_ANALYST", "SCREENING_TRANSFORMER"):
        role = access.role(name)
        for rel in access.RELATIONS:
            for value in (1, 2, 99, None):
                assert access.row_is_visible(role, rel, {"facility_id": value}) is True, (
                    name,
                    rel.name,
                    value,
                )


def check_the_rank_of_each_tier_comes_from_the_matching_module():
    # The rank a conditional policy switches on has to be the number the model
    # publishes, so this reads the tier order rather than a copy of it.
    from screening import match

    for expected, tier in enumerate(match.TIER_ORDER, start=1):
        assert access.match_rank(tier) == expected, tier


def check_asking_for_a_relation_or_a_role_that_does_not_exist_raises():
    # Returning None would make a typo in a check read as a relation with no
    # columns and no recoveries, which passes everything.
    for fn in (access.relation, access.role):
        try:
            fn("nothing_by_this_name")
        except KeyError:
            continue
        raise AssertionError("%s returned something for a name that is not in the design" % fn)


def check_a_column_decided_by_two_different_columns_is_refused():
    """One policy takes one deciding column, so the design cannot hold two.

    Built here rather than planted in the real design, because the real
    design is the thing being graded.
    """
    rel = access.Relation(
        name="made_up",
        columns=("a", "b", "c"),
        recoveries=(
            access.Recovery(access.PROVIDER_IDENTITY, ("a",), decided_by="b", holds_when=(1,)),
            access.Recovery(access.PROVIDER_IDENTITY, ("a",), decided_by="c", holds_when=(2,)),
        ),
    )
    try:
        access.conditionally_withheld_from(access.role("SCREENING_ANALYST"), rel)
    except ValueError:
        return
    raise AssertionError("two deciding columns for one masked column was accepted")


def check_a_partial_recovery_withholds_the_column_like_a_whole_one():
    whole = access.Recovery(access.PROVIDER_IDENTITY, ("k",), decided_by="r", holds_when=(2,))
    partial = access.Recovery(
        access.PROVIDER_IDENTITY, ("k",), decided_by="r", holds_when=(3,), whole=False
    )
    rel = access.Relation(name="made_up", columns=("k", "r"), recoveries=(partial,))
    role = access.role("SCREENING_ANALYST")
    assert access.withheld_from(role, rel) == {"k"}
    # And the two are counted separately, because the measurement counts them
    # separately and the comparison is between those two sets.
    assert whole.measured_as != partial.measured_as
    assert partial.measured_as.endswith("recovers_the_name_only")


# The last four survivors of the mutation pass, and neither of the two causes
# was a missing assertion about an answer.
#
# Three were frozen=True on the three design dataclasses. Nothing in the
# design assigns to one, so flipping the flag changes no answer and no check
# about an answer can kill it. The guard is still worth having, because these
# objects are read by every check in this module and one that mutated a
# Relation in place would change the design for everything after it. So the
# guard gets graded directly rather than removed or left as a survivor.
#
# The fourth was the quantity filter in recoveries_for, and that one was a
# real gap. Every caller loops over both quantities, and no role in the
# design is exempt from one and not the other, so the filter had nothing to
# do and the mutant was equivalent. A role with a partial exemption is a real
# thing to want, so the answer is a case that needs the filter rather than
# deleting it.


def check_the_design_objects_refuse_assignment():
    rec = access.Recovery(access.PROVIDER_IDENTITY, ("a",))
    rel = access.relation("review_queue")
    role = access.role("SCREENING_ANALYST")
    for obj, attr, value in (
        (rec, "quantity", access.PROVIDER_IDENTIFIER),
        (rel, "scope_column", "something_else"),
        (role, "sees_whole", access.QUANTITIES),
    ):
        try:
            setattr(obj, attr, value)
        except Exception:
            continue
        raise AssertionError(
            "%s let %s be reassigned, so one check can change the design for the rest"
            % (type(obj).__name__, attr)
        )


def check_recoveries_for_returns_only_the_quantity_it_was_asked_about():
    rel = access.relation("match_candidate")
    for quantity in access.QUANTITIES:
        got = rel.recoveries_for(quantity)
        assert got, quantity
        assert all(r.quantity == quantity for r in got), [r.quantity for r in got]
    # And the two sets are disjoint, which is what makes the question worth
    # asking at all.
    first = set(rel.recoveries_for(access.PROVIDER_IDENTIFIER))
    second = set(rel.recoveries_for(access.PROVIDER_IDENTITY))
    assert first and second and not (first & second)


def check_a_role_exempt_from_one_quantity_still_withholds_the_other():
    """A partial exemption, which no role in the design currently holds.

    This is the case the filter in recoveries_for exists for. Somebody who
    may read an identifier and not a name is an ordinary thing to want, and
    without a case like this the filter is dead code that reads as a
    precaution.
    """
    partial = access.Role(
        name="MADE_UP_PARTIAL",
        reads=("match_candidate",),
        sees_whole=(access.PROVIDER_IDENTIFIER,),
    )
    rel = access.relation("match_candidate")
    got = access.withheld_from(partial, rel)
    assert got == {"matched_fallback_key"}, got
    conditional = access.conditionally_withheld_from(partial, rel)
    assert conditional == {"matched_fallback_key": ("tier_rank", (2, 3))}, conditional
    # The other way round, so neither quantity is the one that happens to work.
    other = access.Role(
        name="MADE_UP_OTHER",
        reads=("match_candidate",),
        sees_whole=(access.PROVIDER_IDENTITY,),
    )
    assert access.withheld_from(other, rel) == {"matched_npi"}
