-- Warehouse table for FRED observations. One row per (series_id, date).
-- Incremental on date: only observations at or after the current maximum date
-- are reprocessed, which also lets FRED revisions to recent periods overwrite
-- the stored value via the merge on (series_id, date).

{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key=['series_id', 'date'],
        partition_by={
            'field': 'date',
            'data_type': 'date',
            'granularity': 'month'
        },
        cluster_by=['series_id']
    )
}}

with staged as (

    select
        series_id,
        date,
        value,
        extracted_at
    from {{ ref('stg_fred_economic__observations') }}

    {% if is_incremental() %}
        -- Re-read a 90-day tail so late-arriving revisions are merged in.
        where date >= (
            select date_sub(max(existing.date), interval 90 day)
            from {{ this }} as existing
        )
    {% endif %}

)

select
    series_id,
    date,
    value,
    extracted_at,
    current_timestamp() as _loaded_at
from staged
