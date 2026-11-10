{#
  The schema a model lands in, said once rather than concatenated.

  dbt's default appends the model's configured schema to the one in the
  profile. Under the local target that gives main_staging, which is harmless.
  Under the warehouse target it gave staging_staging, which is not a schema
  anybody asked for, and nothing in a parse or a validate complains because
  both targets produce a name and neither name is checked against anything.

  It was found by parsing the project once per target and diffing the resolved
  relation names. That comparison is in scripts/measure_targets.py and the
  answer it writes is graded by the suite.

  So the configured schema is used verbatim when a model sets one. A model that
  sets none falls back to the target's own schema, which is the behaviour a
  person running this locally expects.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema | trim }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
