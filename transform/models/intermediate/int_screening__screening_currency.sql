-- One row per provider, saying whether the screening on file still stands.
--
-- Three things can retire a screening and only one of them is the calendar.
--
-- The list is republished monthly, so a screening older than a cycle was taken
-- against a file that has since been replaced. That is the window.
--
-- A screening can also be inside the window and still have been taken against
-- an older file, which happens when a cycle is re-run on last month's download.
-- The date looks current and the evidence is not.
--
-- And the attributes a match was made on can move. The credentialing
-- application overwrites a provider in place, so a surname that changed after
-- the screening leaves an answer about a person who no longer exists in the
-- source. The snapshot is what makes that visible.

{{ config(materialized='view', schema='intermediate') }}

{% set window_days = var('screening_window_days') %}

with event as (

    select * from {{ ref('stg_screening__screening_event') }}

),

-- The cycle this answer is as of, taken from the log rather than from the
-- clock. A model that reads the clock returns a different answer on a day
-- nobody changed anything, so a test over it starts failing on its own.
cycle as (

    select max(screened_on) as as_of
    from event

),

current_file as (

    select
        min(e.exclusion_file_sha256)            as current_sha256,
        count(distinct e.exclusion_file_sha256) as digests_on_the_latest_cycle

    from event e
    cross join cycle c
    where e.screened_on = c.as_of

),

last_screening as (

    select
        provider_id,
        max(screened_on) as last_screened_on

    from event
    group by provider_id

),

last_screening_detail as (

    select
        e.provider_id,
        min(e.exclusion_file_sha256) as last_sha256,
        min(e.outcome)               as last_outcome

    from event e
    join last_screening s
      on s.provider_id = e.provider_id
     and s.last_screened_on = e.screened_on
    group by e.provider_id

),

-- Active is a property of the application and a provider can hold more than
-- one, so any live application in an active status makes the provider active.
active as (

    select
        provider_id,
        max(case when is_active then 1 else 0 end) = 1 as is_active

    from {{ ref('stg_credentialing__application') }}
    group by provider_id

),

-- A version that was in force and has since been closed.
--
-- This reads the closed versions rather than the start of the open one on
-- purpose. On a first snapshot run every provider's open version starts at the
-- moment the snapshot ran, which is later than every screening in the log and
-- says nothing at all about the source. A closed version is the only evidence
-- that a value actually moved.
superseded_version as (

    select
        provider_id,
        max(dbt_valid_to) as last_version_closed_at,
        count(*)          as closed_versions

    from {{ ref('provider_attribute') }}
    where dbt_valid_to is not null
    group by provider_id

),

shaped as (

    select
        p.provider_id,
        p.last_name,
        p.first_name,
        p.date_of_birth,
        coalesce(a.is_active, false)              as is_active,
        s.last_screened_on,
        d.last_outcome,
        c.as_of                                   as cycle_as_of,
        f.current_sha256,
        f.digests_on_the_latest_cycle,
        d.last_sha256,
        coalesce(v.closed_versions, 0)            as closed_attribute_versions,
        cast(v.last_version_closed_at as date)    as last_attribute_change_on,
        case
            when s.last_screened_on is null then null
            else {{ dbt.datediff('s.last_screened_on', 'c.as_of', 'day') }}
        end                                       as days_since_screening

    from {{ ref('stg_credentialing__provider') }} p
    cross join cycle c
    cross join current_file f
    left join active a
      on a.provider_id = p.provider_id
    left join last_screening s
      on s.provider_id = p.provider_id
    left join last_screening_detail d
      on d.provider_id = p.provider_id
    left join superseded_version v
      on v.provider_id = p.provider_id

),

flagged as (

    select
        *,
        case
            when last_screened_on is null then true
            when days_since_screening > {{ window_days }} then true
            else false
        end as outside_window,
        case
            when last_screened_on is null then false
            when last_sha256 <> current_sha256 then true
            else false
        end as screened_against_a_superseded_file,
        -- The comparison is not strict. A screening is dated to the day and a
        -- version boundary is a timestamp, so a change on the day of the
        -- screening cannot be ordered against it. For a platform whose whole
        -- job is to not clear the wrong person, an unordered pair is read as a
        -- change after.
        case
            when last_screened_on is null then false
            when last_attribute_change_on is null then false
            when last_attribute_change_on >= last_screened_on then true
            else false
        end as attributes_moved_since_screening

    from shaped

)

select
    *,
    -- Named rather than left to a reader to assemble from three booleans. The
    -- providers this is true for are the ones a cycle has to screen again, and
    -- that is the set the queue reads.
    (
        outside_window
        or screened_against_a_superseded_file
        or attributes_moved_since_screening
    ) as screening_is_void

from flagged
