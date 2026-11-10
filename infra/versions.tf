terraform {
  required_version = ">= 1.9.0"

  required_providers {
    snowflake = {
      source  = "snowflakedb/snowflake"
      version = "2.23.0"
    }

    fivetran = {
      source  = "fivetran/fivetran"
      version = "1.9.55"
    }
  }
}
