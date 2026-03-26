{{
    config(
        materialized='view',
        schema='staging'
    )
}}

with source as (

    select * from {{ source('raw', 'twelvedata_indices_daily') }}

),

cleaned as (

    select
        date,
        cast(open as numeric) as open,
        cast(high as numeric) as high,
        cast(low as numeric) as low,
        cast(close as numeric) as close,
        volume,
        extracted_at,
        lower(trim(symbol)) as index_ticker

    from source

    where
        date is not null
        and close is not null

),

deduped as (

    select
        *,
        row_number() over (
            partition by index_ticker, date
            order by extracted_at desc
        ) as _row_num

    from cleaned

)

select
    date,
    open,
    high,
    low,
    close,
    volume,
    extracted_at,
    index_ticker

from deduped

where _row_num = 1
