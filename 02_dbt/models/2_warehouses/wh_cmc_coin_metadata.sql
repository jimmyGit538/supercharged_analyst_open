{{
    config(
        materialized='table',
        schema='warehouses'
    )
}}

with staged as (

    select * from {{ ref('stg_coinmarketcap__coin_metadata') }}

)

select
    coin_id,
    symbol,
    name,
    slug,
    description,
    category,
    tags,
    website,
    current_timestamp() as _loaded_at

from staged
