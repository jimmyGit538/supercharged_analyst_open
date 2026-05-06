select f.index_ticker, f.date
from {{ ref('fct_indices_daily_wide') }} f
left join {{ ref('wh_indices_daily') }} d using (index_ticker, date)
where d.date is null
