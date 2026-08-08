-- State-level affordability: FHFA house price index (annual) against QCEW average
-- weekly wages (quarterly), keyed on the 2-digit state FIPS code embedded in the
-- FRED series id.
--
--   ATNHPIUS<FIPS>000A  -> house price index,     annual
--   ENUC<FIPS>40010SA   -> average weekly wage,   quarterly
--
-- The two series report on different calendars, so the grain is built from the
-- union of both: a row exists wherever at least one of the two reported on that
-- date, and the other column is NULL.

with house_price_index as (

    select
        date,
        value as house_price_index,
        regexp_extract(series_id, r'^ATNHPIUS(\d{2})000A$') as state_fips
    from {{ ref('fred_economic_observations') }}
    where
        regexp_contains(series_id, r'^ATNHPIUS\d{2}000A$')
        and value is not null

),

weekly_wage as (

    select
        date,
        value as avg_weekly_wage,
        regexp_extract(series_id, r'^ENUC(\d{2})40010SA$') as state_fips
    from {{ ref('fred_economic_observations') }}
    where
        regexp_contains(series_id, r'^ENUC\d{2}40010SA$')
        and value is not null

),

state_dates as (

    select
        state_fips,
        date
    from house_price_index

    union distinct

    select
        state_fips,
        date
    from weekly_wage

)

select
    spine.state_fips,
    spine.date,
    hpi.house_price_index,
    wage.avg_weekly_wage,
    -- An index-to-dollars ratio, not an absolute affordability measure.
    -- Comparable across time within a state, not across states.
    safe_divide(
        hpi.house_price_index, wage.avg_weekly_wage
    ) as housing_affordability_ratio
from state_dates as spine
left join house_price_index as hpi
    on
        spine.state_fips = hpi.state_fips
        and spine.date = hpi.date
left join weekly_wage as wage
    on
        spine.state_fips = wage.state_fips
        and spine.date = wage.date
