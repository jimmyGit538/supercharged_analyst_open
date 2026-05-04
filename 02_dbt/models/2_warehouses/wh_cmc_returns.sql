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

with quotes as (

    select * from {{ ref('wh_cmc_quotes_daily') }}

    {% if is_incremental() %}
    -- Pull back 366 days so LAG windows have enough history
        where date >= (
            select date_sub(max(date), interval 366 day)  -- noqa: RF02
            from {{ this }}
        )
    {% endif %}

),

with_returns as (

    select
        date,
        coin_id,
        symbol,
        name,
        price_usd,
        market_cap_usd,
        volume_24h_usd,

        -- Daily return: (today - yesterday) / yesterday
        safe_divide(
            price_usd - lag(price_usd, 1) over (
                partition by coin_id order by date
            ),
            lag(price_usd, 1) over (
                partition by coin_id order by date
            )
        ) as daily_return,

        -- Point-in-time 30-day return: today vs 30 days ago
        safe_divide(
            price_usd - lag(price_usd, 30) over (
                partition by coin_id order by date
            ),
            lag(price_usd, 30) over (
                partition by coin_id order by date
            )
        ) as return_30d,

        -- Rolling 30-day: arithmetic mean of daily returns
        avg(
            safe_divide(
                price_usd - lag(price_usd, 1) over (
                    partition by coin_id order by date
                ),
                lag(price_usd, 1) over (
                    partition by coin_id order by date
                )
            )
        ) over (
            partition by coin_id
            order by date
            rows between 29 preceding and current row
        ) as rolling_return_30d,

        -- Point-in-time 90-day return
        safe_divide(
            price_usd - lag(price_usd, 90) over (
                partition by coin_id order by date
            ),
            lag(price_usd, 90) over (
                partition by coin_id order by date
            )
        ) as return_90d,

        -- Rolling 90-day: arithmetic mean of daily returns
        avg(
            safe_divide(
                price_usd - lag(price_usd, 1) over (
                    partition by coin_id order by date
                ),
                lag(price_usd, 1) over (
                    partition by coin_id order by date
                )
            )
        ) over (
            partition by coin_id
            order by date
            rows between 89 preceding and current row
        ) as rolling_return_90d,

        -- Point-in-time 365-day return
        safe_divide(
            price_usd - lag(price_usd, 365) over (
                partition by coin_id order by date
            ),
            lag(price_usd, 365) over (
                partition by coin_id order by date
            )
        ) as return_365d,

        -- Rolling 365-day: arithmetic mean of daily returns
        avg(
            safe_divide(
                price_usd - lag(price_usd, 1) over (
                    partition by coin_id order by date
                ),
                lag(price_usd, 1) over (
                    partition by coin_id order by date
                )
            )
        ) over (
            partition by coin_id
            order by date
            rows between 364 preceding and current row
        ) as rolling_return_365d,

        current_timestamp() as _loaded_at

    from quotes

),

-- Strip look-back buffer rows already present in the target table
final as (

    select * from with_returns

    {% if is_incremental() %}
        where date > (select max(date) from {{ this }})  -- noqa: RF02
    {% endif %}

)

select * from final
