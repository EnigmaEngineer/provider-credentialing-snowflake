resource "snowflake_storage_integration_aws" "registry_landing" {
  name                      = "SCREENING_REGISTRY_LANDING"
  enabled                   = true
  storage_provider          = "S3"
  storage_aws_role_arn      = var.storage_aws_role_arn
  storage_allowed_locations = [var.registry_landing_url]

  comment = "Reads the registry landing prefix and nothing else."
}

# The file format is where two measurements on the real files turn into
# configuration. Both of these are optional arguments, and the defaults are
# wrong for this data in different ways.
#
# Eleven rows of the 3,030,022 in the Medicare enrollment extract carry
# cp1252 bytes. Snowflake reads a CSV as UTF8 unless told otherwise, so the
# default aborts the load on row eleven out of three million. Setting
# replace_invalid_characters instead would finish the load and replace the
# character, and the field it lands in is a provider name, which is what the
# fallback match tiers compare. A damaged name does not match and does not
# raise, so that option stays off on purpose.
resource "snowflake_file_format_csv" "enrollment" {
  database = snowflake_database.raw.name
  schema   = snowflake_schema.raw_registry.name
  name     = "ENROLLMENT_CSV"

  encoding                       = "WINDOWS1252"
  replace_invalid_characters     = false
  error_on_column_count_mismatch = true
  skip_header                    = 1
  field_optionally_enclosed_by   = "\""

  # The exclusion list writes its absences as values. The NPI column holds the
  # character zero on 75,169 of 84,093 records, and three records carry the
  # four letter string NULL as a surname. Handing those strings to the loader
  # as null markers would delete data that is already telling us something, so
  # the list is deliberately empty and the readers decide what an absence is.
  null_if = []

  # Leading and trailing space in a name is a property of the source file and
  # the match tiers need to see it rather than have it quietly removed here.
  trim_space = false

  comment = "Reads the Medicare enrollment extract. Encoding is not UTF8 and that is measured, not assumed."
}

resource "snowflake_file_format_csv" "exclusions" {
  database = snowflake_database.raw.name
  schema   = snowflake_schema.raw_registry.name
  name     = "EXCLUSIONS_CSV"

  # The exclusion list is UTF8 with a byte order mark.
  encoding                       = "UTF8"
  skip_byte_order_mark           = true
  replace_invalid_characters     = false
  error_on_column_count_mismatch = true
  skip_header                    = 1
  field_optionally_enclosed_by   = "\""
  null_if                        = []
  trim_space                     = false

  comment = "Reads the OIG exclusion list."
}

# The generic snowflake_stage resource is deprecated in this provider version
# and it says so during validate, naming the five replacements. This is the
# external S3 one, and it requires url, so the stage that points at nothing is
# not expressible here. The credentials block is still optional and this
# configuration never writes one, because an inline key in a Terraform file is
# a key in version control.
resource "snowflake_stage_external_s3" "registry" {
  database = snowflake_database.raw.name
  schema   = snowflake_schema.raw_registry.name
  name     = "REGISTRY_LANDING"

  url                 = var.registry_landing_url
  storage_integration = snowflake_storage_integration_aws.registry_landing.name

  file_format {
    format_name = snowflake_file_format_csv.exclusions.fully_qualified_name
  }

  comment = "Where the registry files land."
}

# auto_ingest defaults to false. A pipe without it is a pipe somebody has to
# poke, which is not the thing the design asked for and reads identically in
# the file. The notification integration it needs does not exist until the
# landing bucket does, so this is the one resource here whose plan would fail
# today for a reason other than the missing account.
resource "snowflake_pipe" "exclusions" {
  database = snowflake_database.raw.name
  schema   = snowflake_schema.raw_registry.name
  name     = "EXCLUSIONS_PIPE"

  auto_ingest = true

  copy_statement = <<-COPY
    copy into ${snowflake_database.raw.name}.${snowflake_schema.raw_registry.name}.leie_raw
    from @${snowflake_database.raw.name}.${snowflake_schema.raw_registry.name}.${snowflake_stage_external_s3.registry.name}
    pattern = '.*leie_updated[.]csv'
    file_format = (format_name = ${snowflake_file_format_csv.exclusions.fully_qualified_name})
    on_error = 'abort_statement'
  COPY

  comment = "Loads the exclusion list on file arrival."
}
