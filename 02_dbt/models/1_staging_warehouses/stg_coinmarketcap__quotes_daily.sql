{{
    config(
        materialized='view',
        schema='staging'
    )
}}

with source as (

    select * from {{ source('raw', 'coinmarketcap_quotes_daily') }}

),

cleaned as (

    select
        cast(date as date)               as date,
        cast(coin_id as int64)           as coin_id,
        cast(symbol as string)           as symbol,
        cast(name as string)             as name,
        cast(price_usd as numeric)       as price_usd,
        cast(volume_24h_usd as numeric)  as volume_24h_usd,
        cast(market_cap_usd as numeric)  as market_cap_usd,
        cast(percent_change_1h as numeric)  as percent_change_1h,
        cast(percent_change_24h as numeric) as percent_change_24h,
        cast(percent_change_7d as numeric)  as percent_change_7d,
        extracted_at

    from source

    where
        date is not null
        and coin_id is not null
        and price_usd > 0

),

deduped as (

    select
        *,
        row_number() over (
            partition by date, coin_id
            order by extracted_at desc
        ) as _row_num

    from cleaned

)

select
    date,
    coin_id,
    symbol,
    name,
    price_usd,
    volume_24h_usd,
    market_cap_usd,
    percent_change_1h,
    percent_change_24h,
    percent_change_7d,
    extracted_at

from deduped

where _row_num = 1
