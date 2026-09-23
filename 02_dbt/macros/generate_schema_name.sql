{#
    Resolves the dataset each model is written to.

    Deployed targets use the model's `+schema` config verbatim, so Cloud Run and
    prod write to the canonical `stg_warehouses` / `warehouses` / `stg_marts` /
    `marts` datasets that Looker Studio reads.

    Every other target (notably `dev`) is prefixed with `target.schema`, giving
    `dbt_dev_stg_warehouses`, `dbt_dev_warehouses`, and so on. Without this
    prefix a local `dbt build --target dev` writes straight into production,
    because a bare `custom_schema_name` ignores `target.schema` entirely — the
    `dataset:` field in profiles.yml does not isolate anything on its own.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif target.name in ('prod', 'cloudrun') -%}
        {{ custom_schema_name | trim }}
    {%- else -%}
        {{ target.schema }}_{{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
