-- One row per live provider in the credentialing workflow.
--
-- The identifier stays text. The credentialing application stores it as text
-- and the registry files encode an absent one as the character zero, so a
-- numeric column here would turn two different things into the same 0.

with source as (

    select * from {{ source('credentialing', 'raw_credentialing_provider') }}

),

renamed as (

    select
        provider_id,
        -- Trimmed, not merely cast. An identifier arriving with padding is
        -- not empty and is not the sentinel, so it passes every completeness
        -- check and joins to nothing.
        {{ clean_identifier('npi') }}                        as npi,
        case
            when {{ clean_identifier('npi') }} is null then true
            when {{ clean_identifier('npi') }} = {{ absent_identifier() }} then true
            else false
        end                                                 as npi_is_absent,
        upper(trim(last_name))                              as last_name,
        upper(trim(first_name))                             as first_name,
        upper(trim(middle_name))                            as middle_name,
        upper(trim(business_name))                           as business_name,
        cast(date_of_birth as date)                         as date_of_birth,
        provider_type,
        upper(trim(primary_specialty))                       as primary_specialty,
        cast(created_at as {{ dbt.type_timestamp() }})       as created_at,
        cast(updated_at as {{ dbt.type_timestamp() }})       as updated_at,
        cast(_fivetran_synced as {{ dbt.type_timestamp() }}) as replicated_at

    from source
    where {{ not_deleted() }}

)

select * from renamed
