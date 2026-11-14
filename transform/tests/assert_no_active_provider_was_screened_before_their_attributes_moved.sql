-- The same obligation, one step further in, and the one the snapshot exists
-- for.
--
-- A screening inside the window can still be worthless. If a surname or a date
-- of birth moved after the screening was taken, the answer on file is about a
-- person the source no longer describes, and the calendar says nothing about
-- it.
--
-- Returns a row per provider whose current screening sits behind a closed
-- attribute version.

select
    provider_id,
    last_screened_on,
    last_attribute_change_on,
    closed_attribute_versions

from {{ ref('int_screening__screening_currency') }}
where is_active
  and attributes_moved_since_screening
