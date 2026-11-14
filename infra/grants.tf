# privileges and all_privileges are both optional on this resource. A grant
# naming neither grants nothing and validates. One naming all_privileges
# grants everything and also validates. So every grant here names the
# privileges it means, and nothing in this file uses all_privileges.
resource "snowflake_grant_privileges_to_account_role" "loader_raw_usage" {
  account_role_name = snowflake_account_role.loader.name
  privileges        = ["USAGE"]

  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.raw.name
  }
}

# The loader writes tables and reads the stage. It does not create the stage or
# the pipe, because the deploy creates both and a pipe runs as its owner rather
# than as whoever loaded last. Granting CREATE STAGE here would let the loading
# identity point a new stage at somewhere nobody approved.
resource "snowflake_grant_privileges_to_account_role" "loader_registry_write" {
  account_role_name = snowflake_account_role.loader.name
  privileges        = ["USAGE", "CREATE TABLE"]

  on_schema {
    schema_name = "\"${snowflake_database.raw.name}\".\"${snowflake_schema.raw_registry.name}\""
  }
}

resource "snowflake_grant_privileges_to_account_role" "loader_stage_read" {
  account_role_name = snowflake_account_role.loader.name
  privileges        = ["USAGE"]

  on_schema_object {
    object_type = "STAGE"
    object_name = snowflake_stage_external_s3.registry.fully_qualified_name
  }
}

resource "snowflake_grant_privileges_to_account_role" "transformer_raw_read" {
  account_role_name = snowflake_account_role.transformer.name
  privileges        = ["USAGE"]

  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.raw.name
  }
}

# Future grants, because the loader creates tables after this runs and a
# transformer that can only read today's tables is a transformer that breaks
# the first time a registry gains one.
resource "snowflake_grant_privileges_to_account_role" "transformer_registry_select" {
  account_role_name = snowflake_account_role.transformer.name
  privileges        = ["SELECT"]

  on_schema_object {
    future {
      object_type_plural = "TABLES"
      in_schema          = "\"${snowflake_database.raw.name}\".\"${snowflake_schema.raw_registry.name}\""
    }
  }
}

resource "snowflake_grant_privileges_to_account_role" "transformer_analytics_write" {
  account_role_name = snowflake_account_role.transformer.name
  privileges        = ["USAGE", "CREATE SCHEMA"]

  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.analytics.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "analyst_analytics_usage" {
  account_role_name = snowflake_account_role.analyst.name
  privileges        = ["USAGE"]

  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.analytics.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "reviewer_analytics_usage" {
  account_role_name = snowflake_account_role.reviewer.name
  privileges        = ["USAGE"]

  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.analytics.name
  }
}

# The loader is the only role that touches the loading warehouse, and a role
# with no warehouse cannot run a statement at all.
resource "snowflake_grant_privileges_to_account_role" "loader_warehouse" {
  account_role_name = snowflake_account_role.loader.name
  privileges        = ["USAGE", "OPERATE"]

  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.loading.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "transformer_warehouse" {
  account_role_name = snowflake_account_role.transformer.name
  privileges        = ["USAGE", "OPERATE"]

  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.transforming.name
  }
}

# The analyst and the reviewer read the REVIEW schema and nothing else.
#
# Before today both held USAGE on the analytics database and SELECT on
# nothing, so both saw no rows anywhere and the comments on the roles
# described behaviour that was configured in no file. A role with usage on a
# database and no object grant is not a restricted reader, it is a reader of
# an empty catalogue.
#
# The grant is on the schema's views by name rather than on future views in
# the schema. A future grant would hand both roles any view a later day adds,
# and the whole point of this schema is that what lands in it carries a row
# filter. tfrules.py has a rule that fires when a view in here does not.
resource "snowflake_grant_privileges_to_account_role" "analyst_review_usage" {
  account_role_name = snowflake_account_role.analyst.name
  privileges        = ["USAGE"]

  on_schema {
    schema_name = "\"${snowflake_database.analytics.name}\".\"${snowflake_schema.analytics_review.name}\""
  }
}

resource "snowflake_grant_privileges_to_account_role" "reviewer_review_usage" {
  account_role_name = snowflake_account_role.reviewer.name
  privileges        = ["USAGE"]

  on_schema {
    schema_name = "\"${snowflake_database.analytics.name}\".\"${snowflake_schema.analytics_review.name}\""
  }
}

resource "snowflake_grant_privileges_to_account_role" "analyst_queue_select" {
  account_role_name = snowflake_account_role.analyst.name
  privileges        = ["SELECT"]

  on_schema_object {
    object_type = "VIEW"
    object_name = snowflake_view.review_queue.fully_qualified_name
  }
}

resource "snowflake_grant_privileges_to_account_role" "analyst_candidate_select" {
  account_role_name = snowflake_account_role.analyst.name
  privileges        = ["SELECT"]

  on_schema_object {
    object_type = "VIEW"
    object_name = snowflake_view.match_candidate.fully_qualified_name
  }
}

resource "snowflake_grant_privileges_to_account_role" "reviewer_queue_select" {
  account_role_name = snowflake_account_role.reviewer.name
  privileges        = ["SELECT"]

  on_schema_object {
    object_type = "VIEW"
    object_name = snowflake_view.review_queue.fully_qualified_name
  }
}

resource "snowflake_grant_privileges_to_account_role" "reviewer_candidate_select" {
  account_role_name = snowflake_account_role.reviewer.name
  privileges        = ["SELECT"]

  on_schema_object {
    object_type = "VIEW"
    object_name = snowflake_view.match_candidate.fully_qualified_name
  }
}

# No grant on the reviewer to facility mapping, and that is the point.
#
# This file had one for most of the day and it was an over grant. A reviewer
# with select on that table reads which facilities every other reviewer is
# assigned, which is a question their job does not ask.
#
# It was written because the policy body queries the table and a role with no
# privilege on a table it queries would read nothing. That premise is wrong.
# Snowflake evaluates a row access policy expression using the role of the
# policy owner rather than the role that ran the query, and its own page says
# the consequence directly: the query operator does not require access to the
# mapping tables in the row access policy.
#
#   https://docs.snowflake.com/en/user-guide/security-row-intro
#
# The exempt role list below is granted, and the difference is deliberate. The
# same page says nothing about a masking policy body querying a table, and the
# masking pages were not read, so that half is unverified here. The exempt
# list is a list of role names with no personal data in it, so granting select
# on it costs nothing and makes the mask bodies work under either semantic.
# The assignment mapping is the one that would cost something, so it stays
# ungranted and rests on a sentence that was read rather than observed.
resource "snowflake_grant_privileges_to_account_role" "analyst_exempt_list_select" {
  account_role_name = snowflake_account_role.analyst.name
  privileges        = ["SELECT"]

  on_schema_object {
    object_type = "TABLE"
    object_name = snowflake_table.policy_exempt_role.fully_qualified_name
  }
}

resource "snowflake_grant_privileges_to_account_role" "reviewer_exempt_list_select" {
  account_role_name = snowflake_account_role.reviewer.name
  privileges        = ["SELECT"]

  on_schema_object {
    object_type = "TABLE"
    object_name = snowflake_table.policy_exempt_role.fully_qualified_name
  }
}

# Both reading roles need a warehouse. Neither had one, which on its own would
# have made every query they ran fail with no object to point at.
resource "snowflake_grant_privileges_to_account_role" "analyst_warehouse" {
  account_role_name = snowflake_account_role.analyst.name
  privileges        = ["USAGE"]

  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.reporting.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "reviewer_warehouse" {
  account_role_name = snowflake_account_role.reviewer.name
  privileges        = ["USAGE"]

  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.reporting.name
  }
}
