"""Checks on the credit model, which is derived from a page and a file and never observed.

Nothing in this project has run on an account, so every figure here is a
derivation and the checks grade the derivation. The thing worth guarding is
not the arithmetic, which is three multiplications. It is that each input is
sourced, that a size nobody has a published rate for refuses rather than
guessing, and that the published bracket stays a bracket rather than
collapsing into a point estimate somebody later reads as a measurement.
"""

import json
import os

from screening import credits

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(ROOT, "measurements", "credits.json")


def manifest():
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


def check_every_sourced_fact_carries_a_quote_and_a_url():
    for key, sourced in credits.SOURCED_FACTS.items():
        assert sourced.quote, key
        assert sourced.url.startswith("https://docs.snowflake.com/"), key


def check_a_billing_fact_nobody_read_raises():
    """A rule may not rest on a default nobody looked up."""
    try:
        credits.fact("egress_per_gigabyte")
    except credits.NotSourced:
        return
    raise AssertionError("an unsourced billing fact came back with an answer")


def check_a_warehouse_size_with_no_published_rate_raises():
    try:
        credits.rate_per_hour("ENORMOUS")
    except credits.NotSourced:
        return
    raise AssertionError("a size with no published rate came back with a rate")


def check_the_rate_table_doubles_with_each_size():
    sizes = ["XSMALL", "SMALL", "MEDIUM", "LARGE", "XLARGE", "XXLARGE", "XXXLARGE", "X4LARGE", "X5LARGE", "X6LARGE"]
    rates = [credits.RATE_PER_HOUR[s] for s in sizes]
    for earlier, later in zip(rates, rates[1:]):
        assert later == earlier * 2, (earlier, later)


def check_a_second_cluster_doubles_the_ceiling():
    """Every running cluster bills at the full size rate, which is the quoted rule."""
    assert credits.ceiling_per_hour("XSMALL", 2) == 2 * credits.ceiling_per_hour("XSMALL", 1)


def check_a_warehouse_with_no_cluster_count_has_no_derivable_ceiling():
    try:
        credits.ceiling_per_hour("XSMALL", None)
    except credits.NotSourced:
        return
    raise AssertionError("a warehouse with no cluster count produced a ceiling")


def check_the_floor_is_the_minimum_times_the_rate():
    """One resumption of a SMALL warehouse is sixty seconds at two credits an hour."""
    assert abs(credits.floor_credits(1, "SMALL") - (60 * 2 / 3600.0)) < 1e-12


def check_a_cycle_that_does_no_work_still_costs_something():
    assert credits.floor_credits(1, "XSMALL") > 0


def check_no_resumption_costs_nothing():
    assert credits.floor_credits(0, "SMALL") == 0


def check_resumptions_are_bracketed_and_not_chosen():
    """The low end is one start for the whole cycle and the high end is one per stage.

    Which end a deployment sits at depends on how long each stage takes, and
    nothing here has loaded any data, so publishing a point inside the bracket
    would be a figure dressed as a measurement.
    """
    assert credits.resumption_bounds(4) == (1, 4)
    assert credits.resumption_bounds(1) == (1, 1)
    assert credits.resumption_bounds(0) == (0, 0)


def check_the_manifest_says_it_was_derived_and_not_observed():
    assert manifest()["derived_not_observed"] is True


def check_the_account_ceiling_re_derives_from_the_warehouse_rows():
    found = manifest()
    total = sum(w["ceiling_per_hour"] for w in found["warehouses"].values())
    assert total == found["account_ceiling_per_hour"], (total, found["account_ceiling_per_hour"])


def check_the_cluster_count_changes_the_account_ceiling():
    """If it did not, the multi cluster warehouse would be costed as one cluster.

    The second figure is what reading the sizes alone would give. It is in the
    manifest so that the difference is published rather than implied, because
    the comment on the reporting warehouse argues about concurrency and says
    nothing about the ceiling doubling.
    """
    found = manifest()
    assert found["account_ceiling_per_hour"] > found["account_ceiling_if_clusters_were_ignored"]


def check_every_warehouse_row_re_derives_its_own_ceiling():
    for name, w in manifest()["warehouses"].items():
        assert w["ceiling_per_hour"] == credits.rate_per_hour(w["size"]) * w["max_cluster_count"], name


def check_every_cycle_stage_is_assigned_to_something():
    found = manifest()
    assert sorted(found["stage_assignment"]) == sorted(found["cycle_stages"])
    for name, where in found["stage_assignment"].items():
        assert where["engine"], name
        assert where["why"], name


def check_a_stage_with_no_derivable_rate_says_so_rather_than_being_left_out():
    """A stage quietly dropped is how a cost model comes out low."""
    found = manifest()
    unpriced = set(found["stages_with_no_derivable_rate"])
    priced = {s for v in found["per_warehouse"].values() for s in v["stages"]}
    assert unpriced | priced == set(found["cycle_stages"]), (unpriced, priced)
    assert not (unpriced & priced), unpriced & priced


def check_snowpipe_is_recorded_as_not_on_the_rate_table():
    assert credits.fact("snowpipe_is_not_on_this_table").value is None


def check_the_published_generation_is_named():
    """Gen2 rates are in a document nobody here read, so the generation is stated."""
    assert credits.GENERATION.value == "Gen1"
    assert manifest()["sourced_facts"]["generation"]["value"] == "Gen1"


def check_the_floor_bracket_re_derives_from_the_per_warehouse_rows():
    found = manifest()
    low = round(sum(v["floor_credits_low"] for v in found["per_warehouse"].values()), 6)
    high = round(sum(v["floor_credits_high"] for v in found["per_warehouse"].values()), 6)
    assert low == found["cycle_floor_credits_low"]
    assert high == found["cycle_floor_credits_high"]


def check_the_floor_bracket_is_not_a_point():
    """Four stages on one warehouse means the high end is four times the low one."""
    found = manifest()
    assert found["cycle_floor_credits_high"] > found["cycle_floor_credits_low"]


def check_the_monitor_quota_is_not_a_literal_in_this_configuration():
    """It is a variable with no default, which is why the apply job has to pass it.

    This is recorded rather than asserted away. The one cost control in the
    configuration cannot be created unless something supplies its quota, and
    for six days the job that applies did not.
    """
    assert manifest()["monitor"]["quota_is_a_literal"] is False


def check_the_monitor_names_both_suspend_triggers():
    found = manifest()["monitor"]
    assert found["suspend_trigger"], found
    assert found["suspend_immediate_trigger"], found


def check_the_manifest_carries_no_wall_time():
    text = json.dumps(manifest())
    for word in ("elapsed", "duration", "took_ms", "seconds_elapsed"):
        assert word not in text, word
