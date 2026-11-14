{% snapshot license_attribute %}

{#
  Attribute history for the licence, because the state the third tier reads
  lives here and not on the provider.

  The status and the expiry are in the column list for the same reason as the
  state. A licence that lapsed after a clearance was granted is a clearance
  resting on something that no longer holds, and the row in the source has
  already been overwritten by then.

  Hard deletes are invalidated and this is the table where that matters most. A
  deleted licence row removes the only state the third tier can read, so the
  provider stops being reachable by it. Closing the version is how that shows
  up as something rather than as nothing.
#}

{{
    config(
        target_schema='snapshots',
        unique_key='license_id',
        strategy='check',
        check_cols=['state', 'status', 'expires_on'],
        hard_deletes='invalidate'
    )
}}

select
    license_id,
    provider_id,
    state,
    license_number,
    issued_on,
    expires_on,
    status

from {{ ref('stg_credentialing__license') }}

{% endsnapshot %}
