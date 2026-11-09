"""Grade the configuration reader against an independent parser.

`screening/tfread.py` is hand written, which is a fair thing to object to. It
exists because the rules it feeds have to run on a clone with no cloud account,
so a plan is not available and the file is all there is. What makes it
defensible is this module rather than the reader itself.

The comparison is direction explicit, because the two do not produce the same
shape. tfread pools nested block names across every depth, which is what the
rule about credentials needs, since an inline key would be written one level
in. So the real parser's view of the top level is the authority on what is at
the top level, and tfread has to cover all of it.
"""

import os

from screening import tfread

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INFRA = os.path.join(ROOT, "infra")
BAD = os.path.join(HERE, "fixtures", "infra_bad")


def load_hcl2():
    try:
        import hcl2
    except ImportError as exc:  # pragma: no cover
        # Not a skip. A check that goes quiet when its dependency is absent is
        # a check that reports clean on a machine that cannot run it.
        raise AssertionError(
            "this check needs the parser in requirements-dev.txt: %s" % exc
        ) from None
    return hcl2


def independent_reading(path):
    hcl2 = load_hcl2()
    out = {}
    for name in sorted(os.listdir(path)):
        if not name.endswith(".tf"):
            continue
        with open(os.path.join(path, name), encoding="utf-8") as fh:
            doc = hcl2.load(fh)
        for res in doc.get("resource", []):
            for kind, bodies in res.items():
                for label, body in bodies.items():
                    out["%s.%s" % (kind, label)] = set(body)
    return out


def my_reading(path):
    return {
        b.label: b
        for _name, b in tfread.read_dir(path)
        if b.kind == "resource"
    }


def check_both_readers_find_the_same_resources():
    for path in (INFRA, BAD):
        mine = my_reading(path)
        theirs = independent_reading(path)
        assert set(mine) == set(theirs), (
            path,
            sorted(set(mine) - set(theirs)),
            sorted(set(theirs) - set(mine)),
        )
        assert mine, path


def check_every_top_level_name_the_parser_finds_is_covered_by_the_reader():
    # The direction that matters. A name the parser sees and the reader does
    # not is a name no rule can be written about.
    for path in (INFRA, BAD):
        mine = my_reading(path)
        theirs = independent_reading(path)
        for label, names in theirs.items():
            covered = mine[label].args | mine[label].nested
            missing = sorted(names - covered)
            assert not missing, (path, label, missing)


def check_every_argument_the_reader_reports_is_one_the_parser_sees():
    # The other direction, on arguments only. Nested block names are pooled by
    # the reader on purpose, so they are excluded from this comparison and the
    # check above is what covers them.
    for path in (INFRA, BAD):
        mine = my_reading(path)
        theirs = independent_reading(path)
        for label, block in mine.items():
            extra = sorted(block.args - theirs[label])
            assert not extra, (path, label, extra)


def check_the_pooling_the_reader_does_is_the_only_difference():
    # Named rather than left as a surprise. The reader reports a block nested
    # two levels in at the top of its nested set, and this is the one place
    # that shows up in the configuration as written.
    mine = my_reading(INFRA)
    theirs = independent_reading(INFRA)
    pooled = {}
    for label, block in mine.items():
        deeper = sorted((block.args | block.nested) - theirs[label])
        if deeper:
            pooled[label] = deeper
    assert pooled == {
        "snowflake_grant_privileges_to_account_role.transformer_registry_select": ["future"]
    }, pooled


def check_the_parser_agrees_the_broken_fixture_is_missing_what_the_rules_want():
    # The rules fire on the fixture. This says they fire because the arguments
    # really are absent, read by something that did not write them.
    theirs = independent_reading(BAD)
    assert "auto_suspend" not in theirs["snowflake_warehouse.unbounded"]
    assert theirs["snowflake_resource_monitor.toothless"] == {"name"}
    assert "rsa_public_key" not in theirs["snowflake_service_user.password_please"]
    assert "auto_ingest" not in theirs["snowflake_pipe.manual"]
    assert "privileges" not in theirs["snowflake_grant_privileges_to_account_role.silent"]
