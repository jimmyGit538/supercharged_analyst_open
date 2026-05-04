{{
    config(
        materialized='view',
        schema='staging'
    )
}}

with source as (

    select * from {{ source('raw', 'coinmarketcap_category_coins') }}

),

cleaned as (

    select
        cast(category_id as string)   as category_id,
        cast(category_name as string) as category_name,
        cast(coin_id as int64)        as coin_id,
        cast(coin_symbol as string)   as coin_symbol,
        cast(coin_name as string)     as coin_name,
        cast(coin_slug as string)     as coin_slug,
        cast(cmc_rank as int64)       as cmc_rank,
        extracted_at

    from source

    where category_id is not null and coin_id is not null

),

deduped as (

    select
        *,
        row_number() over (
            partition by category_id, coin_id
            order by extracted_at desc
        ) as _row_num

    from cleaned

)

select
    category_id,
    category_name,
    coin_id,
    coin_symbol,
    coin_name,
    coin_slug,
    cmc_rank,
    extracted_at

from deduped

where _row_num = 1
