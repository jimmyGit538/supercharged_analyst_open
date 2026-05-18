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

),

{% if is_incremental() %}

watermarks as (

    select
        series_id,
        max(date) as max_date

    from {{ this }}
    group by series_id

),

incremental as (

    select src.*
    from source as src
    left join watermarks as wm
        on src.series_id = wm.series_id
    where wm.series_id is null
        or src.date > wm.max_date

)

select
    series_id,
    date,
    value,
    extracted_at,
    current_timestamp() as _loaded_at

from incremental

{% else %}

select
    series_id,
    date,
    value,
    extracted_at,
    current_timestamp() as _loaded_at

from source

{% endif %}
