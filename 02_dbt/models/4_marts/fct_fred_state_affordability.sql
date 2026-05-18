{{
    config(
        materialized='incremental',
        schema='marts',
        unique_key=['state_fips', 'date'],
        partition_by={
            'field': 'date',
            'data_type': 'date',
            'granularity': 'year'
        },
        cluster_by=['state_fips']
    )
}}

with source as (

    select * from {{ ref('stg_fred_economic__state_affordability') }}

    {% if is_incremental() %}
        where date > (select max(date) from {{ this }})  -- noqa: RF02
    {% endif %}

)

select
    state_fips,
    date,
    house_price_index,
    avg_weekly_wage,
    housing_affordability_ratio,
    current_timestamp() as _loaded_at

from source
