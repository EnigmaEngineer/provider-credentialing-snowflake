-- The snapshot has to answer the question the currency model asks of it.
--
-- Two ways it stops doing that and neither is visible in a row count. A
-- provider with two open versions makes the attribute history ambiguous, and
-- the model reads the latest close rather than the open row so it would not
-- notice. A live provider with no open version at all is a provider the
-- snapshot has lost, and every currency answer about them reads as clean.

with snapshotted as (

    select
        provider_id,
        sum(case when dbt_valid_to is null then 1 else 0 end) as open_versions

    from {{ ref('provider_attribute') }}
    group by provider_id

),

live as (

    select provider_id from {{ ref('stg_credentialing__provider') }}

)

select
    l.provider_id,
    coalesce(s.open_versions, 0) as open_versions

from live l
left join snapshotted s
  on s.provider_id = l.provider_id
where coalesce(s.open_versions, 0) <> 1
