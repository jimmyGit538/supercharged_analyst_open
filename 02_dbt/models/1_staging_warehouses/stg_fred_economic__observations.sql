-- Deduplicated view over raw.fred_economic_observations.
-- The extractor re-pulls each series from its watermark date forward so FRED
-- revisions are captured, which means the same (series_id, date) can land more
-- than once. Keep the row with the latest extracted_at.

with source as (

    select
        series_id,
        date,
        value,
        extracted_at
    from {{ source('raw', 'fred_economic_observations') }}
    where
        series_id is not null
        and date is not null

),

deduplicated as (

    select
        series_id,
        date,
        value,
        extracted_at,
        row_number() over (
            partition by series_id, date
            order by extracted_at desc
        ) as row_num
    from source

)

select
    series_id,
    date,
    value,
    extracted_at
from deduplicated
where row_num = 1
