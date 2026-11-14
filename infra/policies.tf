# Masking policies, one row access policy, and the views that carry them.
#
# The enforcement layer is a schema of its own and the reason is ownership.
# A row access policy can be attached to a view or to an iceberg table in this
# provider and to nothing else. Read out of terraform providers schema -json
# for snowflakedb/snowflake 2.23.0: snowflake_view carries a row_access_policy
# block and snowflake_table carries no such block at any nesting level. So the
# raw layer cannot be row filtered declaratively at all, and the relations the
# models build are dbt views, which dbt creates and drops on every run.
#
# Terraform declaring a view dbt also declares is two owners for one object.
# So the models stay granted to the transformer alone, and the roles a person
# or a dashboard uses read secure views in REVIEW that Terraform owns. That is
# one more layer than the obvious design and it is the only one that is
# expressible.
#
# The bodies are written for the account and nothing here has one. terraform
# validate grades the arguments and never the SQL inside body, so the rules in
# screening/tfrules.py grade the things validate is silent about and the
# design the bodies implement is stated in screening/access.py and measured in
# measurements/access.json.

resource "snowflake_schema" "analytics_review" {
  database = snowflake_database.analytics.name
  name     = "REVIEW"
  comment  = "Secure views the analyst and the reviewer read. The only schema either role is granted."

  data_retention_time_in_days = 7
  with_managed_access         = true
}

# Which facilities a reviewer works. The row access policy body reads this, so
# it has to exist before any policy is attached.
#
# The rows are the deploy's job rather than Terraform's, because a reviewer
# joining is an operational event and not a configuration change. The cost is
# a bootstrap state: an empty mapping gives every reviewer the unscoped rows
# and nothing else. That is a visible empty queue rather than a silent full
# one, which is the right way round, and it is in the README limitations.
resource "snowflake_table" "review_assignment" {
  database = snowflake_database.analytics.name
  schema   = snowflake_schema.analytics_review.name
  name     = "REVIEW_ASSIGNMENT"
  comment  = "One row per reviewer role and facility they may read."

  data_retention_time_in_days = 7

  column {
    name     = "ROLE_NAME"
    type     = "VARCHAR(255)"
    nullable = false
  }

  column {
    name     = "FACILITY_ID"
    type     = "NUMBER(38,0)"
    nullable = false
  }
}

# The roles every policy here lets through, said once.
#
# The list used to be an inline set in each of the five bodies. Five copies of
# one fact, and adding a role meant editing five policies and hoping. The
# prose gate is what forced the look: a four element SQL list inside a heredoc
# trips the comma rule and there is no spelling of it that passes, which is
# the 2026-11-09 note. The fix it pushed toward was better than the thing it
# refused.
#
# The transformer because it builds these relations and a mask on its reads
# would mask the inputs of every model downstream. The deploy role because it
# creates the policies. The reviewer is exempt from the masks and not from the
# row filter, so it is in the mask list below and not in this one.
resource "snowflake_table" "policy_exempt_role" {
  database = snowflake_database.analytics.name
  schema   = snowflake_schema.analytics_review.name
  name     = "POLICY_EXEMPT_ROLE"
  comment  = "One row per role that reads past every policy in this schema."

  data_retention_time_in_days = 7

  column {
    name     = "ROLE_NAME"
    type     = "VARCHAR(255)"
    nullable = false
  }

  column {
    name     = "READS_NAMES_WHOLE"
    type     = "BOOLEAN"
    nullable = false
  }
}

# A ten digit identifier, returned as the last four and nothing else. Not a
# constant, because a column of identical values cannot be grouped or counted
# distinctly and an analyst asking how many providers a record reached would
# get one.
resource "snowflake_masking_policy" "identifier" {
  database              = snowflake_database.analytics.name
  schema                = snowflake_schema.analytics_review.name
  name                  = "MASK_IDENTIFIER"
  comment               = "The last four digits of a provider identifier. Readable by the roles that decide."
  return_data_type      = "VARCHAR"
  exempt_other_policies = "false"

  argument {
    name = "VAL"
    type = "VARCHAR"
  }

  body = <<-SQL
    case
      when exists (
        select 1 from screening_analytics.review.policy_exempt_role r
        where r.role_name = current_role() and r.reads_names_whole
      )
        then val
      when val is null then null
      else '******' || right(val, 4)
    end
  SQL
}

resource "snowflake_masking_policy" "name_part" {
  database              = snowflake_database.analytics.name
  schema                = snowflake_schema.analytics_review.name
  name                  = "MASK_NAME_PART"
  comment               = "A surname or a given name, withheld from roles that only count."
  return_data_type      = "VARCHAR"
  exempt_other_policies = "false"

  argument {
    name = "VAL"
    type = "VARCHAR"
  }

  body = <<-SQL
    case
      when exists (
        select 1 from screening_analytics.review.policy_exempt_role r
        where r.role_name = current_role() and r.reads_names_whole
      )
        then val
      else null
    end
  SQL
}

resource "snowflake_masking_policy" "birth_date" {
  database              = snowflake_database.analytics.name
  schema                = snowflake_schema.analytics_review.name
  name                  = "MASK_BIRTH_DATE"
  comment               = "A date of birth, returned as the year for roles that only count."
  return_data_type      = "DATE"
  exempt_other_policies = "false"

  argument {
    name = "VAL"
    type = "DATE"
  }

  body = <<-SQL
    case
      when exists (
        select 1 from screening_analytics.review.policy_exempt_role r
        where r.role_name = current_role() and r.reads_names_whole
      )
        then val
      when val is null then null
      else date_from_parts(year(val), 1, 1)
    end
  SQL
}

# The two conditional ones, and they are the whole reason this file is longer
# than it looks like it should be.
#
# matched_npi is the identifier of the record a tier reached. On a first tier
# row the join is an equality against the provider's own identifier, so the
# column is the provider's identifier under a different name. Measured at
# 41 of 41 pairs in measurements/access.json. On the other tiers it names a
# different person's record and a reviewer needs it.
#
# A policy that masks the column outright is correct and costs the reader the
# record identifier on every row. The conditional form takes the deciding
# column as a second argument, which is in the using list on the view, so the
# answer can be per row. That is the field the provider schema describes rather
# than lists, and the flags beside it say only that it is optional.
resource "snowflake_masking_policy" "matched_identifier" {
  database              = snowflake_database.analytics.name
  schema                = snowflake_schema.analytics_review.name
  name                  = "MASK_MATCHED_IDENTIFIER"
  comment               = "The matched record's identifier, withheld on the tier where it is the provider's own."
  return_data_type      = "VARCHAR"
  exempt_other_policies = "false"

  argument {
    name = "VAL"
    type = "VARCHAR"
  }

  argument {
    name = "TIER_RANK"
    type = "NUMBER"
  }

  body = <<-SQL
    case
      when exists (
        select 1 from screening_analytics.review.policy_exempt_role r
        where r.role_name = current_role() and r.reads_names_whole
      )
        then val
      when tier_rank = 1 then null
      else val
    end
  SQL
}

# The same shape and a wider condition. The second tier key is the provider's
# surname, given name and date of birth with pipes between them, so the column
# is the whole identity. Measured at 61 of 61 pairs.
#
# The third tier is in the condition because the measurement put it there. The
# condition was written as the second tier alone, which is what reading the
# join that forms the key gives you. The third tier joins on the surname and
# the given name, and publishes the same key, so it gives back two of the three
# fields on 51 of 51 pairs. Two of three is a person in a file of this size.
resource "snowflake_masking_policy" "matched_fallback_key" {
  database              = snowflake_database.analytics.name
  schema                = snowflake_schema.analytics_review.name
  name                  = "MASK_MATCHED_FALLBACK_KEY"
  comment               = "The matched record's name key, withheld on the tiers where it is the provider's own."
  return_data_type      = "VARCHAR"
  exempt_other_policies = "false"

  argument {
    name = "VAL"
    type = "VARCHAR"
  }

  argument {
    name = "TIER_RANK"
    type = "NUMBER"
  }

  body = <<-SQL
    case
      when exists (
        select 1 from screening_analytics.review.policy_exempt_role r
        where r.role_name = current_role() and r.reads_names_whole
      )
        then val
      when tier_rank in (2, 3) then null
      else val
    end
  SQL
}

# One policy on the facility, and the third branch is the decision.
#
# A reviewer reads the facilities they are assigned. A provider with no live
# application has no facility, so a body with only the first two branches
# reaches them from no reviewer at all. That is the same disappearance as the
# state tier being unable to reach a provider with no licence, recorded on
# 2026-11-12, and it is worse here because the row is in the queue and nobody
# is assigned to it.
#
# So an unscoped row goes to every reviewer. The cost is duplicated work on a
# small bucket. The cost of the other answer is a provider screened against
# nothing who is never looked at, and an empty queue and a queue nobody can
# see are the same thing from the outside.
resource "snowflake_row_access_policy" "by_facility" {
  database = snowflake_database.analytics.name
  schema   = snowflake_schema.analytics_review.name
  name     = "ROWS_BY_FACILITY"
  comment  = "A reviewer reads their assigned facilities. A row with no facility goes to all of them."

  argument {
    name = "FACILITY_ID"
    type = "NUMBER"
  }

  body = <<-SQL
    exists (
      select 1 from screening_analytics.review.policy_exempt_role r
      where r.role_name = current_role()
    )
    or facility_id is null
    or exists (
      select 1
      from screening_analytics.review.review_assignment a
      where a.role_name = current_role()
        and a.facility_id = facility_id
    )
  SQL
}

# The two views the roles read. Secure, because a view that is not secure
# publishes its own definition to anybody who can read it and lets the
# optimiser push a predicate past the filter, which is how a row that was
# filtered out gets inferred from what a query refuses to return.
#
# The statement selects from the dbt built model and adds the facility the
# policy filters on. The facility comes from the active application, and a
# provider with no active application arrives here with a null, which is the
# branch the policy body was written for.
resource "snowflake_view" "review_queue" {
  database  = snowflake_database.analytics.name
  schema    = snowflake_schema.analytics_review.name
  name      = "REVIEW_QUEUE"
  is_secure = "true"
  comment   = "One row per provider with the strongest tier that reached them, filtered by facility."

  # A star and one added column rather than a column list.
  #
  # A list here would be a second place the relation's columns live, and a
  # column added to the model would be dropped by this view without anything
  # saying so. The star publishes whatever the model has, and the warehouse
  # arm of the access measurement compares the view's column list against the
  # design in both directions, so a column the design does not know about
  # fails the suite rather than reading whole.
  statement = <<-SQL
    select q.*, a.facility_id
    from screening_analytics.intermediate.int_screening__provider_screening q
    left join screening_analytics.staging.stg_credentialing__application a
      on a.provider_id = q.provider_id and a.is_active
  SQL

  row_access_policy {
    policy_name = snowflake_row_access_policy.by_facility.fully_qualified_name
    on          = ["FACILITY_ID"]
  }

  column {
    column_name = "NPI"

    masking_policy {
      policy_name = snowflake_masking_policy.identifier.fully_qualified_name
    }
  }

  column {
    column_name = "LAST_NAME"

    masking_policy {
      policy_name = snowflake_masking_policy.name_part.fully_qualified_name
    }
  }

  column {
    column_name = "FIRST_NAME"

    masking_policy {
      policy_name = snowflake_masking_policy.name_part.fully_qualified_name
    }
  }

  column {
    column_name = "DATE_OF_BIRTH"

    masking_policy {
      policy_name = snowflake_masking_policy.birth_date.fully_qualified_name
    }
  }
}

resource "snowflake_view" "match_candidate" {
  database  = snowflake_database.analytics.name
  schema    = snowflake_schema.analytics_review.name
  name      = "MATCH_CANDIDATE"
  is_secure = "true"
  comment   = "One row per provider and record a tier matched them to, filtered by facility."

  statement = <<-SQL
    select c.*, a.facility_id
    from screening_analytics.intermediate.int_screening__match_candidate c
    left join screening_analytics.staging.stg_credentialing__application a
      on a.provider_id = c.provider_id and a.is_active
  SQL

  row_access_policy {
    policy_name = snowflake_row_access_policy.by_facility.fully_qualified_name
    on          = ["FACILITY_ID"]
  }

  # using names the masked column first and then the column that decides. The
  # order is in the provider's description of the field and getting it the
  # other way round would pass validate.
  column {
    column_name = "MATCHED_NPI"

    masking_policy {
      policy_name = snowflake_masking_policy.matched_identifier.fully_qualified_name
      using       = ["MATCHED_NPI", "TIER_RANK"]
    }
  }

  column {
    column_name = "MATCHED_FALLBACK_KEY"

    masking_policy {
      policy_name = snowflake_masking_policy.matched_fallback_key.fully_qualified_name
      using       = ["MATCHED_FALLBACK_KEY", "TIER_RANK"]
    }
  }
}
