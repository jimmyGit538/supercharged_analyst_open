with observations as (

    select * from {{ ref('fred_economic_observations') }}

),

pivoted as (

    select
        date,
        max(
            case when series_id = 'FEDFUNDS' then value end
        ) as fed_funds_rate,
        max(
            case when series_id = 'DGS10' then value end
        ) as treasury_yield_10y,
        max(
            case when series_id = 'DGS2' then value end
        ) as treasury_yield_2y,
        max(
            case when series_id = 'MORTGAGE30US' then value end
        ) as mortgage_rate_30y,
        max(
            case when series_id = 'UNRATE' then value end
        ) as unemployment_rate,
        max(
            case when series_id = 'PAYEMS' then value end
        ) as nonfarm_payrolls,
        max(
            case when series_id = 'CPIAUCSL' then value end
        ) as cpi_all_urban,
        max(
            case when series_id = 'CPILFESL' then value end
        ) as core_cpi,
        max(
            case when series_id = 'PCEPI' then value end
        ) as pce_price_index,
        max(
            case when series_id = 'GDP' then value end
        ) as gdp_nominal,
        max(
            case when series_id = 'GDPC1' then value end
        ) as gdp_real,
        max(
            case when series_id = 'HOUST' then value end
        ) as housing_starts,
        max(
            case when series_id = 'UMCSENT' then value end
        ) as consumer_sentiment,
        max(
            case when series_id = 'INDPRO' then value end
        ) as industrial_production,
        max(
            case when series_id = 'MSPUS' then value end
        ) as median_home_price_national,
        max(
            case when series_id = 'AHETPI' then value end
        ) as avg_hourly_earnings

    from observations
    where
        series_id in (
            'FEDFUNDS',
            'DGS10',
            'DGS2',
            'MORTGAGE30US',
            'UNRATE',
            'PAYEMS',
            'CPIAUCSL',
            'CPILFESL',
            'PCEPI',
            'GDP',
            'GDPC1',
            'HOUST',
            'UMCSENT',
            'INDPRO',
            'MSPUS',
            'AHETPI'
        )
    group by date

)

select
    date,
    fed_funds_rate,
    treasury_yield_10y,
    treasury_yield_2y,
    mortgage_rate_30y,
    unemployment_rate,
    nonfarm_payrolls,
    cpi_all_urban,
    core_cpi,
    pce_price_index,
    gdp_nominal,
    gdp_real,
    housing_starts,
    consumer_sentiment,
    industrial_production,
    median_home_price_national,
    avg_hourly_earnings,
    treasury_yield_10y - treasury_yield_2y as yield_curve_spread,
    case
        when
            median_home_price_national is not null
            and avg_hourly_earnings is not null
            then median_home_price_national / (avg_hourly_earnings * 2080)
    end as housing_affordability_ratio

from pivoted
