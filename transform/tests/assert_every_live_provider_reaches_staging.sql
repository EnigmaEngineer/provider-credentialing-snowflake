-- A row the replication did not mark deleted has to reach the staging model.
-- Returns the rows that did not, so an empty result is a pass.
--
-- This is the check that fails if the filter is written the obvious way. The
-- marker is null on a row that was never deleted, and the obvious filter reads
-- that as unknown and drops it.

select raw.provider_id
from {{ source('credentialing', 'raw_credentialing_provider') }} as raw
left join {{ ref('stg_credentialing__provider') }} as stg
    on stg.provider_id = raw.provider_id
where coalesce(raw._fivetran_deleted, false) = false
  and stg.provider_id is null
