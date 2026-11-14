-- The third way a screening retires, and it is the one that looks fine on a
-- date.
--
-- A cycle re-run against last month's download produces screenings dated
-- today against a file that has been replaced. The window cannot see it. The
-- digest can.

select
    provider_id,
    last_screened_on,
    last_sha256,
    current_sha256

from {{ ref('int_screening__screening_currency') }}
where is_active
  and screened_against_a_superseded_file
