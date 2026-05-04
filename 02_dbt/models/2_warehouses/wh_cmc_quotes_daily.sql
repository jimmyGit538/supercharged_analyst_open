{{
    config(
        materialized='incremental',
        schema='warehouses',
        unique_key=['date', 'coin_id'],
        partition_by={
            'field': 'date',
            'data_type': 'date',
            'granularity': 'month'
        },
        cluster_by=['coin_id']
    )
}}

with staged as (

    select * from {{ ref('stg_coinmarketcap__quotes_daily') }}

    {% if is_incremental() %}
        where date > (select max(date) from {{ this }})  -- noqa: RF02
    {% endif %}

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
    current_timestamp() as _loaded_at

from staged
