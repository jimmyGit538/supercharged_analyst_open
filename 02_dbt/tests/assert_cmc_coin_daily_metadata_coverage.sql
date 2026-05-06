select distinct f.coin_id
from {{ ref('fct_cmc_coin_daily') }} f
left join {{ ref('wh_cmc_coin_metadata') }} m using (coin_id)
where m.coin_id is null
