-- ============================================================
-- OPENBOOK v1 — Supabase / Postgres schema
-- Match-only product exchange. No payments in-flow.
-- Money is stored in PENCE (integers) everywhere.
-- ============================================================

-- ---------- ENUMS ----------
create type bid_status as enum ('live','matched','completed','expired_unfilled','ghosted','cancelled');
create type ask_status as enum ('live','filled','cancelled');
create type match_status as enum ('pending','completed','ghosted','cancelled');
create type retailer_status as enum ('applied','verified','suspended');
create type fee_status as enum ('accrued','invoiced','paid','waived');

-- ---------- TAXONOMY ----------
create table categories (
  id          bigint generated always as identity primary key,
  slug        text not null unique,
  name        text not null,
  sort_order  int not null default 100
);

create table products (
  id          bigint generated always as identity primary key,
  slug        text not null unique,            -- 'bosch-series-4-wan28282gb'
  name        text not null,                   -- 'Bosch Series 4 Washing Machine'
  model_code  text,                            -- 'WAN28282GB' (the fungibility anchor)
  brand       text,
  category_id bigint not null references categories(id),
  rrp_pence   int not null,
  image_url   text,
  spec_line   text,                            -- '8kg · 1400rpm · New & boxed'
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);
create index products_category_idx on products(category_id) where is_active;

-- ---------- PEOPLE ----------
-- Buyers live in Supabase auth.users; profile adds app fields.
create table profiles (
  id            uuid primary key references auth.users(id) on delete cascade,
  display_name  text,
  is_admin      boolean not null default false,
  -- quiet buyer reputation (v1 anti-manipulation, no card auth)
  ghost_count   int not null default 0,
  completed_count int not null default 0,
  bids_hidden   boolean not null default false,  -- ghosted twice => bids stop counting toward visible curve
  created_at    timestamptz not null default now()
);

create table retailers (
  id                bigint generated always as identity primary key,
  owner_id          uuid not null references auth.users(id),
  company_name      text not null,
  companies_house_no text,
  website           text,
  checkout_domain   text,                       -- must match domain of checkout URLs
  status            retailer_status not null default 'applied',
  fee_rate_bps      int not null default 200,   -- 200 bps = 2%
  completion_rate   numeric(5,2),               -- maintained by trigger, shown to buyers
  deals_completed   int not null default 0,
  created_at        timestamptz not null default now()
);

-- ---------- THE BOOK ----------
create table bids (
  id          bigint generated always as identity primary key,
  product_id  bigint not null references products(id),
  user_id     uuid not null references auth.users(id),
  price_pence int not null check (price_pence > 0),
  status      bid_status not null default 'live',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  -- one live bid per user per product (they can cancel & re-bid)
  constraint one_live_bid unique nulls not distinct (product_id, user_id, status)
    deferrable initially deferred
);
-- NOTE: the unique constraint trick above only guards 'live' cleanly if we
-- null-out status on close; simpler + bulletproof is a partial unique index:
drop index if exists bids_one_live;
create unique index bids_one_live on bids(product_id, user_id) where status = 'live';
create index bids_ladder_idx on bids(product_id, price_pence desc) where status = 'live';

create table asks (
  id            bigint generated always as identity primary key,
  product_id    bigint not null references products(id),
  retailer_id   bigint not null references retailers(id),
  price_pence   int not null check (price_pence > 0),
  qty           int not null check (qty > 0),
  qty_remaining int not null,
  status        ask_status not null default 'live',
  created_at    timestamptz not null default now()
);
create index asks_ladder_idx on asks(product_id, price_pence asc) where status = 'live';

-- ---------- SWEEPS & MATCHES ----------
create table sweeps (
  id              bigint generated always as identity primary key,
  retailer_id     bigint not null references retailers(id),
  product_id      bigint not null references products(id),
  floor_pence     int not null,               -- accepted all live bids >= this
  bids_accepted   int not null,
  gross_pence     bigint not null,
  fee_pence       bigint not null,
  created_at      timestamptz not null default now()
);

create table matches (
  id            bigint generated always as identity primary key,
  match_ref     text not null unique,          -- 'OB-4F27K' — goes in checkout URL as click id
  bid_id        bigint not null references bids(id),
  sweep_id      bigint references sweeps(id),  -- null if matched against a resting ask
  ask_id        bigint references asks(id),
  product_id    bigint not null references products(id),
  retailer_id   bigint not null references retailers(id),
  user_id       uuid not null references auth.users(id),
  price_pence   int not null,
  status        match_status not null default 'pending',
  checkout_url  text not null,                 -- retailer URL incl. ?ob_ref=OB-XXXXX
  matched_at    timestamptz not null default now(),
  expires_at    timestamptz not null,          -- matched_at + 30 min
  completed_at  timestamptz,
  order_ref     text                           -- retailer's order id from postback
);
create index matches_pending_idx on matches(expires_at) where status = 'pending';
create index matches_user_idx on matches(user_id);
create index matches_retailer_idx on matches(retailer_id);

-- ---------- COMPLETION TRACKING (affiliate-style) ----------
create table postbacks (
  id          bigint generated always as identity primary key,
  match_ref   text not null,
  retailer_id bigint references retailers(id),
  order_ref   text,
  amount_pence int,
  source      text not null default 's2s',     -- 's2s' | 'pixel'
  ip          inet,
  raw         jsonb,
  received_at timestamptz not null default now(),
  processed   boolean not null default false
);
create index postbacks_ref_idx on postbacks(match_ref);

-- ---------- MONEY ----------
create table fee_ledger (
  id           bigint generated always as identity primary key,
  retailer_id  bigint not null references retailers(id),
  match_id     bigint not null references matches(id) unique,
  fee_pence    int not null,
  status       fee_status not null default 'accrued',
  invoice_id   bigint,
  created_at   timestamptz not null default now()
);

create table invoices (
  id           bigint generated always as identity primary key,
  retailer_id  bigint not null references retailers(id),
  period_start date not null,
  period_end   date not null,
  total_pence  bigint not null,
  issued_at    timestamptz,
  paid_at      timestamptz
);

-- ============================================================
-- VIEWS — what the front end actually reads
-- ============================================================

-- Public bid ladder (aggregated; hides users; excludes hidden buyers)
create view v_bid_ladder as
select b.product_id,
       b.price_pence,
       count(*)::int as bid_count
from bids b
join profiles p on p.id = b.user_id
where b.status = 'live' and not p.bids_hidden
group by b.product_id, b.price_pence;

-- Public ask ladder
create view v_ask_ladder as
select product_id, price_pence, sum(qty_remaining)::int as units
from asks
where status = 'live'
group by product_id, price_pence;

-- Retailer demand curve (cumulative units & gross at each floor)
create view v_demand_curve as
select l.product_id,
       l.price_pence,
       l.bid_count,
       sum(l.bid_count) over w              as cume_bids,
       sum(l.bid_count * l.price_pence) over w as cume_gross_pence
from v_bid_ladder l
window w as (partition by l.product_id order by l.price_pence desc);

-- Market summary for homepage rows
create view v_market_summary as
select p.id as product_id, p.slug, p.name, p.rrp_pence,
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
where p.is_active;

-- ============================================================
-- CORE FUNCTION — the sweep, fully transactional
-- ============================================================
create or replace function sweep_bids(
  p_retailer_id bigint,
  p_product_id  bigint,
  p_floor_pence int,
  p_max_units   int default null,        -- optional cap ('I only have 40')
  p_checkout_base text default null      -- e.g. 'https://kitchendirect.co.uk/ob-checkout'
) returns bigint                          -- sweep id
language plpgsql security definer as $$
declare
  v_sweep_id bigint;
  v_fee_bps  int;
  v_gross    bigint := 0;
  v_count    int := 0;
  r          record;
  v_ref      text;
begin
  select fee_rate_bps into v_fee_bps from retailers
    where id = p_retailer_id and status = 'verified';
  if v_fee_bps is null then
    raise exception 'retailer not verified';
  end if;

  -- create the sweep shell first
  insert into sweeps(retailer_id, product_id, floor_pence, bids_accepted, gross_pence, fee_pence)
  values (p_retailer_id, p_product_id, p_floor_pence, 0, 0, 0)
  returning id into v_sweep_id;

  -- lock & take qualifying bids, best price first, oldest first at each level
  for r in
    select b.id, b.user_id, b.price_pence
    from bids b
    join profiles pr on pr.id = b.user_id
    where b.product_id = p_product_id
      and b.status = 'live'
      and not pr.bids_hidden
      and b.price_pence >= p_floor_pence
    order by b.price_pence desc, b.created_at asc
    for update of b skip locked
  loop
    exit when p_max_units is not null and v_count >= p_max_units;

    v_ref := 'OB-' || upper(substr(md5(random()::text || clock_timestamp()::text), 1, 5));

    update bids set status = 'matched', updated_at = now() where id = r.id;

    insert into matches(match_ref, bid_id, sweep_id, product_id, retailer_id,
                        user_id, price_pence, checkout_url, expires_at)
    values (v_ref, r.id, v_sweep_id, p_product_id, p_retailer_id,
            r.user_id, r.price_pence,
            coalesce(p_checkout_base,'') || '?ob_ref=' || v_ref
              || '&price=' || r.price_pence,
            now() + interval '30 minutes');

    v_count := v_count + 1;
    v_gross := v_gross + r.price_pence;
  end loop;

  update sweeps
     set bids_accepted = v_count,
         gross_pence   = v_gross,
         fee_pence     = (v_gross * v_fee_bps) / 10000
   where id = v_sweep_id;

  return v_sweep_id;
end $$;

-- ============================================================
-- COMPLETION — postback flips the match, accrues the fee
-- ============================================================
create or replace function process_postback(p_match_ref text, p_order_ref text)
returns void language plpgsql security definer as $$
declare
  m matches%rowtype;
  v_fee_bps int;
begin
  select * into m from matches where match_ref = p_match_ref for update;
  if not found or m.status <> 'pending' then return; end if;

  update matches
     set status='completed', completed_at=now(), order_ref=p_order_ref
   where id = m.id;
  update bids set status='completed', updated_at=now() where id = m.bid_id;

  update profiles set completed_count = completed_count + 1 where id = m.user_id;

  select fee_rate_bps into v_fee_bps from retailers where id = m.retailer_id;
  insert into fee_ledger(retailer_id, match_id, fee_pence)
  values (m.retailer_id, m.id, (m.price_pence * v_fee_bps) / 10000);

  update retailers r
     set deals_completed = deals_completed + 1,
         completion_rate = (
           select round(100.0 * count(*) filter (where status='completed')
                  / nullif(count(*) filter (where status in ('completed','ghosted')),0), 2)
           from matches where retailer_id = r.id)
   where id = m.retailer_id;
end $$;

-- ============================================================
-- EXPIRY — cron job (Supabase pg_cron, every minute)
-- ============================================================
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
        where pr.id = e.user_id)
  select count(*) into v_n from expired;
  return v_n;
end $$;
-- select cron.schedule('expire-matches', '* * * * *', $$select expire_matches()$$);

-- ============================================================
-- RLS — tight by default
-- ============================================================
alter table profiles   enable row level security;
alter table bids       enable row level security;
alter table asks       enable row level security;
alter table matches    enable row level security;
alter table retailers  enable row level security;
alter table sweeps     enable row level security;
alter table fee_ledger enable row level security;
alter table postbacks  enable row level security;

create policy "own profile"      on profiles for all    using (auth.uid() = id);
create policy "own bids"         on bids     for select using (auth.uid() = user_id);
create policy "place bid"        on bids     for insert with check (auth.uid() = user_id);
create policy "cancel own bid"   on bids     for update using (auth.uid() = user_id);
create policy "own matches"      on matches  for select using (auth.uid() = user_id);
create policy "retailer matches" on matches  for select
  using (retailer_id in (select id from retailers where owner_id = auth.uid()));
create policy "own retailer"     on retailers for all
  using (owner_id = auth.uid());
create policy "retailer sweeps"  on sweeps   for select
  using (retailer_id in (select id from retailers where owner_id = auth.uid()));
create policy "retailer fees"    on fee_ledger for select
  using (retailer_id in (select id from retailers where owner_id = auth.uid()));
-- Ladders/curves are exposed via the views through the API only;
-- products & categories are public read:
alter table products   enable row level security;
alter table categories enable row level security;
create policy "public products"   on products   for select using (true);
create policy "public categories" on categories for select using (true);

-- ============================================================
-- SEED — launch vertical
-- ============================================================
insert into categories(slug,name,sort_order) values
 ('washing-machines','Washing machines',1),
 ('air-fryers','Air fryers',2),
 ('tvs','TVs',3),
 ('vacuums','Vacuums',4);

insert into products(slug,name,model_code,brand,category_id,rrp_pence,spec_line) values
 ('bosch-series-4-wan28282gb','Bosch Series 4 Washing Machine','WAN28282GB','Bosch',1,49900,'8kg · 1400rpm · New & boxed'),
 ('ninja-n2-af210uk','Ninja N2 Air Fryer','AF210UK','Ninja',2,9999,'4.7L · New & sealed');
