-- The other direction. A row the replication marked deleted must not be in
-- the staging model. Without this the filter could be dropped entirely and the
-- check above would still pass.

select raw.provider_id
from {{ source('credentialing', 'raw_credentialing_provider') }} as raw
join {{ ref('stg_credentialing__provider') }} as stg
    on stg.provider_id = raw.provider_id
where raw._fivetran_deleted = true
