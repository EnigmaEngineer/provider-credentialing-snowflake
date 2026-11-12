-- The two sides of the fallback match form the key from different columns.
-- The exclusion model concatenates the file's own text. The matching model
-- concatenates a parsed date put back into the file's format. They agree only
-- while the parse and the format agree and nothing else compares them.
--
-- Returns any tier two pair where the key the provider forms is not the key
-- the match was made on.

select
    c.provider_id,
    c.matched_fallback_key,
    {{ fallback_key('p.last_name', 'p.first_name', eight_digit_date('p.date_of_birth')) }} as rebuilt_key
from {{ ref('int_screening__match_candidate') }} as c
join {{ ref('stg_credentialing__provider') }} as p
    on p.provider_id = c.provider_id
where c.tier = 'tier2_name_and_dob'
  and (
      c.matched_fallback_key is null
      or c.matched_fallback_key
         <> {{ fallback_key('p.last_name', 'p.first_name', eight_digit_date('p.date_of_birth')) }}
  )
