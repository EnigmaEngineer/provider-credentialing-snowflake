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
