# rsa_public_key is optional on a service user. A service user created without
# one authenticates with a password, which is the thing key pair authentication
# was chosen to avoid, and nothing about the file says so. The key here is a
# public key, which is not a secret. No private key is generated, stored or
# read anywhere in this repository.
resource "snowflake_service_user" "loader" {
  name         = "SCREENING_LOADER_SVC"
  comment      = "Runs the registry loads."
  display_name = "Screening loader"

  rsa_public_key = var.loader_rsa_public_key

  default_role      = snowflake_account_role.loader.name
  default_warehouse = snowflake_warehouse.loading.name

  # A service user that can hold a session open forever is a service user whose
  # revocation takes effect whenever it feels like it.
  client_session_keep_alive = false

  disabled = false
}

resource "snowflake_grant_privileges_to_account_role" "loader_svc_role" {
  account_role_name = snowflake_account_role.loader.name
  privileges        = ["USAGE"]

  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.ci.name
  }
}
