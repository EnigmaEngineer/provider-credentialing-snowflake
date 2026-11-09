# Every rule in screening/tfrules.py has to fire on this file. It is what
# stops ten passing rules from being ten rules pointed at nothing. Each block
# here validates against the provider schema, which is the whole point: the
# problem is what is not written, and no schema check can see that.
#
# Deliberately broken. Nothing deploys from this directory.

provider "snowflake" {
  # It names no organization and no account. It names no user and no
  # authenticator either. An apply picks up whatever configuration file
  # happens to sit on the machine.
  role = "SYSADMIN"
}

resource "snowflake_warehouse" "unbounded" {
  name           = "BAD_WH"
  warehouse_size = "XSMALL"
}

resource "snowflake_resource_monitor" "toothless" {
  name = "BAD_MONITOR"
}

resource "snowflake_database" "no_retention" {
  name = "BAD_DB"
}

resource "snowflake_schema" "no_retention" {
  database = snowflake_database.no_retention.name
  name     = "BAD_SCHEMA"
}

resource "snowflake_service_user" "password_please" {
  name = "BAD_SVC"
}

resource "snowflake_pipe" "manual" {
  database       = snowflake_database.no_retention.name
  schema         = snowflake_schema.no_retention.name
  name           = "BAD_PIPE"
  copy_statement = "copy into t from @s"
}

resource "snowflake_stage_external_s3" "nowhere" {
  database = snowflake_database.no_retention.name
  schema   = snowflake_schema.no_retention.name
  name     = "BAD_STAGE"

  credentials {
    aws_key_id = "set-from-a-variable-somewhere"
  }
}

resource "snowflake_file_format_csv" "defaults" {
  database = snowflake_database.no_retention.name
  schema   = snowflake_schema.no_retention.name
  name     = "BAD_CSV"
}

resource "snowflake_grant_privileges_to_account_role" "silent" {
  account_role_name = "BAD_ROLE"

  on_account_object {
    object_type = "DATABASE"
    object_name = "BAD_DB"
  }
}

resource "snowflake_grant_privileges_to_account_role" "everything" {
  account_role_name = "BAD_ROLE"
  all_privileges    = true

  on_account_object {
    object_type = "DATABASE"
    object_name = "BAD_DB"
  }
}
