{% snapshot provider_attribute %}

{#
  Attribute history for the fields a match is made on.

  A screening answer is only as current as the attributes it read. The
  credentialing application overwrites a provider in place, so once a surname
  or a date of birth moves there is nothing left to say what the matcher
  compared against. This is the table that says it.

  The check strategy rather than the timestamp one, and the column list is the
  reason. These four are what the three tiers read. A change to a specialty or
  a middle name cannot turn a match into a miss, so a new version for one of
  those would be history nobody can act on.

  Hard deletes are invalidated. The staging model filters a deleted provider
  out, so without this the provider's last version stays open and reads as the
  state of somebody who is still in the workflow.
#}

{{
    config(
        target_schema='snapshots',
        unique_key='provider_id',
        strategy='check',
        check_cols=['npi', 'last_name', 'first_name', 'date_of_birth'],
        hard_deletes='invalidate'
    )
}}

select
    provider_id,
    npi,
    npi_is_absent,
    last_name,
    first_name,
    middle_name,
    date_of_birth,
    primary_specialty,
    updated_at

from {{ ref('stg_credentialing__provider') }}

{% endsnapshot %}
