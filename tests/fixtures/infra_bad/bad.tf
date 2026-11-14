# Every rule in screening/tfrules.py has to fire on this file. It is what
# stops a set of passing rules from being rules pointed at nothing.
#
# Almost every block here validates against the provider schema, and that is
# the argument for the module: the problem is what is not written and a schema
# check cannot see an absence. There is one exception and it was found on
# 2026-11-14 by running terraform validate over this file for the first time.
#
#   snowflake_grant_privileges_to_account_role.silent names neither privileges
#   nor all_privileges. validate rejects it with "one of all_privileges,
#   privileges must be specified", so the first arm of
#   grant_names_what_it_grants duplicates a check terraform already does.
#
# The block and the arm both stay. The suite runs on machines with no
# terraform on them, including the one that builds this repository, and a rule
# that only runs where the binary is installed is not the gate. What changed
# is this comment, which claimed the gap was total and it is not.
#
# snowflake_stage_external_s3.nowhere was also rejected, for a missing url,
# and that one was an oversight rather than a planted defect. It has a url
# now and the planted absences on it are the storage integration and the
# inline credentials.
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
  url      = "s3://bad-bucket/landing/"

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

# The access rules, added 2026-11-14. Every block below is accepted by
# terraform validate. The defect in each one is a thing that is not written.

# Complete, creatable, and pointed at by nothing. It would appear in SHOW
# MASKING POLICIES and mask no column anywhere.
resource "snowflake_masking_policy" "orphan" {
  database         = snowflake_database.no_retention.name
  schema           = snowflake_schema.no_retention.name
  name             = "BAD_MASK"
  return_data_type = "VARCHAR"

  argument {
    name = "VAL"
    type = "VARCHAR"
  }

  body = <<-SQL
    case when current_role() = 'BAD_ROLE' then val else null end
  SQL
}

resource "snowflake_row_access_policy" "orphan" {
  database = snowflake_database.no_retention.name
  schema   = snowflake_schema.no_retention.name
  name     = "BAD_ROWS"

  argument {
    name = "FACILITY_ID"
    type = "NUMBER"
  }

  body = <<-SQL
    facility_id = 1
  SQL
}

# Two conditional policies, one using clause, and no row filter. The second
# column reads whole for every role and the body of its policy references an
# argument nothing passes.
resource "snowflake_masking_policy" "conditional_one" {
  database         = snowflake_database.no_retention.name
  schema           = snowflake_schema.no_retention.name
  name             = "BAD_COND_ONE"
  return_data_type = "VARCHAR"

  argument {
    name = "VAL"
    type = "VARCHAR"
  }

  argument {
    name = "TIER_RANK"
    type = "NUMBER"
  }

  body = <<-SQL
    case when tier_rank = 1 then null else val end
  SQL
}

resource "snowflake_masking_policy" "conditional_two" {
  database         = snowflake_database.no_retention.name
  schema           = snowflake_schema.no_retention.name
  name             = "BAD_COND_TWO"
  return_data_type = "VARCHAR"

  argument {
    name = "VAL"
    type = "VARCHAR"
  }

  argument {
    name = "TIER_RANK"
    type = "NUMBER"
  }

  body = <<-SQL
    case when tier_rank = 2 then null else val end
  SQL
}

# No is_secure, no row_access_policy, and one using clause for two
# conditional policies. Three rules fire on this one block.
resource "snowflake_view" "leaky" {
  database  = snowflake_database.no_retention.name
  schema    = snowflake_schema.no_retention.name
  name      = "BAD_VIEW"
  statement = "select 1 as matched_npi, 2 as matched_fallback_key, 3 as tier_rank"

  column {
    column_name = "MATCHED_NPI"

    masking_policy {
      policy_name = snowflake_masking_policy.conditional_one.fully_qualified_name
      using       = ["MATCHED_NPI", "TIER_RANK"]
    }
  }

  column {
    column_name = "MATCHED_FALLBACK_KEY"

    masking_policy {
      policy_name = snowflake_masking_policy.conditional_two.fully_qualified_name
    }
  }
}

# Granted on an object and on no warehouse. Every statement this role runs
# fails before it reads anything, and the grant above it looks correct.
resource "snowflake_grant_privileges_to_account_role" "reader_with_no_warehouse" {
  account_role_name = snowflake_account_role.stranded.name
  privileges        = ["SELECT"]

  on_schema_object {
    object_type = "VIEW"
    object_name = snowflake_view.leaky.fully_qualified_name
  }
}

resource "snowflake_account_role" "stranded" {
  name = "BAD_READER"
}

# A reviewer granted select on the mapping that decides what they may read.
# The grant looks careful and it hands them every other reviewer's assignment.
resource "snowflake_table" "review_assignment" {
  database = snowflake_database.no_retention.name
  schema   = snowflake_schema.no_retention.name
  name     = "BAD_ASSIGNMENT"

  column {
    name = "ROLE_NAME"
    type = "VARCHAR(255)"
  }
}

resource "snowflake_account_role" "reviewer" {
  name = "BAD_REVIEWER"
}

resource "snowflake_grant_privileges_to_account_role" "reviewer_reads_the_mapping" {
  account_role_name = snowflake_account_role.reviewer.name
  privileges        = ["SELECT"]

  on_schema_object {
    object_type = "TABLE"
    object_name = snowflake_table.review_assignment.fully_qualified_name
  }
}
