"""The replication configuration, graded on what it does not say.

Three layers and they are not the same strength. The rules read argument names
out of this repository's own reader. One check reads the same files with an
independent parser and compares. And two checks compare a name in the
configuration against a name in the source schema, which no single file can
state about itself.
"""

import os
import re

from credentialing import catalog, ftrules
from screening import tfread

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INFRA = os.path.join(ROOT, "infra")
BAD = os.path.join(HERE, "fixtures", "fivetran_bad")
SCHEMA = os.path.join(ROOT, "credentialing", "schema.sql")
CONNECTOR = os.path.join(INFRA, "fivetran.tf")


def schema_sql():
    with open(SCHEMA, encoding="utf-8") as fh:
        return fh.read()


def connector_tf():
    with open(CONNECTOR, encoding="utf-8") as fh:
        return fh.read()


def check_the_real_configuration_passes_every_rule():
    got = ftrules.check_all(INFRA)
    firing = {name: problems for name, problems in got.items() if problems}
    assert not firing, firing


def check_every_rule_fires_on_the_broken_configuration():
    got = ftrules.check_all(BAD)
    silent = sorted(name for name, problems in got.items() if not problems)
    assert not silent, silent


def check_the_rule_set_is_not_empty_and_every_rule_is_in_it():
    # A rule defined and left out of RULES runs nowhere and reads like coverage.
    defined = {
        name
        for name in dir(ftrules)
        if not name.startswith("_") and callable(getattr(ftrules, name))
    }
    defined -= {"check_all", "tfread"}
    listed = {rule.__name__ for rule in ftrules.RULES}
    assert listed, "the rule set is empty"
    assert defined == listed, sorted(defined ^ listed)


def check_the_untyped_connector_resource_is_absent_from_this_configuration():
    # The rule above says so by reading names. This says it about the text,
    # because the reason is worth stating where somebody adding a resource will
    # look.
    #
    # Read with the comments stripped. The file explains in a comment why it
    # does not use that resource, and a check over the raw text fails on the
    # explanation. The sentence is correct and the rule's subject is the code.
    body = tfread.strip_comments(connector_tf())
    assert ftrules.UNGRADEABLE_CONNECTOR not in body
    assert ftrules.TYPED_CONNECTOR in body


def check_the_publication_the_connector_reads_is_the_one_the_schema_creates():
    # A typo here means the connector is pointed at a publication that does not
    # exist, and nothing in either file can see it.
    created = re.findall(r"CREATE PUBLICATION\s+([a-z_][a-z0-9_]*)", schema_sql())
    assert len(created) == 1, created
    named = re.findall(r'publication_name\s*=\s*"([^"]+)"', connector_tf())
    assert named == created, (named, created)


def check_the_update_method_is_the_one_that_reads_the_log():
    # The other supported value cannot see a row that appeared and went between
    # two syncs, which for a screening platform is a provider who was approved
    # and removed in the same month.
    named = re.findall(r'update_method\s*=\s*"([^"]+)"', connector_tf())
    assert named == ["WAL_PGOUTPUT"], named


def check_the_connector_replicates_every_table_the_source_holds():
    # Under the blocking change handling a table absent from the configuration
    # never replicates, and every model over it returns no rows rather than
    # failing. Both directions, because a configuration naming a table the
    # source does not hold is a different mistake.
    body = connector_tf()
    block = body[body.index("fivetran_connector_schema_config") :]
    named = set(re.findall(r'name\s*=\s*"([a-z_][a-z0-9_]*)"', block))
    named.discard("credentialing")
    expected = set(catalog.TABLES)
    assert named == expected, (sorted(named - expected), sorted(expected - named))


def check_the_change_handling_blocks_rather_than_allows():
    named = re.findall(r'schema_change_handling\s*=\s*"([^"]+)"', connector_tf())
    assert named == ["BLOCK_ALL"], named


def check_the_configuration_names_no_credential_value():
    # The rule reads argument names. This reads the file for a value that looks
    # like a key, because an argument named something else can still hold one.
    body = connector_tf()
    assert "BEGIN PRIVATE KEY" not in body
    assert "BEGIN RSA PRIVATE KEY" not in body


def check_the_broken_fixture_is_not_wired_into_anything():
    # It exists to be refused. A fixture that something deploys from is a
    # different kind of file.
    for name in sorted(os.listdir(INFRA)):
        with open(os.path.join(INFRA, name), encoding="utf-8") as fh:
            assert "fivetran_bad" not in fh.read(), name
