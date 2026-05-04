{{
    config(
        materialized='view',
        schema='staging'
    )
}}

with source as (

    select * from {{ source('raw', 'coinmarketcap_coin_metadata') }}

),

cleaned as (

    select
        cast(coin_id as int64)       as coin_id,
        cast(symbol as string)       as symbol,
        cast(name as string)         as name,
        cast(slug as string)         as slug,
        cast(description as string)  as description,
        cast(category as string)     as category,
        cast(tags as string)         as tags,
        cast(website as string)      as website,
        extracted_at

    from source

    where coin_id is not null

),

deduped as (

    select
        *,
        row_number() over (
            partition by coin_id
            order by extracted_at desc
        ) as _row_num

    from cleaned

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
    extracted_at

from deduped

where _row_num = 1
