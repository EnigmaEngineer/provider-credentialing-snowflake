# A planted copy of the namespace defects this repository carried for six
# days, so the rules that now refuse them can be shown to refuse something.
# Every defect here was real in the live tree on 2026-11-16.
variable "organization_name" {
  type = string
}

variable "monthly_credit_quota" {
  type = number
}

variable "deploy_role_name" {
  type    = string
  default = "SCREENING_DEPLOY"
}

resource "snowflake_warehouse" "transforming" {
  name              = "SCREENING_XFORM_WH"
  warehouse_size    = "SMALL"
  auto_suspend      = 120
  max_cluster_count = 1
}

resource "snowflake_account_role" "transformer" {
  name = "SCREENING_TRANSFORMER"
}

resource "snowflake_database" "analytics" {
  name = "SCREENING_ANALYTICS"
}
