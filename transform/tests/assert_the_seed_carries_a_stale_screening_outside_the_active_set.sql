-- A control on the fixture rather than on a model, in the same shape as the
-- one on the deletion marker.
--
-- The three checks above all return nothing on a healthy fixture, which is
-- also what they return on a fixture where nothing is active and on a rule
-- that forgot to read the active flag. So the fixture carries providers the
-- window rule does catch, and they are deliberately not in the active set.
--
-- Provider 9 was screened against an older file months before the current
-- cycle. Providers 3 and 6 have never been screened at all. None of the three
-- holds a live application in an active status, so the obligation does not
-- reach them and the rule has to say so without being told.
--
-- Returns a row when any of that stops being true.

with answer as (

    select
        provider_id,
        is_active,
        outside_window,
        screened_against_a_superseded_file,
        last_screened_on

    from {{ ref('int_screening__screening_currency') }}

),

shaped as (

    select
        sum(case when outside_window then 1 else 0 end)             as caught_by_the_window,
        sum(case when outside_window and is_active then 1 else 0 end) as caught_and_active,
        sum(case when is_active then 1 else 0 end)                  as active_providers,
        sum(case when screened_against_a_superseded_file
                 then 1 else 0 end)                                 as on_a_replaced_file,
        sum(case when last_screened_on is null then 1 else 0 end)    as never_screened

    from answer

)

select *
from shaped
where caught_by_the_window = 0
   or caught_and_active <> 0
   or active_providers = 0
   or on_a_replaced_file = 0
   or never_screened = 0
