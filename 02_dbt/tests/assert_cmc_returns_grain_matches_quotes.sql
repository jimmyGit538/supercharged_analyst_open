select r.date, r.coin_id
from {{ ref('wh_cmc_returns') }} r
left join {{ ref('wh_cmc_quotes_daily') }} q using (date, coin_id)
where q.date is null
