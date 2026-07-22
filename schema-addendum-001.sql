-- ============================================================
-- OPENBOOK schema addendum 001 — browsable markets
-- Run AFTER openbook-schema.sql
-- ============================================================

drop view if exists v_market_summary;
create view v_market_summary as
select p.id as product_id, p.slug, p.name, p.brand, p.spec_line,
       p.rrp_pence, p.category_id, c.slug as category_slug, c.name as category_name,
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

-- category counts for the browse page chips
create or replace view v_category_summary as
select c.id, c.slug, c.name, c.sort_order,
       count(p.id)::int as market_count,
       coalesce(sum((select count(*) from bids b where b.product_id=p.id and b.status='live')),0)::int as live_bids
from categories c
left join products p on p.category_id = c.id and p.is_active
group by c.id, c.slug, c.name, c.sort_order
order by c.sort_order;

-- grants for the anon-key front end
grant usage on schema public to anon, authenticated;
grant select on v_market_summary, v_category_summary,
                v_bid_ladder, v_ask_ladder, v_demand_curve
  to anon, authenticated;
