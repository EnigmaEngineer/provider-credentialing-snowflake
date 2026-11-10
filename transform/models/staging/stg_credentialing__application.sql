-- One row per live credentialing application.
--
-- is_active carries the question a later check has to ask. A screening window
-- applies to a provider who is still in the workflow, and that is a property
-- of the status rather than of whether a decision date is filled in.

with source as (

    select * from {{ source('credentialing', 'raw_credentialing_application') }}

),

renamed as (

    select
        application_id,
        provider_id,
        facility_id,
        application_type,
        status,
        status in ('submitted', 'in_verification', 'committee_review') as is_active,
        cast(submitted_on as date)                           as submitted_on,
        cast(decided_on as date)                             as decided_on,
        cast(_fivetran_synced as {{ dbt.type_timestamp() }}) as replicated_at

    from source
    where {{ not_deleted() }}

)

select * from renamed
