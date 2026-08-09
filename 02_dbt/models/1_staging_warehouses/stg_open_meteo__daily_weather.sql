-- Deduplicated view over raw.open_meteo_daily_weather.
-- The extractor re-pulls each location from its watermark date forward so
-- Open-Meteo's revisions to the most recent provisional days are captured,
-- which means the same (location_id, date) can land more than once. Keep the
-- row with the latest extracted_at.

with source as (

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
    from {{ source('raw', 'open_meteo_daily_weather') }}
    where
        location_id is not null
        and date is not null

),

deduplicated as (

    select
        *,
        row_number() over (
            partition by location_id, date
            order by extracted_at desc
        ) as row_num
    from source

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
    extracted_at
from deduplicated
where row_num = 1
