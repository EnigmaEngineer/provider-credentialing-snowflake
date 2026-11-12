-- One row per provider and exclusion record a tier matched them to.
--
-- Pair grained on purpose. A provider grained answer cannot say which record
-- a tier reached, and a tier that flags the right provider against the wrong
-- record is a tier that looks correct on any count of providers. The Python
-- measurement in scripts/measure_matching.py grades the pair for the same
-- reason, and the two implementations are compared against each other over
-- this model.
--
-- Three tiers, strongest first, and the rank is what decides which queue a
-- provider lands in. The tier is not chosen here. Every candidate pair any
-- tier can form is emitted and int_screening__provider_screening picks the
-- strongest, because a tier two pair is still worth keeping for somebody
-- reviewing a tier one decision.

{{ config(materialized='view', schema='intermediate') }}

with provider as (

    select * from {{ ref('stg_credentialing__provider') }}

),

licence as (

    -- A provider can hold licences in more than one state, so this is not a
    -- one to one join and nothing here assumes it is. The state tier is
    -- reached once per state the provider is licensed in.
    select provider_id, state from {{ ref('stg_credentialing__license') }}

),

exclusion as (

    select * from {{ ref('stg_registry__exclusion') }}

),

tier1 as (

    select
        p.provider_id,
        'tier1_identifier'                           as tier,
        1                                            as tier_rank,
        e.npi                                        as matched_npi,
        e.fallback_key                               as matched_fallback_key
    from provider p
    join exclusion e
      on p.npi = e.npi
    where p.npi_is_absent = false
      and e.npi_is_absent = false

),

tier2 as (

    -- The key is formed from the provider's own columns in the same shape the
    -- exclusion model publishes. The date of birth goes back to the eight
    -- digit form the file uses rather than the registry date being parsed,
    -- because the parse can only fail on the side that has no reason to fail.
    select
        p.provider_id,
        'tier2_name_and_dob'                           as tier,
        2                                              as tier_rank,
        {{ matched_identifier('e') }}                  as matched_npi,
        e.fallback_key                                 as matched_fallback_key
    from provider p
    join exclusion e
      on e.fallback_key = {{ fallback_key('p.last_name', 'p.first_name', eight_digit_date('p.date_of_birth')) }}
    where e.fallback_key is not null
      and p.last_name is not null
      and p.first_name is not null
      and p.date_of_birth is not null

),

tier3 as (

    select distinct
        p.provider_id,
        'tier3_name_state'                           as tier,
        3                                            as tier_rank,
        {{ matched_identifier('e') }}                as matched_npi,
        e.fallback_key                               as matched_fallback_key
    from provider p
    join licence l
      on l.provider_id = p.provider_id
    join exclusion e
      on e.last_name = p.last_name
     and e.first_name = p.first_name
     and e.state = l.state
    where e.is_individual
      and e.last_name is not null
      and e.first_name is not null
      and e.state is not null
      and p.last_name is not null
      and p.first_name is not null

)

select * from tier1
union all
select * from tier2
union all
select * from tier3
