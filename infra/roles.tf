# Four roles because four groups of people and processes do different things.
# A role is only a name until something is granted to it, and the grants are
# in grants.tf for that reason rather than for tidiness.
resource "snowflake_account_role" "loader" {
  name    = "SCREENING_LOADER"
  comment = "Writes the raw layer. Reads nothing in analytics."
}

resource "snowflake_account_role" "transformer" {
  name    = "SCREENING_TRANSFORMER"
  comment = "Reads raw, writes analytics."
}

resource "snowflake_account_role" "analyst" {
  name    = "SCREENING_ANALYST"
  comment = "Reads the marts. Sees identifiers redacted."
}

resource "snowflake_account_role" "reviewer" {
  name    = "SCREENING_REVIEWER"
  comment = "Works the review queue. Sees identifiers whole, for their own facility only."
}
