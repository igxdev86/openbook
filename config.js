/* ============ OPENBOOK config & data layer ============
   1. Create the Supabase project, run openbook-schema.sql,
      then schema-addendum-001.sql, then seed-products.sql
   2. Paste your project URL + anon key below. Until then the
      site runs on built-in demo data (yellow banner shows).
======================================================== */

const SUPABASE_URL = "https://webxitknbugyawafukvb.supabase.co";      // e.g. "https://abcd1234.supabase.co"
const SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndlYnhpdGtuYnVneWF3YWZ1a3ZiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODQ3NTQzNzMsImV4cCI6MjEwMDMzMDM3M30.HbAnHJepUgU2zBqp2kqtzl3BQbbqDA-zOgBfFch_6Tw"; // anon public key — safe in the page, RLS guards everything

const DEMO = !SUPABASE_URL || !SUPABASE_ANON_KEY;
let sb = null;
if (!DEMO) sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

/* ---------- formatting & urls ---------- */
const P = p => '£' + (p / 100).toLocaleString('en-GB', {
  minimumFractionDigits: (p % 100 === 0 ? 0 : 2), maximumFractionDigits: 2 });
const PCT_OFF = (price, rrp) => Math.round((1 - price / rrp) * 100);

/* clean /m/slug URLs on the deployed site (vercel.json rewrite),
   ?p= fallback for local files and previews */
const DEPLOYED = location.protocol.startsWith('http');
const marketUrl = slug => DEPLOYED ? '/m/' + slug : 'market.html?p=' + slug;
function currentSlug(){
  const m = location.pathname.match(/^\/m\/([^\/]+)/);
  if (m) return decodeURIComponent(m[1]);
  return new URLSearchParams(location.search).get('p');
}

/* ---------- demo data ---------- */
const DEMO_CATEGORIES = [
  { slug:'washing-machines', name:'Washing machines', market_count:7 },
  { slug:'air-fryers', name:'Air fryers', market_count:5 },
  { slug:'tvs', name:'TVs', market_count:6 },
  { slug:'vacuums', name:'Vacuums', market_count:5 },
  { slug:'audio', name:'Audio', market_count:6 },
  { slug:'gaming', name:'Gaming', market_count:6 }
];
const DEMO_MARKETS = [
  { slug:'bosch-series-4-wan28282gb', name:'Bosch Series 4 Washing Machine', brand:'Bosch',
    category_slug:'washing-machines', rrp_pence:49900, best_bid_pence:47800,
    best_ask_pence:48200, live_bids:312, last_matched_pence:47800,
    spec_line:'8kg · 1400rpm · New & boxed' },
  { slug:'ninja-n2-af210uk', name:'Ninja N2 Air Fryer', brand:'Ninja',
    category_slug:'air-fryers', rrp_pence:9999, best_bid_pence:9200,
    best_ask_pence:9400, live_bids:641, last_matched_pence:9240,
    spec_line:'4.7L · New & sealed' },
  { slug:'sony-wh1000xm5', name:'Sony WH-1000XM5 Headphones', brand:'Sony',
    category_slug:'audio', rrp_pence:37900, best_bid_pence:31200,
    best_ask_pence:31900, live_bids:530, last_matched_pence:31500,
    spec_line:'Noise cancelling · New & sealed' },
  { slug:'dyson-v11', name:'Dyson V11 Cordless Vacuum', brand:'Dyson',
    category_slug:'vacuums', rrp_pence:42999, best_bid_pence:38500,
    best_ask_pence:39400, live_bids:476, last_matched_pence:38900,
    spec_line:'Cordless · New & boxed' },
  { slug:'samsung-55-q60d', name:'Samsung 55" Q60D QLED 4K TV', brand:'Samsung',
    category_slug:'tvs', rrp_pence:59900, best_bid_pence:54500,
    best_ask_pence:55600, live_bids:288, last_matched_pence:54900,
    spec_line:'55" · QLED 4K · New & boxed' },
  { slug:'sony-ps5-slim-disc', name:'PlayStation 5 Slim (Disc)', brand:'Sony',
    category_slug:'gaming', rrp_pence:47999, best_bid_pence:44900,
    best_ask_pence:46000, live_bids:402, last_matched_pence:45500,
    spec_line:'1TB · Disc edition · New & sealed' }
];
const DEMO_LADDERS = {
  'bosch-series-4-wan28282gb': {
    bids:[{p:47800,c:61},{p:47500,c:44},{p:47000,c:83},{p:46500,c:52},{p:46000,c:72}],
    asks:[{p:48200,u:24},{p:48500,u:18},{p:48900,u:30},{p:49200,u:12},{p:49500,u:20}]
  },
  'ninja-n2-af210uk': {
    bids:[{p:9200,c:118},{p:9000,c:160},{p:8800,c:130},{p:8500,c:145},{p:8400,c:88}],
    asks:[{p:9400,u:43},{p:9500,u:35},{p:9700,u:52},{p:9800,u:26},{p:9900,u:40}]
  },
  'sony-wh1000xm5': {
    bids:[{p:31200,c:97},{p:31000,c:120},{p:30500,c:110},{p:30000,c:126},{p:29000,c:77}],
    asks:[{p:31900,u:26},{p:32500,u:22},{p:33000,u:31},{p:33500,u:15},{p:34000,u:18}]
  },
  'dyson-v11': {
    bids:[{p:38500,c:88},{p:38000,c:104},{p:37500,c:95},{p:37000,c:112},{p:36000,c:77}],
    asks:[{p:39400,u:31},{p:39900,u:24},{p:40500,u:28},{p:41000,u:16},{p:41500,u:22}]
  },
  'samsung-55-q60d': {
    bids:[{p:54500,c:52},{p:54000,c:66},{p:53000,c:71},{p:52000,c:58},{p:50000,c:41}],
    asks:[{p:55600,u:17},{p:56500,u:21},{p:57500,u:14},{p:58500,u:19},{p:59000,u:10}]
  },
  'sony-ps5-slim-disc': {
    bids:[{p:44900,c:74},{p:44000,c:96},{p:43000,c:88},{p:42000,c:81},{p:40000,c:63}],
    asks:[{p:46000,u:12},{p:46500,u:20},{p:47000,u:25},{p:47500,u:15},{p:47900,u:22}]
  }
};

/* ---------- data access ---------- */
async function getCategories(){
  if (DEMO) return DEMO_CATEGORIES;
  const { data, error } = await sb.from('v_category_summary').select('*');
  if (error){ console.error(error); return []; }
  return data;
}

async function getMarkets(opts = {}){
  const { category = null, search = '', limit = 12, offset = 0 } = opts;
  if (DEMO){
    let items = DEMO_MARKETS;
    if (category) items = items.filter(m => m.category_slug === category);
    if (search){
      const s = search.toLowerCase();
      items = items.filter(m =>
        m.name.toLowerCase().includes(s) || (m.brand||'').toLowerCase().includes(s));
    }
    return items.slice(offset, offset + limit);
  }
  let q = sb.from('v_market_summary').select('*')
    .order('live_bids', { ascending: false })
    .range(offset, offset + limit - 1);
  if (category) q = q.eq('category_slug', category);
  if (search) q = q.or(
    `name.ilike.%${search}%,brand.ilike.%${search}%,spec_line.ilike.%${search}%`);
  const { data, error } = await q;
  if (error){ console.error(error); return []; }
  return data;
}

async function getMarket(slug){
  if (DEMO) return DEMO_MARKETS.find(m => m.slug === slug) || DEMO_MARKETS[0];
  const { data } = await sb.from('v_market_summary').select('*').eq('slug', slug).single();
  return data;
}

async function getProductBySlug(slug){
  if (DEMO){
    const m = DEMO_MARKETS.find(x => x.slug === slug) || DEMO_MARKETS[0];
    return { id: 0, slug: m.slug, name: m.name, rrp_pence: m.rrp_pence, spec_line: m.spec_line };
  }
  const { data } = await sb.from('products').select('*').eq('slug', slug).single();
  return data;
}

async function getLadders(slug, productId){
  if (DEMO) return DEMO_LADDERS[slug] || DEMO_LADDERS['bosch-series-4-wan28282gb'];
  const [bids, asks] = await Promise.all([
    sb.from('v_bid_ladder').select('price_pence,bid_count')
      .eq('product_id', productId).order('price_pence', { ascending:false }).limit(5),
    sb.from('v_ask_ladder').select('price_pence,units')
      .eq('product_id', productId).order('price_pence', { ascending:true }).limit(5)
  ]);
  return {
    bids: (bids.data||[]).map(r => ({ p:r.price_pence, c:r.bid_count })),
    asks: (asks.data||[]).map(r => ({ p:r.price_pence, u:r.units }))
  };
}

/* ---------- auth (magic link) ---------- */
async function getUser(){
  if (DEMO) return null;
  const { data } = await sb.auth.getUser();
  return data.user;
}
async function signIn(email){
  if (DEMO) return { error: { message: 'Demo mode — connect Supabase to enable sign-in.' } };
  return sb.auth.signInWithOtp({ email, options: { emailRedirectTo: window.location.href } });
}

/* ---------- actions ---------- */
async function placeBid(productId, pricePence){
  if (DEMO) return { error: { message: 'Demo mode — connect Supabase to enable live bids.' } };
  const user = await getUser();
  if (!user) return { error: { message: 'SIGN_IN' } };
  await sb.from('profiles').upsert({ id: user.id }, { onConflict: 'id' });
  const { error } = await sb.from('bids')
    .insert({ product_id: productId, user_id: user.id, price_pence: pricePence });
  if (error && error.code === '23505')
    return { error: { message: 'You already have a live bid on this product. Cancel it first from My bids.' } };
  return { error };
}

/* ---------- shared UI ---------- */
function initChrome(){
  if (DEMO){
    const b = document.getElementById('demoBanner');
    if (b) b.classList.add('on');
  }
}
