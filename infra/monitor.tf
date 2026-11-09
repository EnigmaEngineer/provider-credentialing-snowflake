# The budget alert. Every argument on this resource except the name is
# optional, so a monitor declared with just a name has no quota, no triggers
# and no recipients, and both terraform validate and a rendered plan are happy
# with it. Each element below is named because leaving it out is the whole
# failure, not because the value is unusual.
resource "snowflake_resource_monitor" "screening" {
  name = "SCREENING_MONITOR"

  credit_quota = var.monthly_credit_quota

  # frequency and start_timestamp are both listed as optional attributes and
  # the provider refuses either one alone. The pairing is stated in the
  # description text inside the schema rather than in its required flag, so
  # reading the field list is not the same as reading the schema. IMMEDIATELY
  # is a documented special value, which keeps a date out of a committed file.
  frequency       = "MONTHLY"
  start_timestamp = "IMMEDIATELY"

  # Warning first, then stop accepting new work, then kill what is running.
  # Without notify_triggers the monitor silently suspends at the suspend
  # trigger and the first anybody hears of it is a failed query.
  notify_triggers           = [60, 80]
  suspend_trigger           = 95
  suspend_immediate_trigger = 100

  notify_users = var.cost_alert_recipients
}
