-- Daily weather fact table for Looker Studio. One row per (location_id, date).

{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['location_id', 'date'],
        partition_by={
            'field': 'date',
            'data_type': 'date',
            'granularity': 'month'
        },
        cluster_by=['location_id']
    )
}}

with weather as (

    select *
    from {{ ref('stg_open_meteo__weather_metrics') }}

    {% if is_incremental() %}
        -- Re-read a 90-day tail: Open-Meteo revises the most recent provisional days.
        where date >= (
            select date_sub(max(existing.date), interval 90 day)
            from {{ this }} as existing
        )
    {% endif %}

)

select
    location_id,
    location_name,
    country,
    latitude,
    longitude,
    date,
    temperature_max_c,
    temperature_min_c,
    temperature_range_c,
    precipitation_sum_mm,
    wind_speed_max_kmh,
    current_timestamp() as _loaded_at
from weather
