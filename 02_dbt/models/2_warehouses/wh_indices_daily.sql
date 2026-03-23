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

with staged as (

    select * from {{ ref('stg_twelvedata__indices_prices') }}

    {% if is_incremental() %}
    where date > (select max(date) from {{ this }})
    {% endif %}

),

with_seq as (

    select
        index_ticker,
        date,
        open,
        high,
        low,
        close,
        volume,
        -- Sequential trading day number per ticker; enables trivial lag/lead in downstream models
        row_number() over (
            partition by index_ticker
            order by date
        )                               as trading_day_seq,
        current_timestamp()             as _loaded_at

    from staged

)

select * from with_seq
