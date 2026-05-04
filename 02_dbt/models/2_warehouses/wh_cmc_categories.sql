{{
    config(
        materialized='table',
        schema='warehouses'
    )
}}

with staged as (

    select * from {{ ref('stg_coinmarketcap__categories') }}

)

select
    id,
    name,
    num_tokens,
    market_cap_usd,
    market_cap_change,
    volume_usd,
    volume_change,
    last_updated,
    current_timestamp() as _loaded_at

from staged
