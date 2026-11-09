# Every argument on this provider is optional, including the account and the
# user. A provider block with nothing in it validates, and an apply then falls
# back to whatever sits in the TOML config file on the machine running it. For
# a deploy that is supposed to run as one named identity that is the wrong
# failure, because it succeeds as the wrong one. So the three that decide who
# is connecting are named here and come from variables with no defaults.
#
# TODO: nothing has been applied. There is no Snowflake account identifier and
# no CI user for this project yet, so the deploy workflow has nothing to
# authenticate as and these files have only ever been validated and formatted.
# They are correct against the provider schema and unproven against an account.
provider "snowflake" {
  organization_name = var.organization_name
  account_name      = var.account_name
  user              = var.ci_user_name

  # Workload identity rather than a key pair, so no long lived secret exists
  # for the deploy at all. The provider reads the token out of the file named
  # by SNOWFLAKE_TOKEN_FILE_PATH, which the workflow writes from the identity
  # token the runner is issued. token_file_path is deliberately not set here,
  # because a path in a committed file is a path somebody has to keep true.
  #
  # Whether Snowflake's OIDC workload identity accepts the runner's issuer has
  # not been verified. There is no account to try it against.
  authenticator              = "WORKLOAD_IDENTITY"
  workload_identity_provider = "OIDC"

  role = var.deploy_role_name

  # Not one of the warehouses below. Pointing the provider at a warehouse this
  # configuration creates is a cycle, because the provider has to connect
  # before it can create anything, and terraform validate refuses it outright.
  # The deploy runs on a warehouse that already exists.
  warehouse = var.deploy_warehouse_name
}
