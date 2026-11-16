"""Checks on the workflow file, and on a run of it.

Two kinds. The static ones read the names the file calls and the values it
passes, which is what an author gets wrong from memory. They cannot see
whether the state one step leaves is the state the next one needs. Twelve of
them passed for four days while the configuration job was red, because a
misaligned file had landed and `terraform fmt -check` was in the job.

So the second kind reads `measurements/workflow-run.json`, which
`scripts/run_workflow.py` writes by executing the steps. That manifest also
records the machine each job was measured on and the reason for every step
that did not run, because no one machine here can run all of them.
"""

import json
import os
import re
import sys

import yaml

from orchestration import workflow as wfrun
from screening import tfread

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "ci.yml")
INFRA = os.path.join(ROOT, "infra")
RUN = os.path.join(ROOT, "measurements", "workflow-run.json")


def workflow():
    with open(WORKFLOW, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def all_run_text(job):
    return "\n".join(
        step["run"] for step in job.get("steps", []) if isinstance(step.get("run"), str)
    )


def check_the_workflow_parses_and_its_jobs_are_the_ones_expected():
    wf = workflow()
    expected = {"suite", "configuration", "transform", "clone", "deploy"}
    assert set(wf["jobs"]) == expected, sorted(wf["jobs"])


def check_every_python_script_the_workflow_runs_exists():
    wf = workflow()
    missing = []
    for name, job in wf["jobs"].items():
        for token in all_run_text(job).split():
            if token.endswith(".py"):
                if not os.path.exists(os.path.join(ROOT, token)):
                    missing.append((name, token))
    assert not missing, missing


def check_every_requirements_file_the_workflow_installs_exists():
    wf = workflow()
    missing = []
    for name, job in wf["jobs"].items():
        text = all_run_text(job)
        for token in text.split():
            if token.endswith(".txt"):
                if not os.path.exists(os.path.join(ROOT, token)):
                    missing.append((name, token))
    assert not missing, missing


def check_the_suite_job_installs_before_it_runs_the_checks():
    # The one ordering question a static read can answer, because both steps
    # are in the same job and one names the file the other needs.
    steps = workflow()["jobs"]["suite"]["steps"]
    order = [s.get("name") for s in steps]
    assert order.index("install") < order.index("checks"), order


def check_every_job_that_needs_an_account_is_held_off():
    # Neither has anything to reach. A job left enabled would fail on every
    # push and be switched off by whoever got tired of it first.
    wf = workflow()
    held = sorted(name for name, job in wf["jobs"].items() if job.get("if") is False)
    assert held == ["clone", "deploy"], held


def check_every_job_that_is_not_held_off_runs_without_an_account():
    # The three live jobs read committed fixtures, the provider schema and a
    # local engine. A live job that needed an account would be red on every
    # pull request, which is the state this project was in for four days.
    wf = workflow()
    for name, job in wf["jobs"].items():
        if job.get("if") is False:
            continue
        text = all_run_text(job)
        for forbidden in ("snow sql", "apply", "SNOWFLAKE_TOKEN"):
            assert forbidden not in text, (name, forbidden)


def check_the_deploy_job_asks_for_an_identity_token():
    # Without id-token write the runner is not issued a token at all, and the
    # failure appears as an empty file rather than as a permissions error.
    deploy = workflow()["jobs"]["deploy"]
    assert deploy["permissions"]["id-token"] == "write", deploy["permissions"]


def check_the_default_permissions_are_read_only():
    assert workflow()["permissions"]["contents"] == "read"


def check_the_variable_the_deploy_sets_is_the_one_the_provider_reads():
    # The provider does not name token_file_path, so this environment variable
    # is the only thing connecting the token the runner writes to the token the
    # provider reads. Nothing but this check couples them.
    deploy = workflow()["jobs"]["deploy"]
    envs = {}
    for step in deploy["steps"]:
        envs.update(step.get("env") or {})
    assert "SNOWFLAKE_TOKEN_FILE_PATH" in envs, sorted(envs)

    token_step = next(s for s in deploy["steps"] if s.get("name") == "identity token")
    target = token_step["run"].strip().splitlines()[-1].strip()
    assert "snowflake-oidc-token" in target, target
    assert "snowflake-oidc-token" in envs["SNOWFLAKE_TOKEN_FILE_PATH"], envs


def check_the_deploy_passes_a_value_for_every_variable_with_no_default():
    # A variable with no default and no value makes terraform prompt, and a
    # runner answering a prompt is a job that hangs until it is cancelled.
    with open(os.path.join(INFRA, "variables.tf"), encoding="utf-8") as fh:
        blocks = [b for b in tfread.blocks(fh.read()) if b.kind == "variable"]
    needed = {b.label for b in blocks if "default" not in b.args}

    deploy = workflow()["jobs"]["deploy"]
    envs = {}
    for step in deploy["steps"]:
        envs.update(step.get("env") or {})
    supplied = {k[len("TF_VAR_"):] for k in envs if k.startswith("TF_VAR_")}

    unsupplied = sorted(needed - supplied)
    # Named rather than asserted away. These are the ones a deploy would have
    # to be given and the account does not exist to give them yet.
    #
    # The replication variables joined the list. There is no account for that
    # connector either, so the deploy has nothing to give them, and the job
    # that would use them is held off.
    expected_gap = [
        "cost_alert_recipients",
        "credentialing_database",
        "credentialing_host",
        "fivetran_postgres_user",
        "fivetran_snowflake_role",
        "fivetran_snowflake_user",
        "loader_rsa_public_key",
        "loading_warehouse",
        "monthly_credit_quota",
        "raw_database",
        "registry_landing_url",
        "snowflake_host",
        "storage_aws_role_arn",
    ]
    assert unsupplied == expected_gap, unsupplied


def check_the_terraform_version_the_workflow_pins_satisfies_the_configuration():
    wf = workflow()
    pinned = set()
    for job in wf["jobs"].values():
        for step in job.get("steps", []):
            if str(step.get("uses", "")).startswith("hashicorp/setup-terraform"):
                pinned.add(step["with"]["terraform_version"])
    assert pinned == {"1.9.8"}, pinned

    with open(os.path.join(INFRA, "versions.tf"), encoding="utf-8") as fh:
        text = fh.read()
    assert 'required_version = ">= 1.9.0"' in text, text
    major, minor, _patch = (int(x) for x in sorted(pinned)[0].split("."))
    assert (major, minor) >= (1, 9), pinned


def check_the_configuration_job_runs_init_before_validate():
    steps = workflow()["jobs"]["configuration"]["steps"]
    order = [s.get("name") for s in steps]
    assert order.index("init") < order.index("validate"), order


def check_no_job_runs_terraform_apply_outside_the_held_off_one():
    wf = workflow()
    for name, job in wf["jobs"].items():
        if name == "deploy":
            continue
        assert "apply" not in all_run_text(job), name


# The run manifest.


def run_manifest():
    with open(RUN, encoding="utf-8") as fh:
        return json.load(fh)


def all_steps(found):
    return [step for job in found["jobs"].values() for step in job["steps"]]


def check_the_run_manifest_names_every_job_in_the_file():
    found = run_manifest()
    assert sorted(found["jobs"]) == sorted(workflow()["jobs"]), sorted(found["jobs"])
    assert found["jobs_in_file"] == sorted(workflow()["jobs"]), found["jobs_in_file"]


def check_no_step_in_the_run_manifest_failed():
    failed = [step for step in all_steps(run_manifest()) if step["status"] == "failed"]
    assert not failed, [(step["name"], step["exit_code"]) for step in failed]


def check_every_step_the_run_did_not_execute_says_why():
    silent = [
        step
        for step in all_steps(run_manifest())
        if step["status"] != "ran" and not step.get("reason")
    ]
    assert not silent, [step["name"] for step in silent]


def check_every_job_in_the_run_manifest_names_the_machine_it_ran_on():
    for name, job in sorted(run_manifest()["jobs"].items()):
        where = job.get("measured_on") or {}
        assert where.get("python"), name
        assert where.get("platform"), name


def check_every_job_that_could_run_executed_at_least_one_step():
    # A manifest where every step was skipped would satisfy the two checks
    # above and would have caught nothing. The list is derived rather than
    # typed, so a job that stops being runnable has to be named in the module
    # rather than quietly dropped from here.
    found = run_manifest()
    wf = workflow()
    runnable = sorted(
        name
        for name, job in wf["jobs"].items()
        if job.get("if") is not False and name not in wfrun.SELF_REFERENTIAL
    )
    assert runnable, "no job in the workflow can be executed here at all"
    for name in runnable:
        ran = [step for step in found["jobs"][name]["steps"] if step["status"] == "ran"]
        assert ran, name


def check_the_verdict_is_what_the_step_statuses_say():
    # Called directly rather than read, because a verdict stored in the
    # manifest cannot disagree with the function that wrote it.
    found = run_manifest()
    assert wfrun.verdict(found["jobs"]) == found["verdict"], found["verdict"]


def check_a_failed_step_makes_the_verdict_failed():
    jobs = {"j": {"steps": [{"status": "ran"}, {"status": "failed"}], "measured_on": {}}}
    assert wfrun.verdict(jobs) == "failed"


def check_a_step_that_could_not_run_makes_the_verdict_incomplete_and_not_passed():
    # The distinction the static checks cannot make. A runner that skipped
    # what it could not do would report the same clean answer they do.
    for status in ("tool-absent", "version-differs", "unknown-action", "no-command"):
        jobs = {"j": {"steps": [{"status": "ran"}, {"status": status}], "measured_on": {}}}
        assert wfrun.verdict(jobs) == "incomplete", status


def check_a_held_off_job_does_not_make_the_verdict_incomplete():
    jobs = {"j": {"steps": [{"status": "ran"}, {"status": "job-held-off"}], "measured_on": {}}}
    assert wfrun.verdict(jobs) == "passed"


def check_the_runner_stands_in_for_an_action_only_where_it_knows_what_it_provides():
    # An action nobody taught it about is reported by name. Treating an
    # unknown action as satisfied is how a run reports clean on a job whose
    # tooling never arrived.
    answer = wfrun.provision({"uses": "some-org/some-action@v1"})
    assert answer["status"] == "unknown-action", answer


def check_every_version_key_the_runner_reads_is_the_key_the_workflow_writes():
    """The runner's spelling of each action's version argument, against the file.

    `actions/setup-python` takes `python-version` and
    `hashicorp/setup-terraform` takes `terraform_version`. The first version
    of that table had both as underscores, so every setup-python step reported
    satisfied while the pin said 3.10 and the machine was on 3.13. A key typed
    from memory is the defect this whole module exists to catch, so it gets a
    check of its own.
    """
    wanted = wfrun.version_keys()
    seen = {}
    for job in workflow()["jobs"].values():
        for step in job.get("steps", []):
            action = str(step.get("uses", "")).split("@")[0]
            if action in wanted:
                seen.setdefault(action, set()).update((step.get("with") or {}))
    assert sorted(seen) == sorted(wanted), (sorted(seen), sorted(wanted))
    for action, key in sorted(wanted.items()):
        assert key in seen[action], (action, key, sorted(seen[action]))


def check_the_runner_refuses_a_pinned_tool_version_it_does_not_have():
    # Either answer is right and which one depends on the machine, so each is
    # held to what it has to carry. A version-differs with nothing in `found`
    # is a mismatch against a version nobody read.
    answer = wfrun.provision(
        {"uses": "hashicorp/setup-terraform@v3", "with": {"terraform_version": "0.0.1"}}
    )
    assert answer["status"] in ("version-differs", "tool-absent"), answer
    if answer["status"] == "version-differs":
        assert answer["found"], answer
    else:
        assert "terraform" in answer["reason"], answer


def check_the_suite_job_is_recorded_as_self_referential_rather_than_run():
    """The one job the runner cannot execute, and not because of a tool.

    The suite grades this manifest. A run of it recorded here would have
    graded the manifest as it stood before the run, so the committed answer
    would always be one iteration behind. The suite is run directly every day
    and that run is what the record carries.
    """
    steps = run_manifest()["jobs"]["suite"]["steps"]
    assert steps, "the manifest has no steps for the suite job"
    for step in steps:
        assert step["status"] == "self-referential", (step["name"], step["status"])
        assert step["reason"], step["name"]


def check_a_self_referential_job_makes_the_verdict_incomplete():
    # Not passed. Something was meant to run and did not, which is a
    # different thing from a job that was held off on purpose.
    jobs = {"j": {"steps": [{"status": "self-referential"}], "measured_on": {}}}
    assert wfrun.verdict(jobs) == "incomplete"


def check_no_line_in_the_run_manifest_carries_a_time_or_a_duration():
    """Because a manifest that does not reproduce has a diff that says nothing.

    dbt stamps a wall clock time and a duration on every line it prints, and
    the first version of this manifest kept twelve of them per step. It
    changed on every run with nothing in the repository changing.
    """
    for step in all_steps(run_manifest()):
        for line in step.get("output_tail") or []:
            assert not re.match(r"^\d{2}:\d{2}:\d{2}", line), line
            assert "\x1b" not in line, line
            assert not re.search(r"\b\d+(\.\d+)?s\b", line), line


def check_a_step_that_passed_carries_no_output():
    # Nothing to diagnose, and keeping it is what made the manifest churn.
    for step in all_steps(run_manifest()):
        if step["status"] == "ran":
            assert "output_tail" not in step, step["name"]


def check_the_runner_reads_the_checkout_step_without_a_with_block():
    # `actions/checkout` is a known action and carries no `with` block, and the
    # version lookup runs before the action is recognised. A mutation making
    # the missing block `None` instead of empty survived until this existed.
    answer = wfrun.provision({"uses": "actions/checkout@v4"})
    assert answer["status"] == "already-satisfied", answer
    assert answer["reason"], answer


def check_the_runner_accepts_a_python_pin_that_matches_this_interpreter():
    here = "%d.%d" % sys.version_info[:2]
    answer = wfrun.provision(
        {"uses": "actions/setup-python@v5", "with": {"python-version": here}}
    )
    assert answer["status"] == "already-satisfied", answer
    assert answer["found"] == here, answer


def check_the_runner_refuses_a_python_pin_that_does_not_match():
    """The defect that was actually in this module on the day it landed.

    The table spelled the key with an underscore, so `asked` came back empty
    and every step reported satisfied on whatever interpreter was running.
    This asserts the mismatch is seen and that both versions are named.
    """
    answer = wfrun.provision(
        {"uses": "actions/setup-python@v5", "with": {"python-version": "2.6"}}
    )
    assert answer["status"] == "version-differs", answer
    assert answer["asked"] == "2.6", answer
    assert answer["found"] == "%d.%d" % sys.version_info[:2], answer


def check_the_runner_tells_the_two_setup_actions_apart():
    # One mutation made the python branch fall through to the terraform one,
    # which reports on a binary the workflow never asked about.
    python_answer = wfrun.provision(
        {"uses": "actions/setup-python@v5", "with": {"python-version": "2.6"}}
    )
    terraform_answer = wfrun.provision(
        {"uses": "hashicorp/setup-terraform@v3", "with": {"terraform_version": "0.0.1"}}
    )
    assert python_answer.get("found") == "%d.%d" % sys.version_info[:2], python_answer
    assert python_answer.get("found") != terraform_answer.get("found"), (
        python_answer,
        terraform_answer,
    )


def check_the_tool_probe_reads_a_version_off_a_binary_that_is_here():
    """Exercised against the interpreter, because terraform is not everywhere.

    The device this suite usually runs on has no terraform, so four mutations
    inside the probe survived for no reason except that nothing reached it.
    Python is on every machine that can run this file at all.
    """
    text, failure = wfrun.tool_version("python3", ["--version"])
    assert failure is None, failure
    assert "Python" in text, text
    assert "%d.%d" % sys.version_info[:2] in text, text


def check_the_tool_probe_reports_a_binary_that_is_not_here():
    text, failure = wfrun.tool_version("a-binary-no-machine-has", ["--version"])
    assert text is None, text
    assert failure, failure


def check_a_step_that_exits_zero_is_recorded_as_having_run():
    answer = wfrun.execute("echo one; echo two", 30)
    assert answer["status"] == "ran", answer
    assert answer["exit_code"] == 0, answer
    assert answer["output_lines"] == 2, answer
    # Nothing to diagnose, and keeping it is what made the manifest churn.
    assert "output_tail" not in answer, answer


def check_a_step_that_exits_non_zero_is_recorded_as_failed_with_its_output():
    answer = wfrun.execute("echo the reason; exit 3", 30)
    assert answer["status"] == "failed", answer
    assert answer["exit_code"] == 3, answer
    assert answer["output_tail"] == ["the reason"], answer


def check_a_failing_step_keeps_the_last_twelve_lines_and_not_all_of_them():
    """The window, because a manifest carrying a whole suite's output is a
    diff nobody reads.

    Twenty lines in, twelve out, and the twelve are the last ones. A mutation
    moving that boundary by one survived while every test command printed
    fewer lines than the window.
    """
    answer = wfrun.execute("seq 1 20; exit 1", 30)
    assert answer["status"] == "failed", answer
    assert answer["output_lines"] == 20, answer
    assert answer["output_tail"] == [str(n) for n in range(9, 21)], answer


def check_a_step_that_writes_to_both_streams_has_both_read():
    answer = wfrun.execute("echo out; echo err 1>&2; exit 1", 30)
    assert sorted(answer["output_tail"]) == ["err", "out"], answer


def check_the_terraform_version_is_read_out_of_its_json():
    assert wfrun.terraform_version_from('{"terraform_version": "1.9.8"}') == "1.9.8"


def check_the_terraform_version_falls_back_to_the_first_line():
    """The branch for a terraform too old to answer `-json`.

    No machine in this project has one, so neither the device nor the
    container could reach this, and three mutations inside it survived.
    """
    assert wfrun.terraform_version_from("Terraform v1.9.8\non linux_amd64") == "Terraform v1.9.8"
    assert wfrun.terraform_version_from('{"no_version_key": true}') == '{"no_version_key": true}'
    assert wfrun.terraform_version_from("") == ""
    assert wfrun.terraform_version_from(None) == ""


def check_the_terraform_branch_accepts_a_version_that_matches_the_pin():
    """Graded with the probe supplied, because no machine here has terraform.

    The suite runs where the binary is absent, so this half of `provision`
    was reachable only in the container, and three mutations inside it
    survived on the machine that runs the pass.
    """
    answer = wfrun.provision(
        {"uses": "hashicorp/setup-terraform@v3", "with": {"terraform_version": "1.9.8"}},
        read_terraform=lambda: ('{"terraform_version": "1.9.8"}', None),
    )
    assert answer["status"] == "already-satisfied", answer
    assert answer["found"] == "1.9.8", answer


def check_the_terraform_branch_refuses_a_version_that_does_not_match_the_pin():
    answer = wfrun.provision(
        {"uses": "hashicorp/setup-terraform@v3", "with": {"terraform_version": "1.9.8"}},
        read_terraform=lambda: ('{"terraform_version": "1.5.0"}', None),
    )
    assert answer["status"] == "version-differs", answer
    assert answer["asked"] == "1.9.8", answer
    assert answer["found"] == "1.5.0", answer


def check_the_terraform_branch_reports_a_binary_it_could_not_run():
    answer = wfrun.provision(
        {"uses": "hashicorp/setup-terraform@v3", "with": {"terraform_version": "1.9.8"}},
        read_terraform=lambda: (None, "FileNotFoundError: terraform"),
    )
    assert answer["status"] == "tool-absent", answer
    assert "terraform" in answer["reason"], answer


def check_a_terraform_step_with_no_pin_is_satisfied_by_whatever_is_there():
    # The workflow always pins, and a step that stopped pinning would make
    # the comparison vacuous rather than failing, so the behaviour is named.
    answer = wfrun.provision(
        {"uses": "hashicorp/setup-terraform@v3"},
        read_terraform=lambda: ('{"terraform_version": "1.5.0"}', None),
    )
    assert answer["status"] == "already-satisfied", answer


def check_the_machine_record_names_this_interpreter_and_platform():
    where = wfrun.measured_on()
    assert where["python"] == "%d.%d.%d" % sys.version_info[:3], where
    assert where["platform"] == sys.platform, where
    assert "terraform" in where, where


def check_run_job_classifies_every_shape_of_step():
    """`run_job` was reachable only through the entry point.

    Five mutations inside its branch chain survived, because the only thing
    that had ever called it was the script that writes the manifest. The job
    below carries one step of each shape the workflow can hold.
    """
    job = {
        "steps": [
            {"uses": "actions/checkout@v4"},
            {"name": "runs", "run": "echo fine"},
            {"name": "nothing"},
            {"name": "expressive", "run": "echo ${{ github.sha }}"},
            {"name": "env only", "run": "echo fine", "env": {"X": "${{ vars.X }}"}},
        ]
    }
    steps = wfrun.run_job("transform", job, 30)
    assert [step["status"] for step in steps] == [
        "already-satisfied",
        "ran",
        "no-command",
        "needs-expression",
        "needs-expression",
    ], [(step["name"], step["status"]) for step in steps]
    assert [step["index"] for step in steps] == [0, 1, 2, 3, 4], steps
    assert steps[0]["name"] == "actions/checkout@v4", steps[0]


def check_run_job_holds_every_step_of_a_job_whose_if_is_false():
    job = {"if": False, "steps": [{"name": "never", "run": "exit 1"}]}
    steps = wfrun.run_job("clone", job, 30)
    assert [step["status"] for step in steps] == ["job-held-off"], steps
    assert steps[0]["reason"], steps[0]
    # And nothing ran, so there is no exit code to report.
    assert "exit_code" not in steps[0], steps[0]


def check_run_job_holds_every_step_of_a_self_referential_job():
    job = {"steps": [{"name": "the checks", "run": "exit 1"}]}
    for name in sorted(wfrun.SELF_REFERENTIAL):
        steps = wfrun.run_job(name, job, 30)
        assert [step["status"] for step in steps] == ["self-referential"], (name, steps)
        assert steps[0]["reason"] == wfrun.SELF_REFERENTIAL[name], steps[0]
