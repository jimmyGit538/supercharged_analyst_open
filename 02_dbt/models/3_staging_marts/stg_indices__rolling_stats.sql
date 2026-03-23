{{
    config(
        materialized='view',
        schema='staging'
    )
}}

with base as (

    select
        d.index_ticker,
        d.date,
        d.close,
        d.trading_day_seq,
        r.daily_return

    from {{ ref('wh_indices_daily') }} d
    inner join {{ ref('wh_indices_returns') }} r
        on  d.index_ticker = r.index_ticker
        and d.date         = r.date

),

with_windows as (

    select
        index_ticker,
        date,
        close,
        trading_day_seq,
        daily_return,

        -- 20-day simple moving average (null for first 19 trading days of history)
        avg(close) over (
            partition by index_ticker
            order by date
            rows between 19 preceding and current row
        )                                                       as ma_20d,

        -- 50-day simple moving average (null for first 49 trading days)
        avg(close) over (
            partition by index_ticker
            order by date
            rows between 49 preceding and current row
        )                                                       as ma_50d,

        -- 20-day realized volatility, annualized: stddev of daily returns * sqrt(252)
        -- null for first 19 trading days; null when daily_return is null
        stddev_pop(daily_return) over (
            partition by index_ticker
            order by date
            rows between 19 preceding and current row
        ) * sqrt(252)                                           as vol_20d_annualized,

        -- 52-week (252 trading day) rolling high — denominator for drawdown
        max(close) over (
            partition by index_ticker
            order by date
            rows between 251 preceding and current row
        )                                                       as rolling_max_close_252d

    from base

)

select * from with_windows
