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

# The reading roles get their own warehouse rather than the transforming one.
# A reviewer opening the queue while the monthly cycle is running would queue
# behind it on a shared warehouse, and the reason to separate them is that the
# cycle is a batch and a review is somebody waiting.
#
# Two clusters here and one everywhere else. This is the only warehouse with
# more than one person on it at a time, and a second cluster is what stops a
# long query holding up a short one. The ceiling is two rather than more
# because nothing has measured the concurrency and a number nobody measured
# should be the smallest one that does the job.
resource "snowflake_warehouse" "reporting" {
  name           = "SCREENING_REPORT_WH"
  warehouse_size = "XSMALL"
  comment        = "The review queue and the counts over it. Interactive rather than batch."

  auto_suspend = 60
  auto_resume  = "true"

  min_cluster_count = 1
  max_cluster_count = 2

  resource_monitor             = snowflake_resource_monitor.screening.name
  statement_timeout_in_seconds = 600
}
