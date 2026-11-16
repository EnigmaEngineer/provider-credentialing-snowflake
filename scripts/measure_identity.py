"""Reconcile the account namespace across the three files that spend it.

Writes measurements/identity.json. The manifest carries counts and names and
no wall time, so a check can re-derive every figure in it on another machine.

Run this on any day that renames a Snowflake object, adds a variable, or
changes an environment block in the workflow. Those are the only three things
that can make it disagree.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screening import identity, tfread  # noqa: E402


def measure(root):
    entries = tfread.read_dir(os.path.join(root, "infra"))
    created, skipped = identity.created(entries)
    consumers = identity.consumers_of(root)
    variables = identity.declared_variables(entries)
    workflow_env = identity.workflow_environment(
        os.path.join(root, ".github", "workflows", "ci.yml")
    )
    profile_pairs, env_var_calls = identity.profile_identities(
        os.path.join(root, "transform", "profiles", "profiles.yml")
    )
    profile_variables = [var for var, _default in profile_pairs]
    shell_read = identity.shell_variables(os.path.join(root, ".github", "workflows", "ci.yml"))

    problems = {
        "a_name_spent_and_not_created": identity.every_name_a_consumer_spends_is_created(created, consumers),
        "an_object_created_and_not_spent": identity.every_object_created_is_spent(created, consumers),
        "a_variable_set_and_not_read": identity.every_variable_a_job_sets_is_read(profile_variables, workflow_env, shell_read),
        "a_required_variable_not_supplied": identity.every_required_variable_is_supplied(variables, workflow_env),
        "a_variable_passed_and_not_declared": identity.every_variable_a_job_passes_is_declared(variables, workflow_env),
        "an_object_with_no_teardown": identity.every_object_created_elsewhere_has_a_teardown(),
    }

    return {
        "created": {name: list(created[name]) for name in sorted(created)},
        "created_count": len(created),
        "account_level_created_count": sum(
            1 for name in created if created[name][0] in identity.ACCOUNT_LEVEL
        ),
        "measured": [
            "created",
            "spent",
            "problems",
            "unconsumed_on_purpose",
            "torn_down_by",
        ],
        "created_with_a_name_this_reader_cannot_resolve": skipped,
        "spent": sorted({name for _w, name, _d in consumers}),
        "spent_count": len({name for _w, name, _d in consumers}),
        "consumer_sites": len(consumers),
        "profile_env_var_calls": env_var_calls,
        "profile_identities_read": len(profile_pairs),
        "declared_variables": len(variables),
        "required_variables": sorted(n for n in variables if not variables[n]),
        "workflow_environment_names": sorted({n for n, _v, _l in workflow_env}),
        "read_by_a_third_party": sorted(identity.READ_BY_A_THIRD_PARTY),
        "account_level_kinds": list(identity.ACCOUNT_LEVEL),
        "unconsumed_on_purpose": sorted(identity.UNCONSUMED_ON_PURPOSE),
        "created_elsewhere": sorted(identity.CREATED_ELSEWHERE),
        "torn_down_by": dict(identity.TORN_DOWN_BY),
        "problems": problems,
        "problem_count": sum(len(v) for v in problems.values()),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    result = measure(args.root)
    out = args.out or os.path.join(args.root, "measurements", "identity.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("%d created, %d spent, %d problems" % (result["created_count"], result["spent_count"], result["problem_count"]))
    for section in sorted(result["problems"]):
        for line in result["problems"][section]:
            print("  %s: %s" % (section, line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
