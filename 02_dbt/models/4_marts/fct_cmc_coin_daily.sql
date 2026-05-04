{{
    config(
        materialized='incremental',
        schema='marts',
        unique_key=['date', 'coin_id'],
        partition_by={
            'field': 'date',
            'data_type': 'date',
            'granularity': 'month'
        },
        cluster_by=['coin_id']
    )
}}

with coin_daily as (

    select * from {{ ref('stg_cmc__coin_daily') }}

    {% if is_incremental() %}
        where date > (select max(date) from {{ this }})  -- noqa: RF02
    {% endif %}

)

select
    date,
    coin_id,
    symbol,
    name,
    slug,
    category_id,
    category_name,
    coin_category,
    tags,
    website,
    price_usd,
    market_cap_usd,
    volume_24h_usd,
    daily_return,
    return_30d,
    rolling_return_30d,
    return_90d,
    rolling_return_90d,
    return_365d,
    rolling_return_365d,
    current_timestamp() as _loaded_at

from coin_daily
