"""Parse the transform project once per target and record what each one resolved.

    python3 scripts/measure_targets.py

A parse opens no connection, so this is the only claim about the warehouse
target that can be made without an account. What it proves is narrow and worth
stating exactly. It proves the project is well formed against that adapter and
that every relation name resolves to the database and schema it was meant to.
It does not compile the warehouse SQL, which has therefore never existed
anywhere.

Both targets write the same target/manifest.json, so each parse runs against a
cleared directory and its manifest is read before the next one starts. Reading
after both have run compares one target against itself and reports agreement.

The comparison earns its place. It found the model schema resolving to the
configured name twice over, which both targets produced without complaint.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROJECT = os.path.join(ROOT, "transform")
OUT = os.path.join(ROOT, "measurements", "targets.json")
TARGETS = ("duckdb", "snowflake")


def parse_one(target):
    build = os.path.join(PROJECT, "target")
    shutil.rmtree(build, ignore_errors=True)
    env = dict(os.environ)
    env["DBT_PROFILES_DIR"] = os.path.join(PROJECT, "profiles")
    done = subprocess.run(
        ["dbt", "parse", "--target", target, "--quiet"],
        cwd=PROJECT,
        env=env,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise SystemExit(
            "dbt parse --target %s exited %d\n%s" % (target, done.returncode, done.stderr.strip())
        )
    with open(os.path.join(build, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def resolved(manifest):
    out = {"adapter": manifest["metadata"]["adapter_type"], "sources": {}, "models": {}}
    for key, node in sorted(manifest["sources"].items()):
        out["sources"][node["name"]] = node["relation_name"]
    for key, node in sorted(manifest["nodes"].items()):
        if node["resource_type"] != "model":
            continue
        out["models"][node["name"]] = node["relation_name"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.parse_args(argv)

    answers = {}
    for target in TARGETS:
        answers[target] = resolved(parse_one(target))
        if answers[target]["adapter"] != target:
            raise SystemExit(
                "parsing against %r produced a manifest for %r, so the read happened after the next parse"
                % (target, answers[target]["adapter"])
            )

    # Every name has to differ between the two. A name that agrees is a name
    # one of the targets did not resolve, which is what reading a stale
    # manifest looks like.
    agreeing = []
    for kind in ("sources", "models"):
        for name in sorted(answers[TARGETS[0]][kind]):
            first = answers[TARGETS[0]][kind][name]
            second = answers[TARGETS[1]][kind].get(name)
            if first == second:
                agreeing.append("%s.%s" % (kind, name))

    measured = {
        "targets": list(TARGETS),
        "resolved": answers,
        "names_agreeing_across_targets": agreeing,
        "measured": ["resolved", "names_agreeing_across_targets"],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(measured, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("wrote %s" % OUT)
    for target in TARGETS:
        print("  %s" % target)
        for name, relation in sorted(answers[target]["models"].items()):
            print("    %-40s %s" % (name, relation))
    if agreeing:
        print("  names agreeing across targets: %r" % agreeing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
