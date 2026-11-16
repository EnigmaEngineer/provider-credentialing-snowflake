"""The per pull request clone, as statements this repository can grade.

A zero copy clone per pull request is cheap to describe and has two ways to go
wrong that cost real money. The clone is never dropped, so storage accumulates
one database per merged branch. Or the name is built out of something a
contributor controls, and the name goes into DDL as a string.

So the statements live here rather than inside the workflow file. A SQL string
inside YAML is read by nothing, which is the same hazard as a policy body
inside a terraform string, and that one has already cost this project a day.
These are built by code the suite calls directly.

The pull request number is the only input and it is required to be an integer.
That is not tidiness. The identifier goes into DDL with no way to parameterise
it, so a branch name reaching this function would be a string concatenated
into a statement that runs as the deploying role.
"""

import argparse
import re

# Snowflake folds an unquoted identifier to upper case, so the name is written
# the way the warehouse will hold it. A quoted lower case name here would mean
# every later reference needs the quotes too.
PREFIX = "SCREENING_CI_PR_"
SOURCE_DATABASE = "SCREENING_ANALYTICS"
IDENTIFIER = re.compile(r"^[A-Z][A-Z0-9_]*$")


class CloneNameError(Exception):
    """Raised when the clone's name cannot be built safely."""


def database_name(pull_request):
    """The clone's database name, from the pull request number alone."""
    if isinstance(pull_request, bool) or not isinstance(pull_request, int):
        raise CloneNameError(
            "the pull request number has to be an integer and this is %r" % (pull_request,)
        )
    if pull_request <= 0:
        raise CloneNameError("a pull request number is positive and this is %d" % pull_request)
    name = "%s%d" % (PREFIX, pull_request)
    if not IDENTIFIER.match(name):
        raise CloneNameError("%r is not an unquoted identifier" % name)
    return name


def create_statements(pull_request, source=SOURCE_DATABASE):
    """Clone the marts, and set the clone to expire on its own.

    The transient clone and the data retention of zero are the part that
    matters if the teardown never runs. A clone that nothing drops still stops
    costing within a day instead of forever.
    """
    name = database_name(pull_request)
    return (
        "create or replace transient database %s clone %s;" % (name, source),
        "alter database %s set data_retention_time_in_days = 0;" % name,
        "alter database %s set comment = 'ci clone for pull request %d';"
        % (name, pull_request),
    )


def drop_statements(pull_request):
    """Drop the clone, and do not fail when it was never created.

    The teardown runs whatever the job did, so it has to be callable after a
    create that did not happen.
    """
    name = database_name(pull_request)
    return ("drop database if exists %s;" % name,)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("create", "drop"))
    ap.add_argument("pull_request", type=int)
    ap.add_argument("--source", default=SOURCE_DATABASE)
    args = ap.parse_args(argv)
    if args.action == "create":
        statements = create_statements(args.pull_request, args.source)
    else:
        statements = drop_statements(args.pull_request)
    for statement in statements:
        print(statement)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
