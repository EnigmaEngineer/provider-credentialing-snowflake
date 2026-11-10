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
