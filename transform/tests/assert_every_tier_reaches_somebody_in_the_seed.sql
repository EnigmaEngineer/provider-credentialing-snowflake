-- A tier that matches nothing in the fixture is a tier nothing graded. Each of
-- the three has to produce at least one candidate pair here, because a model
-- run against an input with nothing in it reports clean.

with per_tier as (

    select tier, count(*) as pairs
    from {{ ref('int_screening__match_candidate') }}
    group by tier

)

select 'tier1_identifier' as missing_tier
where not exists (select 1 from per_tier where tier = 'tier1_identifier')
union all
select 'tier2_name_and_dob'
where not exists (select 1 from per_tier where tier = 'tier2_name_and_dob')
union all
select 'tier3_name_state'
where not exists (select 1 from per_tier where tier = 'tier3_name_state')
