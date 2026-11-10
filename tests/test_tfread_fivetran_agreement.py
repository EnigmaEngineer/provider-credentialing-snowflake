"""The configuration reader, graded against an independent parser on these files.

The reader in this repository covers the subset of the language this repository
writes. The only honest way to know it reads the replication configuration
correctly is to read the same files with a parser somebody else wrote and
compare.

These checks fail rather than skip when the parser is absent. A check that goes
quiet without its dependency reports clean on a machine that cannot run it.
"""

import os

from credentialing import ftrules
from screening import tfread

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONNECTOR = os.path.join(ROOT, "infra", "fivetran.tf")

MISSING = (
    "python-hcl2 is not installed. It is in requirements-dev.txt and these "
    "checks fail rather than skip without it."
)


def parsed():
    try:
        import hcl2
    except ImportError as exc:
        raise AssertionError(MISSING) from exc
    with open(CONNECTOR, encoding="utf-8") as fh:
        return hcl2.load(fh)


def ours():
    return tfread.read_dir(os.path.dirname(CONNECTOR))


def _parser_resources(doc):
    out = {}
    for item in doc.get("resource", []):
        for kind, bodies in item.items():
            for name, body in bodies.items():
                out[(kind, name)] = body
    return out


def check_both_readings_find_the_same_replication_resources():
    theirs = {
        (kind, name)
        for kind, name in _parser_resources(parsed())
    }
    mine = {
        (b.labels[0], b.labels[1])
        for _f, b in ours()
        if b.kind == "resource" and len(b.labels) == 2 and b.labels[0].startswith("fivetran_")
    }
    assert mine == theirs, (sorted(mine - theirs), sorted(theirs - mine))


def check_the_update_method_the_parser_reads_is_the_one_the_rules_assume():
    theirs = _parser_resources(parsed())
    body = theirs[(ftrules.TYPED_CONNECTOR, "credentialing")]
    config = body["config"]
    config = config[0] if isinstance(config, list) else config
    assert config["update_method"] == "WAL_PGOUTPUT", config["update_method"]
    assert config["publication_name"] == "credentialing_pub", config["publication_name"]


def check_every_argument_our_reader_reports_is_one_the_parser_sees():
    theirs = _parser_resources(parsed())
    body = theirs[(ftrules.TYPED_CONNECTOR, "credentialing")]
    config = body["config"]
    config = config[0] if isinstance(config, list) else config
    seen = set(config) | set(body)
    ours_block = [
        b
        for _f, b in ours()
        if b.kind == "resource" and tuple(b.labels[:2]) == (ftrules.TYPED_CONNECTOR, "credentialing")
    ]
    assert len(ours_block) == 1, ours_block
    reported = ours_block[0].args | ours_block[0].nested_args
    # destination_schema is a nested block of its own and its argument pools
    # into the same set, which is deliberate and is the one difference pinned
    # by name rather than left to be discovered.
    reported -= {"prefix"}
    unknown = sorted(reported - seen)
    assert not unknown, unknown
