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
        cast(coin_id as int64) as coin_id,
        cast(symbol as string) as symbol,
        cast(name as string) as name,  -- noqa: RF04
        cast(slug as string) as slug,
        cast(description as string) as description,  -- noqa: RF04
        cast(category as string) as category,  -- noqa: RF04
        cast(tags as string) as tags,
        cast(website as string) as website,
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
