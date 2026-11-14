"""Checks on the configuration, and on the reader that grades it.

Nothing in this repository can apply the configuration, so the gate on it is
this suite and not a plan. Each rule is driven from both sides: it has to be
silent on infra and it has to fire on the fixture built to break it.
"""

import os

from screening import tfread, tfrules

HERE = os.path.dirname(os.path.abspath(__file__))
INFRA = os.path.join(os.path.dirname(HERE), "infra")
BAD = os.path.join(HERE, "fixtures", "infra_bad")


def check_every_rule_is_silent_on_the_real_configuration():
    got = tfrules.check_all(INFRA)
    problems = {k: v for k, v in got.items() if v}
    assert not problems, problems


def check_every_rule_fires_on_the_fixture_built_to_break_it():
    # Without this the module above is ten functions that could all return an
    # empty list for any reason at all.
    got = tfrules.check_all(BAD)
    silent = sorted(k for k, v in got.items() if not v)
    assert not silent, "these rules did not fire on the broken fixture: %r" % (silent,)


def check_the_rule_list_and_the_rule_functions_are_the_same_set():
    # A rule defined and left out of RULES is a rule that never runs, and the
    # coupling check has to iterate the module rather than a list beside it.
    defined = {
        name
        for name in dir(tfrules)
        if callable(getattr(tfrules, name))
        and not name.startswith("_")
        and name not in ("check_all", "tfread")
        and getattr(getattr(tfrules, name), "__module__", "") == tfrules.__name__
    }
    listed = {r.__name__ for r in tfrules.RULES}
    assert defined == listed, (sorted(defined - listed), sorted(listed - defined))


def check_the_reader_finds_every_resource_in_the_configuration():
    entries = tfread.read_dir(INFRA)
    assert entries, "the reader returned nothing for a directory that has files in it"
    kinds = {b.labels[0] for _n, b in entries if b.kind == "resource" and b.labels}
    for required in (
        "snowflake_warehouse",
        "snowflake_resource_monitor",
        "snowflake_database",
        "snowflake_account_role",
        "snowflake_grant_privileges_to_account_role",
        "snowflake_file_format_csv",
        "snowflake_pipe",
        "snowflake_service_user",
    ):
        assert required in kinds, required


def check_the_reader_sees_past_a_heredoc():
    text = '''resource "snowflake_pipe" "p" {
  name        = "P"
  auto_ingest = true

  copy_statement = <<-COPY
    copy into ${a.b.c}.t
    from @${a.b.c}.s
  COPY

  comment = "after the heredoc"
}
'''
    got = tfread.blocks(text)
    assert len(got) == 1, got
    assert got[0].args == {"name", "auto_ingest", "copy_statement", "comment"}, got[0].args


def check_a_hash_inside_a_string_is_not_read_as_a_comment():
    text = '''resource "snowflake_warehouse" "w" {
  name    = "W#1"
  comment = "size # not a comment"
  auto_suspend = 60
}
'''
    got = tfread.blocks(text)
    assert got[0].args == {"name", "comment", "auto_suspend"}, got[0].args


def check_a_commented_out_argument_does_not_count_as_present():
    # The failure this guards is a rule passing because the element it wants
    # appears in the sentence explaining why it is missing.
    text = '''resource "snowflake_warehouse" "w" {
  name = "W"
  # auto_suspend is deliberately left out here
}
'''
    got = tfread.blocks(text)
    assert got[0].args == {"name"}, got[0].args
    problems = tfrules.warehouse_suspends_itself([("x.tf", got[0])])
    assert len(problems) == 1, problems


def check_a_nested_block_is_recorded_by_name():
    text = '''resource "snowflake_stage_external_s3" "s" {
  name = "S"
  url  = "s3://x"

  credentials {
    aws_key_id = "k"
  }
}
'''
    got = tfread.blocks(text)
    assert got[0].nested == {"credentials"}, got[0].nested
    problems = tfrules.stage_points_somewhere_and_carries_no_credential([("x.tf", got[0])])
    assert any("inline credentials" in p for p in problems), problems


def check_the_monitor_rule_fires_when_there_is_no_monitor_at_all():
    # An absent resource and a hollow one are both absences and the second is
    # the one a reader of the file would miss.
    assert tfrules.monitor_can_actually_alert([])


def check_the_provider_rule_fires_when_there_is_no_provider_at_all():
    assert tfrules.provider_names_who_it_connects_as([])


def check_the_configuration_pins_the_provider_version():
    with open(os.path.join(INFRA, "versions.tf"), encoding="utf-8") as fh:
        text = fh.read()
    assert "snowflakedb/snowflake" in text, text
    assert 'version = "2.23.0"' in text, text


def check_no_variable_that_identifies_a_real_account_carries_a_default():
    with open(os.path.join(INFRA, "variables.tf"), encoding="utf-8") as fh:
        text = fh.read()
    for block in tfread.blocks(text):
        if block.kind != "variable":
            continue
        name = block.label
        if name in ("organization_name", "account_name", "ci_user_name", "deploy_warehouse_name"):
            assert "default" not in block.args, "%s carries a default" % name


NEVER_IN_CONFIGURATION = ("private_key", "aws_secret_key", "password")


def check_nothing_in_the_configuration_sets_a_credential_argument():
    # Read off the argument names rather than out of the text. A grep over the
    # file failed twice: first on the comment in provider.tf saying the deploy
    # carries no password, then on the description string in variables.tf
    # explaining that a public key is not one. Both sentences are correct and
    # both are prose sitting beside configuration.
    for name, block in tfread.read_dir(INFRA):
        names = {a.lower() for a in block.args | block.nested_args}
        hit = sorted(names & set(NEVER_IN_CONFIGURATION))
        assert not hit, "%s %s sets %r" % (name, block.label, hit)


def check_a_credential_argument_is_found_inside_a_nested_block():
    # The control, and the reason the reader had to record nested arguments at
    # all. A rule that only reads top level arguments is silent on the one
    # place an inline key would be written.
    text = """resource "snowflake_stage_external_s3" "s" {
  name = "S"
  url  = "s3://x"

  credentials {
    aws_secret_key = "oops"
  }
}
"""
    block = tfread.blocks(text)[0]
    assert "aws_secret_key" not in block.args
    assert "aws_secret_key" in block.nested_args, block.nested_args
    names = {a.lower() for a in block.args | block.nested_args}
    assert names & set(NEVER_IN_CONFIGURATION) == {"aws_secret_key"}


def check_prose_naming_a_credential_does_not_trip_the_rule():
    # The other direction. variables.tf has to be allowed to explain itself.
    text = """variable "loader_rsa_public_key" {
  description = "A public key is not a secret and a password would be."
  type        = string
}
"""
    block = tfread.blocks(text)[0]
    names = {a.lower() for a in block.args | block.nested_args}
    assert not names & set(NEVER_IN_CONFIGURATION), names


def check_stripping_comments_leaves_the_configuration_parseable():
    with open(os.path.join(INFRA, "load.tf"), encoding="utf-8") as fh:
        raw = fh.read()
    before = tfread.blocks(raw)
    after = tfread.blocks(tfread.strip_comments(raw))
    assert len(before) == len(after), (len(before), len(after))
    for a, b in zip(before, after):
        assert a.label == b.label, (a.label, b.label)
        assert a.args == b.args, (a.label, a.args ^ b.args)


def check_the_reader_closes_a_block_with_nested_blocks_two_deep():
    # A scanner that loses count on the way out of a nested block attributes
    # the next block's arguments to this one.
    text = '''resource "snowflake_grant_privileges_to_account_role" "a" {
  account_role_name = "R"
  privileges        = ["USAGE"]

  on_schema_object {
    future {
      object_type_plural = "TABLES"
      in_schema          = "D.S"
    }
  }
}

resource "snowflake_warehouse" "b" {
  name         = "W"
  auto_suspend = 60
}
'''
    got = tfread.blocks(text)
    assert len(got) == 2, [b.label for b in got]
    assert got[0].args == {"account_role_name", "privileges"}, got[0].args
    assert got[0].nested == {"on_schema_object", "future"}, got[0].nested
    assert got[1].label == "snowflake_warehouse.b", got[1].label
    assert got[1].args == {"name", "auto_suspend"}, got[1].args


def check_a_double_slash_comment_is_stripped():
    text = '''resource "snowflake_warehouse" "w" {
  name = "W" // the name
  // auto_suspend = 60
}
'''
    got = tfread.blocks(text)
    assert got[0].args == {"name"}, got[0].args


def check_an_escaped_quote_does_not_end_the_string():
    # grants.tf writes quoted identifiers this way, so a scanner that treats an
    # escaped quote as a terminator reads the rest of the line as code.
    text = '''resource "snowflake_grant_privileges_to_account_role" "a" {
  account_role_name = "R"

  on_schema {
    schema_name = "\\"D\\".\\"S\\" # not a comment"
  }
}
'''
    got = tfread.blocks(text)
    assert got[0].args == {"account_role_name"}, got[0].args
    assert got[0].nested == {"on_schema"}, got[0].nested
    assert got[0].nested_args == {"schema_name"}, got[0].nested_args


def check_two_heredocs_in_one_block_are_both_consumed():
    text = '''resource "snowflake_pipe" "p" {
  name = "P"

  copy_statement = <<-ONE
    copy into a
  ONE

  comment = <<-TWO
    a comment with a { brace in it
  TWO

  auto_ingest = true
}
'''
    got = tfread.blocks(text)
    assert len(got) == 1, got
    assert got[0].args == {"name", "copy_statement", "comment", "auto_ingest"}, got[0].args


def check_a_brace_inside_a_heredoc_does_not_open_a_block():
    text = '''resource "snowflake_pipe" "p" {
  name           = "P"
  auto_ingest    = true
  copy_statement = <<-COPY
    from @${a.b.c}.s
    where x = {
  COPY
}

resource "snowflake_warehouse" "w" {
  name         = "W"
  auto_suspend = 60
}
'''
    got = tfread.blocks(text)
    assert len(got) == 2, [b.label for b in got]
    assert got[1].label == "snowflake_warehouse.w", got[1].label


def check_a_variable_block_records_whether_it_has_a_default():
    text = '''variable "a" {
  type    = string
  default = "x"
}

variable "b" {
  type = string
}
'''
    got = tfread.blocks(text)
    assert [b.label for b in got] == ["a", "b"], got
    assert "default" in got[0].args
    assert "default" not in got[1].args


def check_reading_a_directory_returns_the_file_each_block_came_from():
    entries = tfread.read_dir(INFRA)
    names = {name for name, _b in entries}
    assert "warehouses.tf" in names, sorted(names)
    for name, block in entries:
        assert name.endswith(".tf"), name
        assert block.kind, block


def check_reading_a_directory_with_no_configuration_in_it_returns_nothing():
    # Named rather than left implicit. A reader that returned something here
    # would make every rule pass on an empty directory.
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        assert tfread.read_dir(d) == []
        got = tfrules.check_all(d)
        # And the two rules whose subject is a resource that must exist have to
        # fire on nothing at all.
        assert got["monitor_can_actually_alert"], got
        assert got["provider_names_who_it_connects_as"], got


# The depth arithmetic decides how many blocks the reader returns, and a reader
# that loses a block makes every rule pass on a file it never read. These drive
# it from several shapes and assert the count rather than the contents.
DEPTH_SHAPES = (
    # one nested block, closing on its own line
    ('''resource "a" "one" {
  name = "N"

  nested {
    x = 1
  }
}

resource "b" "two" {
  name = "M"
}
''', 2, {"one": {"name"}, "two": {"name"}}),
    # two nested blocks in a row
    ('''resource "a" "one" {
  name = "N"

  first {
    x = 1
  }

  second {
    y = 2
  }

  tail = "t"
}

resource "b" "two" {
  name = "M"
}
''', 2, {"one": {"name", "tail"}, "two": {"name"}}),
    # three deep
    ('''resource "a" "one" {
  name = "N"

  outer {
    middle {
      inner {
        z = 1
      }
    }
  }

  tail = "t"
}

resource "b" "two" {
  name = "M"
}
''', 2, {"one": {"name", "tail"}, "two": {"name"}}),
    # a nested block whose braces share a line
    ('''resource "a" "one" {
  name = "N"

  nested {
    inline = { k = "v" }
  }
}

resource "b" "two" {
  name = "M"
}
''', 2, {"one": {"name"}, "two": {"name"}}),
)


def check_the_depth_arithmetic_returns_every_block_in_each_shape():
    for i, (text, count, args_by_label) in enumerate(DEPTH_SHAPES):
        got = tfread.blocks(text)
        assert len(got) == count, (i, [b.label for b in got])
        by_label = {b.labels[1]: b for b in got}
        assert set(by_label) == set(args_by_label), (i, sorted(by_label))
        for label, expected in args_by_label.items():
            assert by_label[label].args == expected, (i, label, by_label[label].args)


def check_a_block_that_never_closes_does_not_swallow_the_rest_of_the_file():
    # The failure is silent. A reader that stays inside an unclosed block
    # returns one block and every rule then grades a file it half read.
    text = '''resource "a" "one" {
  name = "N"

resource "b" "two" {
  name = "M"
}
'''
    got = tfread.blocks(text)
    labels = [b.labels[1] for b in got]
    assert "two" not in labels or len(got) == 2, labels
    assert got, "an unclosed block made the reader return nothing at all"


def check_the_reader_counts_the_configuration_blocks_it_is_given():
    """A reader that starts dropping blocks quietly shrinks what the rules grade.

    The counts used to be typed into this check, at 34 resources and 18
    variables and a split of 29 and 5 by provider. All four had to be retyped
    on 2026-11-14 when the access configuration landed, which is the tell that
    a check is carrying a copy of something the repository already knows. A
    typed count also passes for the wrong reason: it agrees with a reader that
    drops one block on the day somebody adds one.

    So the count comes from the second parser instead. The question this asks
    is whether the two readings have the same size, and neither side of that
    is a number anybody maintains.
    """
    entries = tfread.read_dir(INFRA)
    independent = hcl2_blocks(INFRA)

    for kind in ("resource", "variable", "provider"):
        mine = len([b for _n, b in entries if b.kind == kind])
        theirs = independent[kind]
        assert mine == theirs, (kind, mine, theirs)
        assert mine > 0, kind

    # Split by provider, because one count over two providers hides a reader
    # that drops every block of one of them.
    by_provider = {}
    for _name, block in entries:
        if block.kind == "resource" and block.labels:
            prefix = block.labels[0].split("_")[0]
            by_provider[prefix] = by_provider.get(prefix, 0) + 1
    assert set(by_provider) == {"snowflake", "fivetran"}, by_provider
    assert sum(by_provider.values()) == independent["resource"], by_provider


def hcl2_blocks(path):
    """How many top level blocks of each kind a second parser finds.

    Lives here rather than in the agreement module because this is the only
    check that needs a count. python-hcl2 returns one list per block kind with
    one dictionary per block, keyed by label, so a kind with two blocks of the
    same first label arrives as two entries in the list.
    """
    import hcl2

    counts = {"resource": 0, "variable": 0, "provider": 0}
    for name in sorted(os.listdir(path)):
        if not name.endswith(".tf"):
            continue
        with open(os.path.join(path, name), encoding="utf-8") as handle:
            parsed = hcl2.load(handle)
        for kind in counts:
            for entry in parsed.get(kind, []):
                if kind == "resource":
                    counts[kind] += sum(len(v) for v in entry.values())
                else:
                    counts[kind] += len(entry)
    return counts


# The reader's own transformation, graded character for character.
#
# Two checks above reach the escape branch and the double slash branch and then
# assert the argument names the reader came out with. An off by one in either
# branch changes the characters and leaves the names alone, so eighteen mutants
# of this module survived a suite that was already exercising the lines they
# sit on. What the function returns is the subject, so that is what these
# compare.


def check_stripping_a_line_leaves_an_escaped_quote_and_what_follows_it():
    line = '  schema_name = "\\"D\\".\\"S\\" # not a comment"'
    assert tfread.strip_comments(line) == line, tfread.strip_comments(line)


def check_stripping_a_line_removes_a_double_slash_comment_and_keeps_a_lone_slash():
    # The lone slash is the half that matters. A rule that breaks on any slash
    # truncates an expression, and the argument name survives the truncation.
    line = "  count = 4 / 2 // halved"
    assert tfread.strip_comments(line) == "  count = 4 / 2 ", repr(tfread.strip_comments(line))


def check_stripping_a_hash_comment_keeps_the_code_before_it():
    line = '  name = "W" # the warehouse'
    assert tfread.strip_comments(line) == '  name = "W" ', repr(tfread.strip_comments(line))


def check_an_argument_opened_as_a_heredoc_inside_a_nested_block_is_recorded():
    # It was recorded at the top level and nowhere else, so a credential
    # written as a heredoc body one level in reached neither set.
    text = '''resource "snowflake_pipe" "p" {
  name = "P"

  on_schema {
    body = <<-SQL
      copy into t from @s
    SQL
  }
}
'''
    got = tfread.blocks(text)
    assert len(got) == 1, [b.label for b in got]
    assert got[0].args == {"name"}, got[0].args
    assert got[0].nested == {"on_schema"}, got[0].nested
    assert got[0].nested_args == {"body"}, got[0].nested_args


def check_the_reader_recovers_when_a_nested_block_and_its_parent_close_together():
    # Two levels closing on one line is not what the formatter writes and it is
    # what a hand edited file carries. A scanner that does not reset on it
    # attributes the next block's arguments to this one, or reaches for a block
    # that is no longer open.
    text = '''resource "snowflake_warehouse" "a" {
  name = "A"

  on_schema {
    inner = 1 } }

resource "snowflake_warehouse" "b" {
  name = "B"
}
'''
    got = tfread.blocks(text)
    assert [b.label for b in got] == ["snowflake_warehouse.a", "snowflake_warehouse.b"], [
        b.label for b in got
    ]
    assert got[0].args == {"name"}, got[0].args
    assert got[0].nested_args == {"inner"}, got[0].nested_args
    assert got[1].args == {"name"}, got[1].args


MIXED_BLOCKS = '''provider "snowflake" {
  account_name = "A"
}

resource "snowflake_warehouse" "w" {
  name = "W"
}

resource "snowflake_database" "d" {
  name = "D"
}

variable "x" {
  type = string
}
'''


def check_the_resource_filter_returns_resources_and_nothing_else():
    got = tfread.resources(MIXED_BLOCKS)
    assert [b.label for b in got] == ["snowflake_warehouse.w", "snowflake_database.d"], [
        b.label for b in got
    ]
    assert {b.kind for b in got} == {"resource"}, {b.kind for b in got}


def check_the_resource_filter_narrowed_to_a_type_returns_only_that_type():
    got = tfread.resources(MIXED_BLOCKS, "snowflake_warehouse")
    assert [b.label for b in got] == ["snowflake_warehouse.w"], [b.label for b in got]
    none = tfread.resources(MIXED_BLOCKS, "snowflake_stage")
    assert none == [], [b.label for b in none]


def check_a_heredoc_opened_on_a_line_of_its_own_records_no_argument():
    # Legal and the reader has to survive it. A heredoc inside a list opens on
    # a line carrying no name at all, and a reader that reaches for the name
    # anyway fails on the file rather than on the rule.
    text = '''resource "snowflake_pipe" "p" {
  name = "P"

  statements = [
    <<-SQL
    copy into t from @s
    SQL
  ]
}
'''
    got = tfread.blocks(text)
    assert len(got) == 1, [b.label for b in got]
    assert got[0].args == {"name", "statements"}, got[0].args
    assert got[0].nested_args == set(), got[0].nested_args
