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

)

select * from cleaned
