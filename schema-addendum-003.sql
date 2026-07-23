-- OPENBOOK addendum 003 — seller wallet, order acceptance, auto-refunds
alter table retailers add column if not exists balance_pence bigint not null default 0;
alter table retailers alter column fee_rate_bps set default 100;  -- 1%
update retailers set fee_rate_bps = 100;

create table if not exists wallet_ledger (
  id          bigint generated always as identity primary key,
  retailer_id bigint not null references retailers(id),
  amount_pence bigint not null,             -- +topup/+refund, -fee
  kind        text not null,                -- 'topup' | 'fee' | 'refund'
  match_id    bigint references matches(id),
  note        text,
  created_at  timestamptz not null default now()
);
alter table wallet_ledger enable row level security;
create policy "own ledger" on wallet_ledger for select
  using (retailer_id in (select id from retailers where owner_id = auth.uid()));

-- sellers may apply (insert their own retailer row)
drop policy if exists "own retailer" on retailers;
create policy "own retailer" on retailers for all
  using (owner_id = auth.uid()) with check (owner_id = auth.uid());

-- ============ accept orders: the seller's core action ============
create or replace function accept_orders(
  p_product_id  bigint,
  p_floor_pence int,
  p_checkout_base text,
  p_max_units   int default null
) returns jsonb
language plpgsql security definer as $$
declare
  v_ret     retailers%rowtype;
  v_sweep_id bigint;
  v_gross   bigint := 0;
  v_fee     bigint := 0;
  v_count   int := 0;
  r         record;
  v_ref     text;
  v_this_fee bigint;
begin
  select * into v_ret from retailers
   where owner_id = auth.uid() and status = 'verified';
  if not found then
    return jsonb_build_object('error','Seller account not verified yet');
  end if;
  if p_checkout_base is null or p_checkout_base !~ '^https://' then
    return jsonb_build_object('error','Checkout link must be a full https:// URL');
  end if;

  insert into sweeps(retailer_id, product_id, floor_pence, bids_accepted, gross_pence, fee_pence)
  values (v_ret.id, p_product_id, p_floor_pence, 0, 0, 0)
  returning id into v_sweep_id;

  for r in
    select b.id, b.user_id, b.price_pence
    from bids b join profiles pr on pr.id = b.user_id
    where b.product_id = p_product_id and b.status = 'live'
      and not pr.bids_hidden and b.price_pence >= p_floor_pence
    order by b.price_pence desc, b.created_at asc
    for update of b skip locked
  loop
    exit when p_max_units is not null and v_count >= p_max_units;
    v_this_fee := (r.price_pence * v_ret.fee_rate_bps) / 10000;
    -- stop if balance exhausted
    exit when (select balance_pence from retailers where id = v_ret.id) < v_fee + v_this_fee;

    v_ref := 'OB-' || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 5));
    update bids set status = 'matched', updated_at = now() where id = r.id;
    insert into matches(match_ref, bid_id, sweep_id, product_id, retailer_id,
                        user_id, price_pence, checkout_url, expires_at)
    values (v_ref, r.id, v_sweep_id, p_product_id, v_ret.id, r.user_id, r.price_pence,
            p_checkout_base || (case when p_checkout_base like '%?%' then '&' else '?' end)
              || 'ob_ref=' || v_ref || '&price=' || r.price_pence,
            now() + interval '30 minutes');
    insert into wallet_ledger(retailer_id, amount_pence, kind, match_id,
                              note)
    values (v_ret.id, -v_this_fee, 'fee', currval(pg_get_serial_sequence('matches','id')),
            'Order accepted at ' || r.price_pence || 'p');
    v_count := v_count + 1;
    v_gross := v_gross + r.price_pence;
    v_fee   := v_fee + v_this_fee;
  end loop;

  update retailers set balance_pence = balance_pence - v_fee where id = v_ret.id;
  update sweeps set bids_accepted = v_count, gross_pence = v_gross, fee_pence = v_fee
   where id = v_sweep_id;

  return jsonb_build_object('accepted', v_count, 'gross_pence', v_gross,
                            'fee_pence', v_fee, 'sweep_id', v_sweep_id);
end $$;
grant execute on function accept_orders(bigint,int,text,int) to authenticated;

-- ============ expiry now refunds the fee on ghosted matches ============
create or replace function expire_matches()
returns int language plpgsql security definer as $$
declare v_n int;
begin
  with expired as (
    update matches set status='ghosted'
    where status='pending' and expires_at < now()
    returning id, bid_id, user_id, retailer_id
  ),
  b as (update bids set status='ghosted', updated_at=now()
        where id in (select bid_id from expired)),
  p as (update profiles pr
        set ghost_count = ghost_count + e.c,
            bids_hidden = (ghost_count + e.c) >= 2
        from (select user_id, count(*) c from expired group by user_id) e
        where pr.id = e.user_id),
  refunds as (
    insert into wallet_ledger(retailer_id, amount_pence, kind, match_id, note)
    select wl.retailer_id, -wl.amount_pence, 'refund', wl.match_id,
           'Buyer did not complete — fee credited back'
    from wallet_ledger wl
    where wl.kind='fee' and wl.match_id in (select id from expired)
    returning retailer_id, amount_pence
  ),
  rb as (
    update retailers r set balance_pence = balance_pence + s.amt
    from (select retailer_id, sum(amount_pence) amt from refunds group by retailer_id) s
    where r.id = s.retailer_id)
  select count(*) into v_n from expired;
  return v_n;
end $$;

-- seller's view of demand per product (already granted: v_demand_curve, v_market_summary)
