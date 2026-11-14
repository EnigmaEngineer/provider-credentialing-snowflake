{% snapshot provider_attribute_by_timestamp %}

{#
  The same table under the strategy that trusts the source's own clock. A
  control arm, in the same shape as the two arms in measurements/matching.json.
  Nothing downstream reads it.

  It is here because the timestamp strategy is the cheaper and more obvious
  choice and it answers a different question. It records a version when the
  application says the row changed. The arm above records one when a field a
  match reads has a different value. Those agree only while every write bumps
  updated_at, and a write that does not is invisible to this arm while the
  attribute it changed is sitting in the matcher.

  scripts/measure_history.py runs both over the same change set and counts what
  each one recorded.
#}

{{
    config(
        target_schema='snapshots',
        unique_key='provider_id',
        strategy='timestamp',
        updated_at='updated_at'
    )
}}

select
    provider_id,
    npi,
    last_name,
    first_name,
    date_of_birth,
    updated_at

from {{ ref('stg_credentialing__provider') }}

{% endsnapshot %}
