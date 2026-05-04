{{
    config(
        materialized='view',
        schema='staging'
    )
}}

with returns as (

    select * from {{ ref('wh_cmc_returns') }}

),

metadata as (

    select * from {{ ref('wh_cmc_coin_metadata') }}

),

category_coins as (

    select * from {{ ref('wh_cmc_category_coins') }}

),

joined as (

    select
        r.date,
        r.coin_id,
        r.symbol,
        r.name,
        r.price_usd,
        r.market_cap_usd,
        r.volume_24h_usd,
        r.daily_return,
        r.return_30d,
        r.rolling_return_30d,
        r.return_90d,
        r.rolling_return_90d,
        r.return_365d,
        r.rolling_return_365d,
        m.slug,
        m.category        as coin_category,
        m.tags,
        m.website,
        cc.category_id,
        cc.category_name

    from returns as r
    left join metadata as m
        on r.coin_id = m.coin_id
    left join category_coins as cc
        on r.coin_id = cc.coin_id

)

select * from joined
