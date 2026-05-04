{{
    config(
        materialized='incremental',
        schema='marts',
        unique_key=['date', 'category_id'],
        partition_by={
            'field': 'date',
            'data_type': 'date',
            'granularity': 'month'
        },
        cluster_by=['category_id']
    )
}}

with category_daily as (

    select * from {{ ref('stg_cmc__category_daily') }}

    {% if is_incremental() %}
        where date > (select max(date) from {{ this }})  -- noqa: RF02
    {% endif %}

)

select
    date,
    category_id,
    category_name,
    total_market_cap_usd,
    total_volume_24h_usd,
    num_coins,
    avg_daily_return,
    avg_return_30d,
    avg_rolling_return_30d,
    avg_return_90d,
    avg_rolling_return_90d,
    avg_return_365d,
    avg_rolling_return_365d,
    current_timestamp() as _loaded_at

from category_daily
