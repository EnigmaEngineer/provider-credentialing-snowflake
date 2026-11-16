"""Execute the workflow's steps here and write the manifest.

    python3 scripts/run_workflow.py
    python3 scripts/run_workflow.py --job configuration --job transform --merge

The work is in `orchestration/workflow.py` so the suite can call it. This is
the entry point and the manifest's only writer.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestration import workflow as wfmod  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "measurements", "workflow-run.json")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", action="append", default=None)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", default=OUT)
    ap.add_argument(
        "--merge",
        action="store_true",
        help="keep the jobs already in the manifest and replace only the ones attempted",
    )
    args = ap.parse_args(argv)

    wf = wfmod.workflow()
    wanted = args.job or sorted(wf["jobs"])
    unknown = [name for name in wanted if name not in wf["jobs"]]
    if unknown:
        raise SystemExit("the workflow has no job named %r" % unknown)

    here = wfmod.measured_on()
    fresh = {
        name: {
            "steps": wfmod.run_job(name, wf["jobs"][name], args.timeout),
            "measured_on": here,
        }
        for name in wanted
    }

    jobs = {}
    if args.merge and os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as fh:
            jobs = json.load(fh).get("jobs") or {}
    jobs.update(fresh)
    jobs = {name: jobs[name] for name in sorted(jobs) if name in wf["jobs"]}

    steps = [step for job in jobs.values() for step in job["steps"]]
    executed = [step for step in steps if step["status"] == "ran"]
    measured = {
        "workflow": os.path.relpath(wfmod.WORKFLOW, ROOT).replace(os.sep, "/"),
        "jobs_in_file": sorted(wf["jobs"]),
        "jobs_attempted": sorted(wanted),
        "jobs": jobs,
        "verdict": wfmod.verdict(jobs),
        "summary": {
            "jobs_in_the_workflow": len(wf["jobs"]),
            "jobs_with_an_executed_step": sum(
                1
                for job in jobs.values()
                if any(step["status"] == "ran" for step in job["steps"])
            ),
            "steps_executed": len(executed),
            "steps_not_executed": len(steps) - len(executed),
        },
        "measured": ["jobs", "verdict", "jobs_attempted", "summary"],
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(measured, fh, indent=1, sort_keys=True)
        fh.write("\n")

    print("wrote %s" % args.out)
    for name in sorted(jobs):
        print("  %s  (python %s)" % (name, jobs[name]["measured_on"]["python"]))
        for step in jobs[name]["steps"]:
            extra = step.get("reason") or ""
            if "exit_code" in step:
                extra = "exit %d" % step["exit_code"]
            print("    %-18s %-24s %s" % (step["status"], step["name"][:24], extra))
    print("  verdict: %s" % measured["verdict"])
    return 1 if measured["verdict"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
