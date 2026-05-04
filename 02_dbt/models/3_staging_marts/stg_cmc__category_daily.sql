{{
    config(
        materialized='view',
        schema='staging'
    )
}}

with coin_daily as (

    select * from {{ ref('stg_cmc__coin_daily') }}

    where category_id is not null

),

aggregated as (

    select
        date,
        category_id,
        category_name,

        -- Size metrics
        sum(market_cap_usd)   as total_market_cap_usd,
        sum(volume_24h_usd)   as total_volume_24h_usd,
        count(distinct coin_id) as num_coins,

        -- Average return metrics across constituent coins
        avg(daily_return)        as avg_daily_return,
        avg(return_30d)          as avg_return_30d,
        avg(rolling_return_30d)  as avg_rolling_return_30d,
        avg(return_90d)          as avg_return_90d,
        avg(rolling_return_90d)  as avg_rolling_return_90d,
        avg(return_365d)         as avg_return_365d,
        avg(rolling_return_365d) as avg_rolling_return_365d

    from coin_daily

    group by date, category_id, category_name

)

select * from aggregated
