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
