variable "organization_name" {
  description = "Snowflake organization name. No default, because a default here is a real account somebody did not choose."
  type        = string
}

variable "account_name" {
  description = "Snowflake account name within the organization."
  type        = string
}

variable "ci_user_name" {
  description = "The service user the deploy connects as."
  type        = string
}

variable "deploy_role_name" {
  description = "The role the deploy assumes. Separate from the roles this configuration creates."
  type        = string
  default     = "SYSADMIN"
}

variable "deploy_warehouse_name" {
  description = "An existing warehouse the deploy connects on. It cannot be one of the warehouses this configuration creates."
  type        = string
}

variable "monthly_credit_quota" {
  description = "Credits the screening account may spend in a month before the monitor acts."
  type        = number
}

variable "registry_landing_url" {
  description = "Cloud storage prefix the registry files land in, read by the external stage."
  type        = string
}

variable "storage_aws_role_arn" {
  description = "Role the storage integration assumes to read the landing prefix."
  type        = string
}

variable "loader_rsa_public_key" {
  description = "Public key for the loading service user. A public key is not a secret and a password would be."
  type        = string
}

variable "cost_alert_recipients" {
  description = "Snowflake users the resource monitor notifies. An empty list is a monitor that tells nobody."
  type        = list(string)

  validation {
    condition     = length(var.cost_alert_recipients) > 0
    error_message = "A credit monitor with no recipients suspends a warehouse and notifies nobody."
  }
}

variable "snowflake_host" {
  description = "Snowflake host the replication destination connects to. The account identifier with the Snowflake domain after it."
  type        = string
}

variable "raw_database" {
  description = "The database the replication lands in. Separate from the analytics database on purpose."
  type        = string
}

variable "loading_warehouse" {
  description = "The warehouse the replication runs its loads on. Named rather than left to a user default."
  type        = string
}

variable "fivetran_snowflake_user" {
  description = "The Snowflake service user the replication writes as."
  type        = string
}

variable "fivetran_snowflake_role" {
  description = "The role that service user assumes. Without it the replication takes whatever default role the user has."
  type        = string
}

variable "credentialing_host" {
  description = "Host of the credentialing application's own database."
  type        = string
}

variable "credentialing_database" {
  description = "Database name in the credentialing application."
  type        = string
}

variable "fivetran_postgres_user" {
  description = "The Postgres user the replication reads as. It needs replication rights and nothing more."
  type        = string
}
