-- A provider the queue marks cleared must have no candidate row at any tier.
-- The join that produces that column is a left join and a left join written
-- against the wrong key clears everybody.

select s.provider_id
from {{ ref('int_screening__provider_screening') }} as s
join {{ ref('int_screening__match_candidate') }} as c
    on c.provider_id = s.provider_id
where s.cleared_without_review = true
