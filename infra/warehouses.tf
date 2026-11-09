# auto_suspend and resource_monitor are both optional on a warehouse. A
# warehouse with neither runs until somebody notices the bill, and it is the
# one resource in this configuration that costs money by existing.
resource "snowflake_warehouse" "loading" {
  name           = "SCREENING_LOAD_WH"
  warehouse_size = "XSMALL"
  comment        = "Registry loads. Bursty, so it suspends fast."

  auto_suspend = 60
  auto_resume  = "true"

  # A monthly screening cycle is one job. Scaling out would buy concurrency
  # nothing is asking for.
  min_cluster_count = 1
  max_cluster_count = 1

  resource_monitor             = snowflake_resource_monitor.screening.name
  statement_timeout_in_seconds = 3600
}

resource "snowflake_warehouse" "transforming" {
  name           = "SCREENING_XFORM_WH"
  warehouse_size = "SMALL"
  comment        = "The transformation models and the match tiers."

  auto_suspend = 120
  auto_resume  = "true"

  min_cluster_count = 1
  max_cluster_count = 1

  resource_monitor             = snowflake_resource_monitor.screening.name
  statement_timeout_in_seconds = 3600
}

# Pull request builds run against a clone, so they need a warehouse that is
# not the one a monthly cycle is using.
resource "snowflake_warehouse" "ci" {
  name           = "SCREENING_CI_WH"
  warehouse_size = "XSMALL"
  comment        = "Pull request builds against a zero copy clone."

  auto_suspend = 60
  auto_resume  = "true"

  min_cluster_count = 1
  max_cluster_count = 1

  resource_monitor             = snowflake_resource_monitor.screening.name
  statement_timeout_in_seconds = 1800
}
