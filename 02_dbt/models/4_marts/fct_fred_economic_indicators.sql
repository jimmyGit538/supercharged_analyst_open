-- National macro fact table for Looker Studio. One row per date.

{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='date',
        partition_by={
            'field': 'date',
            'data_type': 'date',
            'granularity': 'month'
        }
    )
}}

with indicators as (

    select *
    from {{ ref('stg_fred_economic__indicators') }}

    {% if is_incremental() %}
        -- Re-read a 90-day tail: FRED revises recent months after first release.
        where date >= (
            select date_sub(max(existing.date), interval 90 day)
            from {{ this }} as existing
        )
    {% endif %}

)

select
    date,
    fed_funds_rate,
    treasury_yield_10y,
    treasury_yield_2y,
    yield_curve_spread,
    mortgage_rate_30y,
    unemployment_rate,
    nonfarm_payrolls,
    cpi_all_urban,
    core_cpi,
    pce_price_index,
    gdp_nominal,
    gdp_real,
    housing_starts,
    consumer_sentiment,
    industrial_production,
    median_home_price_national,
    avg_hourly_earnings,
    housing_affordability_ratio,
    current_timestamp() as _loaded_at
from indicators
