{{
    config(
        materialized='table',
        schema='warehouses'
    )
}}

select
    index_ticker,
    index_name,
    asset_class,
    currency,
    cast(inception_date as date)    as inception_date

from {{ ref('indices_metadata') }}
