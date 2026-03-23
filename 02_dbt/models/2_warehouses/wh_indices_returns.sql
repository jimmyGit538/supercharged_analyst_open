{{
    config(
        materialized='incremental',
        schema='warehouses',
        unique_key=['index_ticker', 'date'],
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

    {% if is_incremental() %}
    -- Pull back 7 days so LAG has prior-day close available for the first new row
    where date >= (
        select date_sub(max(date), interval 7 day) from {{ this }}
    )
    {% endif %}

),

with_returns as (

    select
        index_ticker,
        date,
        close,

        -- Prior close via LAG — null on the first trading day of the partition
        lag(close, 1) over (
            partition by index_ticker
            order by date
        )                                                       as prior_close,

        -- Daily return
        safe_divide(
            close - lag(close, 1) over (partition by index_ticker order by date),
            lag(close, 1) over (partition by index_ticker order by date)
        )                                                       as daily_return,

        -- WTD: return vs the close of the last day of the prior week (Sunday)
        safe_divide(
            close - first_value(close) over (
                partition by index_ticker,
                    date_trunc(date, week(monday))
                order by date
                rows between unbounded preceding and 1 preceding
            ),
            first_value(close) over (
                partition by index_ticker,
                    date_trunc(date, week(monday))
                order by date
                rows between unbounded preceding and 1 preceding
            )
        )                                                       as wtd_return,

        -- MTD: return vs the close of the last trading day before the 1st of the month
        safe_divide(
            close - first_value(close) over (
                partition by index_ticker,
                    date_trunc(date, month)
                order by date
                rows between unbounded preceding and 1 preceding
            ),
            first_value(close) over (
                partition by index_ticker,
                    date_trunc(date, month)
                order by date
                rows between unbounded preceding and 1 preceding
            )
        )                                                       as mtd_return,

        -- YTD: return vs the close of the last trading day before Jan 1
        safe_divide(
            close - first_value(close) over (
                partition by index_ticker,
                    date_trunc(date, year)
                order by date
                rows between unbounded preceding and 1 preceding
            ),
            first_value(close) over (
                partition by index_ticker,
                    date_trunc(date, year)
                order by date
                rows between unbounded preceding and 1 preceding
            )
        )                                                       as ytd_return,

        current_timestamp()                                     as _loaded_at

    from daily

),

-- Strip the look-back buffer rows that already exist in the target table
final as (

    select * from with_returns

    {% if is_incremental() %}
    where date > (select max(date) from {{ this }})
    {% endif %}

)

select * from final
