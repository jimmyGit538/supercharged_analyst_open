select cc.category_id
from {{ ref('wh_cmc_category_coins') }} cc
left join {{ ref('wh_cmc_categories') }} c on cc.category_id = c.id
where c.id is null
