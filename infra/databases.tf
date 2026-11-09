# data_retention_time_in_days is optional, so a database declared without it
# takes the account default. On Standard edition that default is one day. A
# credentialing decision has to be explainable later than that, so the number
# is named rather than inherited.
resource "snowflake_database" "raw" {
  name    = "SCREENING_RAW"
  comment = "Registry files and the replicated credentialing application, as landed."

  data_retention_time_in_days = 7

  # The loader writes into named schemas. A public schema nobody owns is a
  # place for a table nobody meant to create.
  drop_public_schema_on_creation = true
}

resource "snowflake_database" "analytics" {
  name    = "SCREENING_ANALYTICS"
  comment = "Staging, intermediate and mart models, plus the review queue."

  data_retention_time_in_days    = 7
  drop_public_schema_on_creation = true
}

resource "snowflake_schema" "raw_registry" {
  database = snowflake_database.raw.name
  name     = "REGISTRY"
  comment  = "NPPES, the exclusion list and the Medicare enrollment extract."

  data_retention_time_in_days = 7
  with_managed_access         = true
}

resource "snowflake_schema" "raw_credentialing" {
  database = snowflake_database.raw.name
  name     = "CREDENTIALING"
  comment  = "The synthetic credentialing application, replicated."

  data_retention_time_in_days = 7
  with_managed_access         = true
}
