select r.index_ticker, r.date
from {{ ref('wh_indices_returns') }} r
left join {{ ref('wh_indices_daily') }} d using (index_ticker, date)
where d.date is null
