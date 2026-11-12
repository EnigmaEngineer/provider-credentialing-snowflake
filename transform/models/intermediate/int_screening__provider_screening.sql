-- One row per provider, carrying the strongest tier that reached them.
--
-- This is what a review queue reads. A provider with no row in the candidate
-- model appears here with no tier at all, which is the set the platform clears
-- with nobody looking, and that set is the one worth counting.

{{ config(materialized='view', schema='intermediate') }}

with provider as (

    select provider_id, npi, npi_is_absent, last_name, first_name, date_of_birth
    from {{ ref('stg_credentialing__provider') }}

),

candidate as (

    select * from {{ ref('int_screening__match_candidate') }}

),

strongest as (

    select provider_id, min(tier_rank) as tier_rank
    from candidate
    group by provider_id

),

at_strongest as (

    select
        c.provider_id,
        c.tier,
        c.tier_rank,
        count(*)                                              as records_matched,
        count(distinct coalesce(c.matched_npi, c.matched_fallback_key)) as distinct_records_matched
    from candidate c
    join strongest s
      on s.provider_id = c.provider_id
     and s.tier_rank = c.tier_rank
    group by c.provider_id, c.tier, c.tier_rank

)

select
    p.provider_id,
    p.npi,
    p.npi_is_absent,
    p.last_name,
    p.first_name,
    p.date_of_birth,
    a.tier,
    a.tier_rank,
    coalesce(a.records_matched, 0)          as records_matched,
    coalesce(a.distinct_records_matched, 0) as distinct_records_matched,
    -- Named rather than left to be derived from a null tier. The providers
    -- this column is true for are the ones nobody looks at, and that is the
    -- set a reader of this model is looking for.
    case when a.tier is null then true else false end as cleared_without_review
from provider p
left join at_strongest a
  on a.provider_id = p.provider_id
