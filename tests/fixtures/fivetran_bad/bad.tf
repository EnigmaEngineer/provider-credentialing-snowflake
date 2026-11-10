# Written to be broken. Every rule in credentialing/ftrules.py has to fire on
# this file, which is what stops a set of passing rules from being a set of
# rules pointed at nothing. Nothing deploys from it.
#
# Every resource below validates against the provider schema. That is the
# point. Each one is a capability configured so that it does not happen.

resource "fivetran_group" "bad" {
  name = "bad"
}

# The untyped resource. Its whole service configuration is one string the
# provider never reads back.
resource "fivetran_connection" "untyped" {
  group_id = fivetran_group.bad.id
  service  = "postgres"
  config   = "{}"
}

# A connector that names no source and no update method. It carries an inline
# password in a nested block, which is where one would actually be written.
resource "fivetran_connector" "hollow" {
  group_id = fivetran_group.bad.id
  service  = "postgres"

  config {
    password = "not a real password and still committed"
  }
}

# A schedule that decides nothing.
resource "fivetran_connector_schedule" "hollow" {
  connector_id = fivetran_connector.hollow.id
  schedule_type = "auto"
}

# A schema config that lets a new column in without anyone allowing it.
resource "fivetran_connector_schema_config" "hollow" {
  connector_id = fivetran_connector.hollow.id

  schema {
    name    = "credentialing"
    enabled = true
  }
}

# A destination with no warehouse and no role, so the load runs as whatever
# default the user has.
resource "fivetran_destination" "hollow" {
  group_id         = fivetran_group.bad.id
  service          = "snowflake"
  time_zone_offset = "0"

  config {
    host = "example.snowflakecomputing.com"
  }
}
