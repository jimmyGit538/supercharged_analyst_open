{{
    config(
        materialized='view',
        schema='staging'
    )
}}

with source as (

    select * from {{ source('raw', 'coinmarketcap_categories') }}

),

cleaned as (

    select
        cast(id as string)           as id,
        cast(name as string)         as name,
        cast(num_tokens as int64)    as num_tokens,
        cast(market_cap_usd as numeric) as market_cap_usd,
        cast(market_cap_change as numeric) as market_cap_change,
        cast(volume_usd as numeric)  as volume_usd,
        cast(volume_change as numeric) as volume_change,
        cast(last_updated as string) as last_updated,
        extracted_at

    from source

    where id is not null

),

deduped as (

    select
        *,
        row_number() over (
            partition by id
            order by extracted_at desc
        ) as _row_num

    from cleaned

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
    extracted_at

from deduped

where _row_num = 1
