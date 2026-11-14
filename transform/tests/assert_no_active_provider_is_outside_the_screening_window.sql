-- A provider still in the credentialing workflow has to carry a screening from
-- the current cycle.
--
-- This is the one that would stop a release. Everything else in this directory
-- grades a transformation. This grades the platform's obligation: the list is
-- republished monthly and a provider whose last screening predates the current
-- cycle has been cleared against a file that no longer exists.
--
-- A provider who has never been screened is outside the window too, which is
-- the case a rule written as a date subtraction quietly passes, because
-- subtracting from nothing returns nothing and nothing is not greater than
-- thirty.
--
-- Returns a row per provider who fails it, so an empty result is a pass.

select
    provider_id,
    last_screened_on,
    days_since_screening,
    cycle_as_of

from {{ ref('int_screening__screening_currency') }}
where is_active
  and outside_window
