{{
    config(
        materialized='table',
        schema='marts',
        partition_by={
            'field': 'date',
            'data_type': 'date',
            'granularity': 'month'
        },
        cluster_by=['index_ticker']
    )
}}

with daily as (

    select * from {{ ref('wh_indices_daily') }}

),

returns as (

    select * from {{ ref('wh_indices_returns') }}

),

metadata as (

    select * from {{ ref('wh_indices_metadata') }}

),

joined as (

    select
        d.index_ticker,
        m.index_name,
        m.asset_class,
        m.currency,
        m.inception_date,
        d.date,
        d.open,
        d.high,
        d.low,
        d.close,
        d.volume,
        d.trading_day_seq,
        r.prior_close,
        r.daily_return,
        r.wtd_return,
        r.mtd_return,
        r.ytd_return,
        current_timestamp()             as _loaded_at

    from daily d
    inner join returns r
        on  d.index_ticker = r.index_ticker
        and d.date         = r.date
    inner join metadata m
        on d.index_ticker = m.index_ticker

)

select * from joined
