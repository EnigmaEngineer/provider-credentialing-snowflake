# Replicating the credentialing application into the raw layer.
#
# Nothing here has been applied. There is no Fivetran account for this project
# and no Snowflake account either. Read it as configuration under the same gate
# as the rest of infra/ and not as something that ran.
#
# Two things about this provider shaped the file.
#
# The fivetran_connection resource takes its service settings as one
# JSON encoded string that the provider does not read back. That means
# terraform validate cannot grade a single Postgres setting and terraform plan
# cannot see drift on any of them. fivetran_connector takes the same settings
# as a typed block instead, so that is the resource used here. The cost is the
# older resource name.
#
# The typed block marks almost every field optional. So the rules in
# credentialing/ftrules.py fire on the fields being absent rather than on their
# values, the same way the warehouse rules work.

resource "fivetran_group" "screening" {
  name = "provider_screening"
}

resource "fivetran_destination" "warehouse" {
  group_id         = fivetran_group.screening.id
  service          = "snowflake"
  time_zone_offset = "0"
  run_setup_tests  = false

  config {
    host     = var.snowflake_host
    database = var.raw_database
    auth     = "KEY_PAIR"
    user     = var.fivetran_snowflake_user
    role     = var.fivetran_snowflake_role

    # The warehouse Fivetran runs its loads on. Named rather than left to the
    # user's default, because a load that picks up whatever default is set
    # spends from a monitor nobody pointed at it.
    default_virtual_warehouse = var.loading_warehouse
  }
}

resource "fivetran_connector" "credentialing" {
  group_id        = fivetran_group.screening.id
  service         = "postgres"
  run_setup_tests = false

  destination_schema {
    # Every table from this connector lands under this one prefix. The raw
    # layer has registry files arriving by pipe as well, so the two have to be
    # separable by name alone.
    prefix = "credentialing"
  }

  config {
    host     = var.credentialing_host
    port     = 5432
    database = var.credentialing_database
    user     = var.fivetran_postgres_user

    # Directly rather than omitted. Omitting it means the value is inferred
    # from whether a tunnel host happens to be set, so the connection method
    # would be decided by the presence of another field.
    connection_type = "Directly"

    # WAL_PGOUTPUT reads the write ahead log through a logical slot. The other
    # supported value is QUERY_BASED, which finds changed rows through the xmin
    # and ctid system columns and so cannot see a row between two syncs.
    #
    # What neither value controls is what a delete carries. That is decided by
    # the source table's replica identity, which appears in no field here and
    # in no Fivetran setting at all. The measurement is in
    # measurements/replication.json and the choice it drove is in
    # credentialing/schema.sql.
    update_method    = "WAL_PGOUTPUT"
    replication_slot = "fivetran_credentialing"
    publication_name = "credentialing_pub"
  }
}

resource "fivetran_connector_schedule" "credentialing" {
  connector_id = fivetran_connector.credentialing.id

  # Set rather than omitted. An omitted frequency takes the account default and
  # the screening cycle is monthly, so a connector syncing once a day is paying
  # for twenty nine syncs nobody reads.
  sync_frequency  = "1440"
  schedule_type   = "manual"
  daily_sync_time = "02:00"

  # False and written down. A connector left paused replicates nothing and
  # every model over it returns no rows, which reads downstream exactly like a
  # source that is genuinely empty.
  paused            = false
  pause_after_trial = false
}

resource "fivetran_connector_schema_config" "credentialing" {
  connector_id = fivetran_connector.credentialing.id

  # BLOCK_ALL rather than omitted. The default lets a column added to the
  # credentialing application arrive in the warehouse on the next sync. This
  # source holds dates of birth beside names, which is the pair the masking
  # policies exist for, so a new column has to be allowed in by someone.
  schema_change_handling = "BLOCK_ALL"

  schema {
    name    = "credentialing"
    enabled = true

    table {
      name    = "provider"
      enabled = true
    }

    table {
      name    = "application"
      enabled = true
    }

    table {
      name    = "license"
      enabled = true
    }

    table {
      name    = "committee_decision"
      enabled = true
    }

    table {
      name    = "verification"
      enabled = true
    }

    table {
      name    = "facility"
      enabled = true
    }
  }
}

# TODO: this configuration has never been planned or applied. It needs a
# Fivetran account, an API key pair for the Terraform provider, a Snowflake
# account identifier and a key pair for the Fivetran service user. None of
# those exist for this project. The deploy job in .github/workflows/ci.yml
# stays disabled until they do.
#
# TODO: the typed table block above cannot express a blocked column. It carries
# a name and an enabled flag and nothing else, so excluding date_of_birth from
# the replication is not sayable here. The only route the provider offers is
# the schemas_json field, which is the same untyped string this file avoided by
# not using fivetran_connection. Decide between a column that replicates and a
# configuration nothing can grade.
