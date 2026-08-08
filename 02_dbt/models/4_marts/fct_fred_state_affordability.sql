-- State-level affordability fact table. One row per (state_fips, date).

{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['state_fips', 'date'],
        partition_by={
            'field': 'date',
            'data_type': 'date',
            'granularity': 'year'
        },
        cluster_by=['state_fips']
    )
}}

with affordability as (

    select *
    from {{ ref('stg_fred_economic__state_affordability') }}

    {% if is_incremental() %}
        -- Both source series are revised well after first publication, and the
        -- HPI series is annual — re-read three years rather than a short tail.
        where date >= (
            select date_sub(max(existing.date), interval 3 year)
            from {{ this }} as existing
        )
    {% endif %}

)

select
    state_fips,
    date,
    house_price_index,
    avg_weekly_wage,
    housing_affordability_ratio,
    current_timestamp() as _loaded_at
from affordability
