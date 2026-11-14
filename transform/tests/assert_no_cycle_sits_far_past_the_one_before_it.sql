-- The cycle date is derived from the screening log's own maximum, so the log
-- dates the platform.
--
-- That is deliberate. A model that reads the clock gives a different answer on
-- a day nobody changed anything. The cost is that one row dated into the
-- future moves the cycle date forward and retires every screening behind it,
-- and the currency model cannot tell that apart from a month having passed.
--
-- This is the guard. Consecutive cycle dates more than two windows apart mean
-- either a cycle was skipped or a row is misdated, and both are worth
-- stopping on. Two windows rather than one, because a cycle that ran late is a
-- real thing and a cycle dated six months out is not.

{% set window_days = var('screening_window_days') %}

with cycle as (

    select distinct screened_on
    from {{ ref('stg_screening__screening_event') }}

),

spaced as (

    select
        screened_on,
        lag(screened_on) over (order by screened_on) as previous_cycle
    from cycle

)

select
    previous_cycle,
    screened_on,
    {{ dbt.datediff('previous_cycle', 'screened_on', 'day') }} as days_apart

from spaced
where previous_cycle is not null
  and {{ dbt.datediff('previous_cycle', 'screened_on', 'day') }} > {{ window_days * 2 }}
