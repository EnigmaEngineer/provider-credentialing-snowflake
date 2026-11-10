-- One row per live committee decision.
--
-- This is the table where a delete the warehouse misses does the most damage.
-- A rescinded approval left in place here reads as an approval that still
-- stands, and the model that clears a provider reads this one.

with source as (

    select * from {{ source('credentialing', 'raw_credentialing_committee_decision') }}

),

renamed as (

    select
        decision_id,
        application_id,
        cast(meeting_on as date)                             as meeting_on,
        decision,
        cast(effective_from as date)                         as effective_from,
        cast(effective_to as date)                           as effective_to,
        cast(_fivetran_synced as {{ dbt.type_timestamp() }})  as replicated_at

    from source
    where {{ not_deleted() }}

)

select * from renamed
