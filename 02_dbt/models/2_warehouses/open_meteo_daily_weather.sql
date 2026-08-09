-- Warehouse table for Open-Meteo daily weather. One row per (location_id, date).
-- Incremental on date: only observations at or after a 90-day tail of the
-- current maximum date are reprocessed, which also lets Open-Meteo's
-- revisions to provisional recent days overwrite the stored value via the
-- merge on (location_id, date).

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

with staged as (

    select
        location_id,
        location_name,
        country,
        latitude,
        longitude,
        date,
        temperature_max_c,
        temperature_min_c,
        precipitation_sum_mm,
        wind_speed_max_kmh,
        extracted_at
    from {{ ref('stg_open_meteo__daily_weather') }}

    {% if is_incremental() %}
        -- Re-read a 90-day tail so late-arriving revisions are merged in.
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
    precipitation_sum_mm,
    wind_speed_max_kmh,
    extracted_at,
    current_timestamp() as _loaded_at
from staged
