-- A matching model's identifier column is an answer and not a transcription,
-- so the sentinel must not reach it. The staging model is allowed to publish
-- the character zero with its flag beside it. This column is not.
--
-- Returns any candidate pair whose matched identifier is unusable, so an empty
-- result is a pass.

select
    provider_id,
    tier,
    matched_npi
from {{ ref('int_screening__match_candidate') }}
where matched_npi = '0'
   or matched_npi = ''
   or matched_npi <> trim(matched_npi)
