-- State-level affordability view. One row per (state_fips, date).
-- House price index series pattern: ATNHPIUS<FIPS>A  (annual, FIPS = 5 chars)
-- Avg weekly wage series pattern:   ENUC<FIPS>40010SA (quarterly)
-- FIPS is extracted as the 2-digit state code from both patterns.
with observations as (

    select * from {{ ref('fred_economic_observations') }}

),

hpi as (

    -- FHFA house price index: ATNHPIUS06000A -> state_fips '06'
    select
        date,
        value as house_price_index,
        regexp_extract(series_id, r'^ATNHPIUS(\d{2})\d{3}A$', 1) as state_fips

    from observations
    where
        regexp_contains(series_id, r'^ATNHPIUS\d{5}A$')
        and value is not null

),

wages as (

    -- Avg weekly wage: ENUC060040010SA -> state_fips '06'
    select
        date,
        value as avg_weekly_wage,
        regexp_extract(series_id, r'^ENUC(\d{2})\d{2}40010SA$', 1)
            as state_fips

    from observations
    where
        regexp_contains(series_id, r'^ENUC\d{4}40010SA$')
        and value is not null

),

joined as (

    select
        hpi.house_price_index,
        wages.avg_weekly_wage,  -- noqa: RF04
        coalesce(hpi.state_fips, wages.state_fips) as state_fips,
        coalesce(hpi.date, wages.date) as date  -- noqa: RF04  -- noqa: RF04

    from hpi
    full outer join wages
        on
            hpi.state_fips = wages.state_fips
            and hpi.date = wages.date

)

select
    state_fips,
    date,
    house_price_index,
    avg_weekly_wage,
    case
        when house_price_index is not null and avg_weekly_wage is not null
            then house_price_index / avg_weekly_wage
    end as housing_affordability_ratio

from joined
where
    state_fips is not null
    and date is not null
