-- The identifier column must not come out of staging holding the sentinel
-- without the flag beside it saying so, and it must not come out padded.
--
-- Returns any row where the two disagree, so an empty result is a pass.

select
    npi,
    npi_is_absent
from {{ ref('stg_registry__exclusion') }}
where (npi = '0' and not npi_is_absent)
   or (npi is null and not npi_is_absent)
   or (npi is not null and npi <> trim(npi))
