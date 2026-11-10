"""Checks on the workflow file.

Nothing here executes it. These read the names it calls and the values it
passes, which is what an author gets wrong from memory. They cannot see
whether the state one step leaves is the state the next one needs, and that is
the defect a workflow file usually has. The README says so rather than letting
a passing suite imply otherwise.
"""

import os

import yaml

from screening import tfread

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "ci.yml")
INFRA = os.path.join(ROOT, "infra")


def workflow():
    with open(WORKFLOW, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def all_run_text(job):
    return "\n".join(
        step["run"] for step in job.get("steps", []) if isinstance(step.get("run"), str)
    )


def check_the_workflow_parses_and_has_the_three_jobs():
    wf = workflow()
    assert set(wf["jobs"]) == {"suite", "configuration", "deploy"}, sorted(wf["jobs"])


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


def check_the_deploy_job_is_held_off():
    # It has no identity to assume. A job left enabled would fail on every
    # push and be switched off by whoever got tired of it first.
    deploy = workflow()["jobs"]["deploy"]
    assert deploy.get("if") is False, deploy.get("if")


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
