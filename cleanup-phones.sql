-- OPENBOOK: phones-only cleanup. Removes every non-phone product and
-- its dependent rows, then the unused categories. Safe to run once.
begin;
create temp table doomed as
  select id from products
  where category_id <> (select id from categories where slug = 'phones');
delete from fee_ledger where match_id in (select id from matches where product_id in (select id from doomed));
delete from matches  where product_id in (select id from doomed);
delete from bids     where product_id in (select id from doomed);
delete from asks     where product_id in (select id from doomed);
delete from products where id in (select id from doomed);
delete from categories where slug <> 'phones';
commit;
select count(*) as products_left from products;
