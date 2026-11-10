-- A control on the fixture rather than on a model.
--
-- The whole argument for the coalescing filter is that it differs from the
-- obvious one. If the seed ever stops carrying a null marker, the two spellings
-- agree, every other check still passes, and the difference becomes invisible.
-- This returns a row when that happens.

with counted as (

    select
        count(*)                                                      as rows_total,
        sum(case when coalesce(_fivetran_deleted, false) = false
                 then 1 else 0 end)                                   as live_by_coalesce,
        sum(case when not coalesce(_fivetran_deleted, true)
                 then 1 else 0 end)                                   as live_by_naive,
        sum(case when _fivetran_deleted is null then 1 else 0 end)     as marker_null,
        sum(case when _fivetran_deleted = true then 1 else 0 end)      as marker_true,
        sum(case when _fivetran_deleted = false then 1 else 0 end)     as marker_false

    from {{ source('credentialing', 'raw_credentialing_provider') }}

)

select *
from counted
where marker_null = 0
   or marker_true = 0
   or marker_false = 0
   or live_by_coalesce <= live_by_naive
