{#
  The two things every model over a replicated table has to get right.

  A row the replication marked deleted is still in the table. The marker is a
  boolean column the replication adds, and the only state it is guaranteed to
  carry is true on a row that was deleted. A row that was never deleted can
  arrive as false or as nothing at all, and that is the whole problem: the
  obvious filter reads the absence as unknown and drops every live row with it.

  So the filter coalesces. A test asserts what each spelling returns over a
  seed carrying all three states, because the difference between them is
  invisible on any data where the column happens to be populated.
#}

{% macro not_deleted(alias=none) -%}
    {%- set prefix = (alias ~ '.') if alias else '' -%}
    coalesce({{ prefix }}_fivetran_deleted, false) = false
{%- endmacro %}

{#
  The naive spelling, kept so a test can show what it does rather than
  describe it. Nothing in models/ calls this.
#}
{% macro not_deleted_naive(alias=none) -%}
    {%- set prefix = (alias ~ '.') if alias else '' -%}
    not {{ prefix }}_fivetran_deleted
{%- endmacro %}

{#
  The exclusion list writes an absent identifier as the character zero rather
  than as nothing. Casting that column to a number turns the sentinel into 0,
  and a join on 0 matches every other record that had no identifier either.

  So the staging layer keeps the column as text and publishes the absence as
  its own boolean. The sentinel is named once, here, because a model that spells
  it inline is a model somebody will change in one place and not the other.
#}
{% macro absent_identifier() -%}
    '0'
{%- endmacro %}

{#
  The exclusion file writes a serialised null as the four character word NULL
  in its surname column. Three records carry it, measured on the published
  file, and a fallback key built on that word matches every other record whose
  surname was serialised the same way.

  Only the exact word is treated as absent. NA appears as a given name on three
  records and is left alone, because NA is a name somebody can actually have
  and NULL is not.
#}
{% macro absent_name() -%}
    'NULL'
{%- endmacro %}

{#
  An identifier with padding around it is the same defect as the sentinel, one
  step quieter. It is not empty and it is not the sentinel, so every
  completeness check passes, and a join on it matches nothing.
#}
{% macro clean_identifier(column) -%}
    nullif(trim({{ column }}), '')
{%- endmacro %}

{#
  The fallback key, built in one place because two models form it and the two
  sides of a match have to agree character for character.

  The exclusion model built it inline until 2026-11-12 and the matching model
  built it again from a date column. A key concatenated from a parsed date and
  a key concatenated from the file's own text agree only while the parse and
  the format agree, and nothing anywhere compares them. The pipe is a
  separator the data cannot contain, so a surname ending in a space cannot
  borrow the next field's first character.
#}
{% macro fallback_key(last, first, dob_text) -%}
    case
        when {{ last }} is not null
             and {{ first }} is not null
             and {{ first }} <> ''
             and {{ dob_text }} is not null
        then {{ last }} || '|' || {{ first }} || '|' || {{ dob_text }}
        else null
    end
{%- endmacro %}

{#
  A date back in the eight digit form the exclusion file publishes.

  The comparison goes this way rather than parsing the file's eight digits,
  because the parse can only fail on the side that has no reason to fail. The
  credentialing database holds a real date and the file holds text that may not
  be one.
#}
{% macro eight_digit_date(column) -%}
    {{ dbt.replace("cast(" ~ column ~ " as " ~ dbt.type_string() ~ ")", "'-'", "''") }}
{%- endmacro %}

{#
  The identifier a match reached, with the sentinel kept out of it.

  The staging model publishes the identifier column as the file wrote it, with
  the absence flagged beside it, which is right for a model whose job is to
  transcribe. A matching model's identifier column is an answer rather than a
  transcription, and the character zero published there is an identifier
  nothing can use: anything joining on it joins to every other record that had
  none either.

  Found on 2026-11-12 by comparing the SQL tiers against the Python ones over
  the whole sample, pair by pair. The tier each provider landed in agreed on
  all 500. 103 of the pairs disagreed on which record, and every one of them
  was this. The seed suite passed throughout, because the check on the
  sentinel reads the staging model and nothing graded this column.
#}
{% macro matched_identifier(alias) -%}
    case when {{ alias }}.npi_is_absent then null else {{ alias }}.npi end
{%- endmacro %}
