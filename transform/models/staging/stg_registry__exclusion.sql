-- The exclusion list, staged without losing what its identifier column says.
--
-- The column is populated on every record. Most of those values are the
-- character zero, which is how the file says it has no identifier. Three
-- things follow and all three are here rather than in whatever model matches
-- next.
--
-- The column stays text. The absence becomes its own boolean. And the
-- fallback key is null rather than a tuple of blanks, because a key of three
-- empty strings matches every other record that could not form one either.
--
-- This source arrives by pipe rather than by the replication connector, so it
-- carries no deletion marker and nothing here filters on one.

with source as (

    select * from {{ source('registry', 'raw_registry_exclusion') }}

),

typed as (

    select
        {{ clean_identifier('npi') }}              as npi,
        upper(trim(lastname))                      as last_name_raw,
        upper(trim(firstname))                     as first_name_raw,
        upper(trim(midname))                       as middle_name,
        upper(trim(busname))                       as business_name,
        trim(dob)                                  as date_of_birth_raw,
        upper(trim(state))                         as state,
        trim(excltype)                             as exclusion_type,
        trim(excldate)                             as exclusion_date_raw

    from source

),

flagged as (

    select
        npi,
        case
            when npi is null then true
            when npi = {{ absent_identifier() }} then true
            else false
        end                                        as npi_is_absent,
        -- The surname column carries a serialised null as the word NULL on
        -- three records. A fallback key built on it would match every other
        -- record serialised the same way, so it becomes absent here.
        nullif(last_name_raw, {{ absent_name() }})  as last_name,
        first_name_raw                             as first_name,
        middle_name,
        business_name,
        case
            when date_of_birth_raw is null then null
            when date_of_birth_raw = '' then null
            when date_of_birth_raw = {{ absent_identifier() }} then null
            else date_of_birth_raw
        end                                        as date_of_birth_raw,
        last_name_raw is not null
            and last_name_raw <> ''
            and last_name_raw <> {{ absent_name() }} as is_individual,
        state,
        exclusion_type,
        exclusion_date_raw

    from typed

)

select
    npi,
    npi_is_absent,
    last_name,
    first_name,
    middle_name,
    business_name,
    date_of_birth_raw,
    is_individual,
    state,
    exclusion_type,
    exclusion_date_raw,
    -- Built by a macro rather than inline, because the matching model forms
    -- the same key from a date column and the two have to agree character for
    -- character. is_individual is still required here: a record with no
    -- surname is not a person this key can identify.
    case
        when is_individual
        then {{ fallback_key('last_name', 'first_name', 'date_of_birth_raw') }}
        else null
    end as fallback_key
from flagged
