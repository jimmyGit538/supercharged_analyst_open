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

with staged as (

    select * from {{ ref('stg_indices__rolling_stats') }}

),

metadata as (

    select index_ticker, index_name from {{ ref('wh_indices_metadata') }}

),

final as (

    select
        s.index_ticker,
        m.index_name,
        s.date,
        s.close,
        s.trading_day_seq,
        s.ma_20d,
        s.ma_50d,
        s.vol_20d_annualized,
        s.rolling_max_close_252d,

        -- Drawdown from 52-week high: always <= 0 (0 = at or above the prior 252d peak)
        safe_divide(
            s.close - s.rolling_max_close_252d,
            s.rolling_max_close_252d
        )                                                       as drawdown_from_52w_high,

        current_timestamp()                                     as _loaded_at

    from staged s
    inner join metadata m
        on s.index_ticker = m.index_ticker

)

select * from final
