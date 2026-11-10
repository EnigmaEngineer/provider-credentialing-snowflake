-- One row per live state licence.
--
-- A delete in the source removes the basis for a clearance, so the source
-- table publishes its whole old row on a delete rather than its key alone.
-- That choice is in credentialing/schema.sql and the measurement behind it is
-- in measurements/replication.json.

with source as (

    select * from {{ source('credentialing', 'raw_credentialing_license') }}

),

renamed as (

    select
        license_id,
        provider_id,
        upper(trim(state))                                   as state,
        trim(license_number)                                 as license_number,
        cast(issued_on as date)                              as issued_on,
        cast(expires_on as date)                             as expires_on,
        status,
        cast(_fivetran_synced as {{ dbt.type_timestamp() }})  as replicated_at

    from source
    where {{ not_deleted() }}

)

select * from renamed
