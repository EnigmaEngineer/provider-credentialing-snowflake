"""Executing the workflow's steps, and recording what each one exited with.

Twelve checks in `tests/test_workflow.py` read the workflow file and none of
them runs it. `terraform fmt -check -diff` sat in the configuration job for
four days while a misaligned file sat in `infra/`, and all twelve passed
throughout. This is the half of that gap which needs no GitHub account and no
Snowflake account.

What this is not. It is not a runner. It does not build a container, it does
not resolve an action, and it cannot evaluate a `${{ }}` expression. What it
does is take the `run` steps of a job in the order the file lists them,
execute each one with the shell in the repository root, and record the exit
code. A step it cannot execute is recorded as not executed with the reason,
which is the part that makes the manifest worth reading. A runner that
silently skipped the step it could not do would report the same clean answer
the static checks already report.

The tool steps are read rather than performed. `hashicorp/setup-terraform`
with a pinned version becomes a check that terraform is here and is that
version, and a version that does not match is a skip with the mismatch named
rather than a pass.

No one machine here can run every job. The suite job pins the Python the
device interpreter happens to be, and terraform and dbt are in the cloud
container and not on the device. So a job carries the machine it was measured
on and the entry point's `--merge` updates only the jobs it attempted. A
manifest that hid that would be claiming one machine ran all of it.

This module is importable so the suite can call `verdict` and `provision`
directly. A check that only read the manifest could not disagree with the code
that wrote it.
"""

import json
import os
import re
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "ci.yml")

EXPRESSION = re.compile(r"\$\{\{")

# The one job this cannot execute, and the reason is not a missing tool. The
# suite writes nothing and grades `measurements/workflow-run.json`, which is
# the file a run of it would be recorded in. Executing it here would grade the
# manifest as it stood before this run and then record that result into the
# manifest, so the committed answer would always be one iteration stale. The
# suite is run directly every day and that run is what the record carries.
SELF_REFERENTIAL = {
    "suite": "the suite grades this manifest, so a run of it recorded here would be one iteration stale"
}

# The actions this knows how to stand in for, and what standing in means. An
# action not listed is reported by name rather than guessed at.
# The second element is the key inside the step's `with` block that carries
# the version. These are the action's own spelling and not a guess, and they
# differ between the two: `python-version` with a hyphen and
# `terraform_version` with an underscore. The first version of this table had
# both as underscores, so every setup-python step reported satisfied on a
# Python that was three minor versions off the pin. There is a check asserting
# each key below is present in the workflow step it claims to read.
PROVISIONERS = {
    "actions/checkout": ("the working tree is already here", None),
    "actions/setup-python": ("python is already here", "python-version"),
    "hashicorp/setup-terraform": ("terraform has to be on the path", "terraform_version"),
}


def version_keys():
    """The `with` key each known action carries its version in."""
    return {
        action: key for action, (_reason, key) in sorted(PROVISIONERS.items()) if key
    }


def workflow(path=WORKFLOW):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def tool_version(binary, argv):
    try:
        done = subprocess.run(
            [binary] + argv, capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)
    return (done.stdout + done.stderr).strip(), None


def terraform_version_from(text):
    """The version out of `terraform version -json`, or out of its first line.

    A function rather than a try block inside `provision`, because the
    fallback is for a terraform too old to answer `-json` and no machine here
    has one. Neither the device nor the container could reach that branch, so
    a mutation pass found it ungraded, and a branch nothing can run is a
    branch nobody should trust.
    """
    try:
        return json.loads(text)["terraform_version"]
    except (TypeError, ValueError, KeyError):
        return text.splitlines()[0] if text else ""


def provision(step, read_terraform=None):
    """What a `uses` step means for a run on this machine.

    `read_terraform` exists so the terraform branch can be graded on a machine
    that has no terraform, which is every machine this suite usually runs on.
    Without it the branch is reachable only where the binary happens to be,
    and a module whose job is saying what it actually measured should not have
    a half of itself that nothing can measure.
    """
    action = step["uses"].split("@")[0]
    with_block = step.get("with") or {}
    if action not in PROVISIONERS:
        return {
            "status": "unknown-action",
            "reason": "nothing here knows what %r provides" % action,
        }
    reason, version_key = PROVISIONERS[action]
    asked = with_block.get(version_key) if version_key else None
    if action == "actions/checkout":
        return {"status": "already-satisfied", "reason": reason}
    if action == "actions/setup-python":
        found = "%d.%d" % sys.version_info[:2]
        if asked and str(asked) != found:
            return {
                "status": "version-differs",
                "reason": "the workflow pins python %s and this is %s" % (asked, found),
                "asked": str(asked),
                "found": found,
            }
        return {"status": "already-satisfied", "reason": reason, "found": found}
    probe = read_terraform or (lambda: tool_version("terraform", ["version", "-json"]))
    text, failure = probe()
    if failure is not None:
        return {"status": "tool-absent", "reason": failure, "asked": str(asked)}
    found = terraform_version_from(text)
    if asked and str(asked) != found:
        return {
            "status": "version-differs",
            "reason": "the workflow pins terraform %s and this is %s" % (asked, found),
            "asked": str(asked),
            "found": found,
        }
    return {"status": "already-satisfied", "reason": reason, "found": found}


ANSI = re.compile(r"\x1b\[[0-9;]*m")
STAMP = re.compile(r"^\d{2}:\d{2}:\d{2}\s*")
DURATION = re.compile(r"\b\d+(\.\d+)?s\b|\b\d+ hours \d+ minutes[^)]*")


def clean(line):
    """One output line with the things that do not reproduce taken off.

    Colour escapes, the wall clock time dbt stamps on every line, and any
    duration. A manifest that carries a time does not reproduce, so its diff
    says nothing about what changed, and a wall time was ruled out of these
    manifests on 2026-10-13.
    """
    return DURATION.sub("", STAMP.sub("", ANSI.sub("", line).strip())).strip()


def execute(command, timeout):
    done = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    tail = (done.stdout + done.stderr).strip().splitlines()
    record = {
        "status": "ran" if done.returncode == 0 else "failed",
        "exit_code": done.returncode,
        # Whether the step said anything, and not how much it said. A line
        # count passes the rule about a manifest carrying counts rather than
        # wall times, and it re-derives no better than a wall time, because it
        # counts a tool's chatter rather than any work. The re-measure on
        # 2026-11-16 moved `terraform init` from 15 lines to 24 on a cold
        # plugin cache and `dbt seed` from 27 to 24 on a warm target
        # directory, with nothing in this repository changed.
        #
        # The run before it removed the log for a passing step for this reason
        # and kept the count of the log, which is the same instability at a
        # lower resolution.
        "produced_output": bool(tail),
    }
    if done.returncode != 0:
        # Output on a failure and not otherwise. A step that passed has
        # nothing to diagnose, and keeping its log here is what made this
        # manifest fail to reproduce in the first place.
        record["output_tail"] = [clean(line) for line in tail[-12:] if clean(line)]
    return record


def measured_on():
    """The machine a job was measured on.

    The terraform version goes through the same reader `provision` uses, so
    there is one way to get a version out of that binary rather than two. The
    first version of this took the first line itself, which was a second
    parser and a mutation site nothing could reach.
    """
    terraform, _failure = tool_version("terraform", ["version", "-json"])
    return {
        "platform": sys.platform,
        "python": "%d.%d.%d" % sys.version_info[:3],
        "terraform": terraform_version_from(terraform) if terraform else None,
    }


def run_job(name, job, timeout):
    held = job.get("if") in (False, "false")
    steps = []
    for index, step in enumerate(job.get("steps", [])):
        label = step.get("name") or step.get("uses", "step %d" % index)
        record = {"index": index, "name": label}
        if name in SELF_REFERENTIAL:
            record.update(status="self-referential", reason=SELF_REFERENTIAL[name])
        elif held:
            record.update(status="job-held-off", reason="the job's own `if` is false")
        elif "uses" in step:
            record.update(provision(step))
        elif not isinstance(step.get("run"), str):
            record.update(status="no-command", reason="the step has neither `uses` nor `run`")
        elif EXPRESSION.search(step["run"]) or EXPRESSION.search(
            json.dumps(step.get("env") or {})
        ):
            record.update(
                status="needs-expression",
                reason="the step reads a ${{ }} expression only the runner can fill in",
            )
        else:
            record.update(execute(step["run"], timeout))
        steps.append(record)
    return steps


def verdict(jobs):
    """Three answers and not two.

    `failed` means a step ran and exited non zero, which is the answer the
    static checks cannot produce. `incomplete` means every step that ran
    passed and at least one could not run here, which is honest and is not a
    pass. `passed` is every step of every live job executed and clean.

    A held off job does not make a run incomplete, because nothing was meant
    to run. A self referential one does, because something was.
    """
    statuses = [step["status"] for job in jobs.values() for step in job["steps"]]
    if "failed" in statuses:
        return "failed"
    unrun = {
        "tool-absent",
        "version-differs",
        "unknown-action",
        "no-command",
        "self-referential",
    }
    if any(status in unrun for status in statuses):
        return "incomplete"
    return "passed"
