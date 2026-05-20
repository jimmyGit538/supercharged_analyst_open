{{
    config(
        materialized='incremental',
        schema='warehouses',
        unique_key=['series_id', 'date'],
        partition_by={
            'field': 'date',
            'data_type': 'date',
            'granularity': 'month'
        },
        cluster_by=['series_id']
    )
}}

with source as (

    select
        series_id,
        date,
        value,
        extracted_at

    from {{ ref('stg_fred_economic__observations') }}

    {% if is_incremental() %}
        where date > (select max(date) from {{ this }})
    {% endif %}

)

select
    series_id,
    date,
    value,
    extracted_at,
    current_timestamp() as _loaded_at

from source
