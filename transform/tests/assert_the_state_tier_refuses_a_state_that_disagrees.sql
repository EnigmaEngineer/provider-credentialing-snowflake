-- The state predicate has to be able to refuse somebody, and a predicate that
-- only ever runs where the answer is already true proves nothing.
--
-- Providers 8 and 9 in the seed carry the same surname, the same given name
-- and the same date of birth. One is licensed in the state the exclusion
-- record names and the other is not. The first has to reach the state tier and
-- the second has to reach no tier at all.
--
-- Returns a row when either half stops holding, so an empty result is a pass.

with answer as (

    select provider_id, tier
    from {{ ref('int_screening__provider_screening') }}
    where provider_id in (8, 9)

),

shaped as (

    select
        max(case when provider_id = 8 then tier end) as agreeing_state,
        max(case when provider_id = 9 then tier end) as disagreeing_state,
        count(*)                                     as rows_seen

    from answer

)

select *
from shaped
where rows_seen <> 2
   or agreeing_state <> 'tier3_name_state'
   or disagreeing_state is not null
