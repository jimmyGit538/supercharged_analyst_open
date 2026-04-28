{{
    config(
        materialized='table',
        schema='warehouses'
    )
}}

select
    name as index_name,
    instrument_type as asset_class,
    currency,
    lower(symbol) as index_ticker

from {{ source('raw', 'twelvedata_symbols_metadata') }}
