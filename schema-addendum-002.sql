-- OPENBOOK addendum 002 — retail floor price
alter table products add column if not exists retail_price_pence int;
alter table products add column if not exists retail_checked_at timestamptz;

drop view if exists v_market_summary;
create view v_market_summary as
select p.id as product_id, p.slug, p.name, p.brand, p.spec_line,
       p.rrp_pence, p.retail_price_pence, p.category_id,
       c.slug as category_slug, c.name as category_name,
       (select max(price_pence) from bids b join profiles pr on pr.id=b.user_id
         where b.product_id=p.id and b.status='live' and not pr.bids_hidden) as best_bid_pence,
       (select min(price_pence) from asks a
         where a.product_id=p.id and a.status='live')                        as best_ask_pence,
       (select count(*) from bids b join profiles pr on pr.id=b.user_id
         where b.product_id=p.id and b.status='live' and not pr.bids_hidden) as live_bids,
       (select m.price_pence from matches m
         where m.product_id=p.id and m.status='completed'
         order by m.completed_at desc limit 1)                               as last_matched_pence
from products p
join categories c on c.id = p.category_id
where p.is_active;

grant select on v_market_summary to anon, authenticated;
