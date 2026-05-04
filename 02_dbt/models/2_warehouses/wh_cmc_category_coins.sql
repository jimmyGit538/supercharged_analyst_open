{{
    config(
        materialized='table',
        schema='warehouses'
    )
}}

with staged as (

    select * from {{ ref('stg_coinmarketcap__category_coins') }}

)

select
    category_id,
    category_name,
    coin_id,
    coin_symbol,
    coin_name,
    coin_slug,
    cmc_rank,
    current_timestamp() as _loaded_at

from staged
