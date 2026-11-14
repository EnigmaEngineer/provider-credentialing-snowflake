"""What the snapshots watch, read back out of the matcher rather than listed here.

A snapshot's column list is a claim about which fields can change an answer. A
tier that starts reading a new field and a snapshot that does not watch it is a
pair that nothing complains about: both halves work, every check passes, and
the attribute history simply stops covering the thing the match was made on.

So the list is derived. These checks read the three tier functions in
screening/match.py, collect the provider columns they actually ask for, and
compare that set against the configuration in the snapshot file.
"""

import ast
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SNAPSHOTS = os.path.join(ROOT, "transform", "snapshots")
MATCH = os.path.join(ROOT, "screening", "match.py")

# The functions that read a provider row. One per tier, which is the property
# this derivation rests on.
TIER_FUNCTIONS = ("provider_identifier", "provider_name_and_dob", "provider_name_and_state")

PROVIDER_ARM = "provider_attribute.sql"
TIMESTAMP_ARM = "provider_attribute_by_timestamp.sql"
LICENCE = "license_attribute.sql"


def source(name):
    with open(os.path.join(SNAPSHOTS, name), encoding="utf-8") as fh:
        return fh.read()


def config_value(text, key):
    """The value of one key in the snapshot's config call."""
    found = re.search(key + r"\s*=\s*'([^']+)'", text)
    return found.group(1) if found else None


def watched_columns(text):
    """The check_cols list the snapshot configures.

    Not named for the key it reads. The runner collects every callable whose
    name starts with check_, so a helper spelled that way is collected as a
    check and fails on its own arguments.
    """
    found = re.search(r"check_cols\s*=\s*\[([^\]]*)\]", text)
    assert found, "the snapshot states no check_cols"
    return sorted(re.findall(r"'([^']+)'", found.group(1)))


def columns_the_tiers_read():
    """Every provider column the three tier functions ask for, from the source."""
    tree = ast.parse(open(MATCH, encoding="utf-8").read())
    wanted = set()
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in TIER_FUNCTIONS:
            continue
        seen.add(node.name)
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if not isinstance(func, ast.Attribute) or func.attr != "get":
                continue
            if not isinstance(func.value, ast.Name) or func.value.id != "provider":
                continue
            if call.args and isinstance(call.args[0], ast.Constant):
                wanted.add(call.args[0].value)
    missing = sorted(set(TIER_FUNCTIONS) - seen)
    assert not missing, "the matcher no longer defines %r, so this derivation is stale" % missing
    assert wanted, "no provider column was found, so this check graded nothing"
    return sorted(wanted)


def check_the_provider_snapshot_watches_every_column_a_tier_reads():
    assert watched_columns(source(PROVIDER_ARM)) == columns_the_tiers_read(), (
        watched_columns(source(PROVIDER_ARM)),
        columns_the_tiers_read(),
    )


def check_the_provider_snapshot_watches_nothing_a_tier_cannot_read():
    # The other direction. A column in the list that no tier reads produces a
    # version for a change that cannot move an answer, which is history nobody
    # can act on and the specific complaint against the control arm below.
    extra = sorted(set(watched_columns(source(PROVIDER_ARM))) - set(columns_the_tiers_read()))
    assert not extra, extra


def check_the_two_provider_arms_ask_different_questions():
    # The control arm is only a control while it uses the other strategy. If
    # both end up on check the comparison in the measurement compares an arm
    # with itself and reports agreement.
    assert config_value(source(PROVIDER_ARM), "strategy") == "check"
    assert config_value(source(TIMESTAMP_ARM), "strategy") == "timestamp"
    assert config_value(source(TIMESTAMP_ARM), "updated_at") == "updated_at"


def check_the_licence_snapshot_watches_the_state_the_third_tier_reads():
    # The state is the one matched field that does not live on the provider, so
    # the derivation above cannot reach it and this says it directly.
    assert "state" in watched_columns(source(LICENCE))


def check_both_snapshots_the_platform_reads_close_a_version_on_a_hard_delete():
    # A deleted row is filtered out by the staging model, so without this its
    # last version stays open and reads as the current state of somebody who
    # has left the source. The control arm is excluded because it exists to
    # show what the other strategy does and nothing reads it.
    for name in (PROVIDER_ARM, LICENCE):
        assert config_value(source(name), "hard_deletes") == "invalidate", name


def check_every_snapshot_reads_a_staging_model_rather_than_the_raw_table():
    # Deliberate, and it has a cost worth knowing. Snapshotting the raw table
    # would record a version for padding appearing around an identifier, which
    # is not a change any tier can see. Snapshotting the cleaned column means
    # the snapshot depends on the staging layer, so a cycle cannot run the
    # snapshots before the models that feed them.
    for name in sorted(os.listdir(SNAPSHOTS)):
        if not name.endswith(".sql"):
            continue
        text = source(name)
        refs = re.findall(r"ref\(\s*'([^']+)'\s*\)", text)
        assert refs, "%s refs no model" % name
        for target in refs:
            assert target.startswith("stg_"), (name, target)
            model = os.path.join(ROOT, "transform", "models", "staging", target + ".sql")
            assert os.path.exists(model), (name, target)
        assert "source(" not in text, name
