{{
    config(
        materialized='incremental',
        schema='marts',
        unique_key=['date'],
        partition_by={
            'field': 'date',
            'data_type': 'date',
            'granularity': 'month'
        }
    )
}}

with source as (

    select * from {{ ref('stg_fred_economic__indicators') }}

    {% if is_incremental() %}
        where date > (select max(date) from {{ this }})  -- noqa: RF02
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

from source
