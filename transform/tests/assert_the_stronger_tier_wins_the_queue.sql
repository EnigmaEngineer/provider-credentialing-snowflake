-- Provider 7 agrees with an exclusion record on surname, given name, date of
-- birth and state, so two tiers can reach them. The queue has to carry the
-- stronger one, because a provider sitting in the name and state queue when
-- the dates of birth agree is a provider somebody reviews a second time.
--
-- This is a check on the ordering rather than on either tier. Dropping the
-- rank from the model leaves both candidate rows in place and every other
-- check still passes.

with answer as (

    select tier, tier_rank, records_matched
    from {{ ref('int_screening__provider_screening') }}
    where provider_id = 7

),

candidates as (

    select count(*) as tiers_reached
    from (
        select distinct tier
        from {{ ref('int_screening__match_candidate') }}
        where provider_id = 7
    ) as t

)

select answer.*, candidates.tiers_reached
from answer
cross join candidates
where answer.tier <> 'tier2_name_and_dob'
   or answer.tier_rank <> 2
   or candidates.tiers_reached < 2
