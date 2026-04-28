{{
    config(
        materialized='table',
        schema='warehouses'
    )
}}

select
    lower(symbol)    as index_ticker,
    name             as index_name,
    instrument_type  as asset_class,
    currency

from {{ source('raw', 'twelvedata_symbols_metadata') }}
