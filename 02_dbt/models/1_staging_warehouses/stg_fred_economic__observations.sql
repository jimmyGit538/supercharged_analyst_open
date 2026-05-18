with source as (

    select * from {{ source('raw', 'fred_economic_observations') }}

),

filtered as (

    select *
    from source
    where
        series_id is not null
        and date is not null

),

deduped as (

    select
        series_id,
        date,
        value,
        extracted_at,
        row_number() over (
            partition by series_id, date
            order by extracted_at desc
        ) as row_num

    from filtered

)

select
    series_id,
    date,
    value,
    extracted_at

from deduped
where row_num = 1
