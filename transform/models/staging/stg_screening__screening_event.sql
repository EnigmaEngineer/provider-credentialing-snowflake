-- One row per screening that was taken.
--
-- There is no deletion filter here and that is deliberate. The source is
-- append only, so a filter on a marker column that does not exist would bind
-- against nothing and the model would look like the others while reading a
-- table that cannot answer the question.

with source as (

    select * from {{ source('screening', 'raw_screening_screening_event') }}

),

renamed as (

    select
        screening_id,
        provider_id,
        cast(screened_on as date)      as screened_on,
        lower(trim(exclusion_file_sha256)) as exclusion_file_sha256,
        matched_tier,
        outcome,
        -- A screening that reached no tier is the one that cleared somebody
        -- with nobody looking, which is the set this platform counts.
        case when matched_tier is null then true else false end as cleared_without_review

    from source

)

select * from renamed
