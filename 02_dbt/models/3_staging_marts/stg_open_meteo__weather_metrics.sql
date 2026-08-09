-- Adds a derived daily temperature range on top of the warehouse table.
-- One row per (location_id, date), same grain as the warehouse layer.

with weather as (

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
        wind_speed_max_kmh
    from {{ ref('open_meteo_daily_weather') }}

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
    temperature_max_c - temperature_min_c as temperature_range_c
from weather
