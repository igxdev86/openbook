#!/usr/bin/env python3
"""
OPENBOOK page generator
-----------------------
Input : products.csv  (columns: slug,name,model_code,brand,category_slug,
                       category_name,rrp_pence,ean,spec_line)
Output: m/<slug>.html   one static SEO page per product
        sitemap.xml, robots.txt
        seed-generated.sql   (upserts categories + products for Supabase)

Run:   python3 generate.py [products.csv] [--domain https://openbook.example]
The generated pages are static shells for Google; the live ladder hydrates
client-side from Supabase via ../config.js.
"""
import csv, sys, html, pathlib, datetime

CSV_PATH = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else 'products.csv'
DOMAIN = 'https://openbook.example'
for i, a in enumerate(sys.argv):
    if a == '--domain' and i + 1 < len(sys.argv):
        DOMAIN = sys.argv[i + 1].rstrip('/')

ROOT = pathlib.Path(__file__).parent
OUT_M = ROOT / 'm'
OUT_M.mkdir(exist_ok=True)

def money(pence):
    p = int(pence)
    return '£{:,.2f}'.format(p / 100).replace('.00', '')

def esc(s): return html.escape(str(s or ''), quote=True)

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
<link rel="stylesheet" href="/styles.css">
<script type="application/ld+json">{jsonld}</script>
</head>
<body>

<div class="topbar">
  <a class="logo" href="/">OPEN<span>BOOK</span></a>
  <a class="top-link" href="/account.html">Sign in · <b>My bids</b></a>
</div>

<div class="demo-banner" id="demoBanner">Demo mode — showing sample data. Add Supabase keys in config.js to go live.</div>

<div class="wrap">

  <div class="crumbs">
    <a href="/">Home</a> / <a href="/markets.html">{category_name}</a> / {brand}</div>

  <div class="card prod-head">
    <div>
      <h1>{name}</h1>
      <div class="prod-spec">{spec_line}</div>
    </div>
    <div class="prod-last">
      <div class="cap">Last matched</div>
      <div class="num big" id="pLast">—</div>
      <div class="num sub" id="pOff">RRP {rrp_disp}</div>
      <div class="num" id="retailLine" style="font-size:.66rem;color:var(--ink-soft);margin-top:2px"></div>
    </div>
  </div>

  <div class="card" style="margin-top:12px;overflow:hidden">
    <div class="book-head">
      <div class="side-label sell">Sellers · Ask</div>
      <div class="mid-label">Spread</div>
      <div class="side-label buy">Buyers · Bid</div>
    </div>
    <div class="book">
      <div class="ladder sell" id="askLadder">
        <div class="rung"><span class="units">Loading the book…</span></div></div>
      <div class="spread">
        <div class="spread-val num" id="spreadVal">—</div>
        <div class="spread-cap">spread</div>
      </div>
      <div class="ladder buy" id="bidLadder">
        <div class="rung"><span class="units">Loading the book…</span></div></div>
    </div>
  </div>

  <div class="card" style="margin-top:12px;padding:14px">
    <div class="section-cap">Place your bid</div>
    <div class="field">
      <label for="bidPrice">Your price (£)</label>
      <input type="number" id="bidPrice" inputmode="decimal" step="0.01" min="1" placeholder="What would you pay?">
    </div>
    <button class="btn btn-buy" style="width:100%;margin-top:12px" id="bidBtn">
      Place bid<small>free to bid · you're only committed if a retailer accepts</small></button>
    <div class="msg" id="bidMsg"></div>
  </div>

  <div class="card content">
    <h2>Name your price on the {name}</h2>
    <p>
      The {name} ({spec_line}) has a recommended retail price of <b class="num">{rrp_disp}</b>.
      On OpenBook you don't pay the shelf price — you bid the price you'd pay today,
      and verified UK retailers accept bids in bulk when the numbers work for them.
      Your bid joins the open order book above alongside every other buyer's.</p>
    <h3>How bidding on the {short_name} works</h3>
    <p>
      Bidding is free and you can only have one live bid on this product.
      If a retailer accepts your bid you get a 30-minute checkout link at your exact
      price — payment and delivery are handled directly by the retailer, never by OpenBook.
      If nobody accepts, your bid simply stays in the book until you cancel it.</p>
    <h3>Product details</h3>
    <table class="spec-table">
      <tr><td>Brand</td><td>{brand}</td></tr>
      <tr><td>Model</td><td class="num">{model_code}</td></tr>
      {ean_row}
      <tr><td>Category</td><td>{category_name}</td></tr>
      <tr><td>RRP</td><td class="num">{rrp_disp}</td></tr>
      <tr><td>Condition</td><td>New — every unit sold by a verified UK retailer</td></tr>
    </table>
  </div>

  <div class="foot">OpenBook · every price is set by the market, not the retailer<br>
    All retailers are verified UK businesses · payment &amp; delivery direct with the retailer</div>
</div>

<div class="overlay" id="authSheet">
  <div class="sheet">
    <div style="font-size:1.1rem;font-weight:700">Sign in to place your bid</div>
    <p style="font-size:.76rem;color:var(--ink-soft);margin-top:6px;line-height:1.5">
      We'll email you a one-tap sign-in link. No passwords.</p>
    <div class="field">
      <label for="authEmail">Email</label>
      <input type="email" id="authEmail" placeholder="you@example.com" autocomplete="email">
    </div>
    <button class="btn btn-dark" style="width:100%;margin-top:12px" id="authBtn">Send sign-in link</button>
    <div class="msg" id="authMsg"></div>
    <button style="display:block;width:100%;margin-top:8px;border:none;background:none;
      color:var(--ink-soft);font-size:.78rem;padding:8px;cursor:pointer;font-family:inherit"
      onclick="document.getElementById('authSheet').classList.remove('open')">Not now</button>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js"></script>
<script src="/config.js"></script>
<script>
initChrome();
const slug = {slug_js};
const RRP = {rrp_pence};
let product = null;

function rungHtml(o, side) {{
  const label = side === 'bid' ? (o.c + ' bid' + (o.c === 1 ? '' : 's'))
                               : (o.u + ' unit' + (o.u === 1 ? '' : 's'));
  return '<div class="rung"><span class="price num">' + P(o.p) +
         '</span><span class="units num">' + label + '</span></div>';
}}

async function load() {{
  product = await getProductBySlug(slug);
  const summary = await getMarket(slug);
  let retail = null;
  try {{
    const rj = await fetch('/data/retail.json').then(r => r.ok ? r.json() : null);
    if (rj && rj[slug]) retail = rj[slug];
  }} catch (e) {{}}
  if (!retail && summary && summary.retail_price_pence)
    retail = {{ price_pence: summary.retail_price_pence, seller: '', url: '' }};
  if (summary && summary.last_matched_pence) {{
    document.getElementById('pLast').textContent = P(summary.last_matched_pence);
    const anchor = (retail && retail.price_pence) || summary.retail_price_pence || RRP;
    const label = (retail || summary.retail_price_pence) ? 'below retail' : 'below RRP';
    document.getElementById('pOff').textContent =
      PCT_OFF(summary.last_matched_pence, anchor) + '% ' + label;
  }}
  if (retail) {{
    const el = document.getElementById('retailLine');
    el.innerHTML = 'Cheapest at retail today: ' + P(retail.price_pence) +
      (retail.seller ? ' at ' + retail.seller : '');
    // retail is the reference now — hide the RRP fallback text
    const off = document.getElementById('pOff');
    if (off.textContent.trim().startsWith('RRP')) off.textContent = '';
  }}
  const l = await getLadders(slug, product ? product.id : 0);
  document.getElementById('bidLadder').innerHTML =
    l.bids.length ? l.bids.map(o => rungHtml(o, 'bid')).join('')
    : '<div class="rung"><span class="units">No bids yet — set the market</span></div>';
  let askHtml = l.asks.map(o => rungHtml(o, 'ask')).join('');
  if (!l.asks.length && retail) {{
    const inner = '<span class="price num">' + P(retail.price_pence) +
      '</span><span class="units">' + (retail.seller || 'retail') + ' →</span>';
    askHtml = retail.url
      ? '<a class="rung" href="' + retail.url + '" target="_blank" rel="noopener nofollow">' + inner + '</a>'
      : '<div class="rung">' + inner + '</div>';
  }} else if (!l.asks.length) {{
    askHtml = '<div class="rung"><span class="units">No asks yet</span></div>';
  }}
  document.getElementById('askLadder').innerHTML = askHtml;
  if (!l.asks.length && retail && l.bids.length)
    document.getElementById('spreadVal').textContent = P(retail.price_pence - l.bids[0].p);
  if (l.bids.length && l.asks.length)
    document.getElementById('spreadVal').textContent = P(l.asks[0].p - l.bids[0].p);
}}

document.getElementById('bidBtn').addEventListener('click', async () => {{
  const msg = document.getElementById('bidMsg'); msg.className = 'msg';
  const v = parseFloat(document.getElementById('bidPrice').value);
  if (!v || v <= 0) {{ msg.textContent = 'Enter a price.'; msg.className = 'msg err'; return; }}
  const pence = Math.round(v * 100);
  if (pence >= RRP) {{
    msg.textContent = 'Your bid is at or above RRP — just buy it from a shop! Bid below ' + P(RRP) + '.';
    msg.className = 'msg err'; return;
  }}
  const r = await placeBid(product ? product.id : 0, pence);
  if (r.error && r.error.message === 'SIGN_IN') {{
    document.getElementById('authSheet').classList.add('open'); return; }}
  if (r.error) {{ msg.textContent = r.error.message; msg.className = 'msg err'; return; }}
  msg.textContent = 'Bid placed at ' + P(pence) + ". You'll be emailed the moment a retailer accepts.";
  msg.className = 'msg ok';
  load();
}});
document.getElementById('authBtn').addEventListener('click', async () => {{
  const email = document.getElementById('authEmail').value.trim();
  const msg = document.getElementById('authMsg'); msg.className = 'msg';
  if (!email) {{ msg.textContent = 'Enter your email.'; msg.className = 'msg err'; return; }}
  const r = await signIn(email);
  if (r.error) {{ msg.textContent = r.error.message; msg.className = 'msg err'; return; }}
  msg.textContent = 'Link sent — check your inbox, then come back and place your bid.';
  msg.className = 'msg ok';
}});
load();
</script>
</body>
</html>
"""

def jsonld(row):
    d = {
        "@context": "https://schema.org", "@type": "Product",
        "name": row['name'],
        "brand": {"@type": "Brand", "name": row['brand']},
        "model": row['model_code'],
        "description": f"Name your price on the {row['name']} ({row['spec_line']}). "
                       f"RRP {money(row['rrp_pence'])}. Verified UK retailers accept bids in bulk on OpenBook.",
        "category": row['category_name'],
        "url": f"{DOMAIN}/m/{row['slug']}"
    }
    if row.get('ean'): d["gtin13"] = row['ean']
    import json
    return json.dumps(d)

def build_page(row):
    rrp_disp = money(row['rrp_pence'])
    short_name = (row['brand'] + ' ' + row['model_code']).strip() or row['name']
    title = f"{row['name']} — Name Your Price (RRP {rrp_disp}) | OpenBook"
    desc = (f"Bid what you'd pay for the {row['name']} ({row['spec_line']}). RRP {rrp_disp}. "
            f"Verified UK retailers accept bids in bulk. Free to bid — you only commit if a retailer accepts.")
    ean_row = (f'<tr><td>EAN</td><td class="num">{esc(row["ean"])}</td></tr>') if row.get('ean') else ''
    return PAGE.format(
        title=esc(title), description=esc(desc),
        canonical=f"{DOMAIN}/m/{row['slug']}",
        jsonld=jsonld(row),
        name=esc(row['name']), short_name=esc(short_name),
        spec_line=esc(row['spec_line']), brand=esc(row['brand']),
        model_code=esc(row['model_code']), ean_row=ean_row,
        category_name=esc(row['category_name']),
        rrp_disp=rrp_disp, rrp_pence=int(row['rrp_pence']),
        slug_js="'" + row['slug'].replace("'", "") + "'"
    )

CAT_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{canonical}">
<link rel="stylesheet" href="/styles.css">
<script type="application/ld+json">{jsonld}</script>
</head>
<body>

<div class="topbar">
  <a class="logo" href="/">OPEN<span>BOOK</span></a>
  <a class="top-link" href="/account.html"><b>My bids</b></a>
</div>

<div class="wrap">

  <div class="crumbs"><a href="/">Home</a> / <a href="/markets.html">All markets</a> / {cat_name}</div>

  {catnav}

  <div style="padding:14px 4px 2px">
    <h1 style="font-size:1.25rem;font-weight:800;letter-spacing:-.01em">{cat_name}: name your price</h1>
    <p style="font-size:.78rem;color:var(--ink-soft);margin-top:6px;line-height:1.55">
      {intro}</p>
  </div>

  <div class="markets" style="margin-top:8px">
    <div class="m-legend">
      <div>Product</div><div class="bid-l">Best bid</div><div class="ask-l">Best ask</div>
    </div>
    {rows}
  </div>

  <div class="card content">
    <h2>How bidding on {cat_name_lc} works on OpenBook</h2>
    <p>Every product above has an open market. Pick the exact model you want, bid the
      price you'd pay today, and your bid joins the public order book. Verified UK
      retailers watch the demand on their stock and accept bids in bulk when the price
      works — if yours is accepted you get a 30-minute checkout link at your exact
      price, paid directly to the retailer. Bidding is free and you can cancel any time.</p>
  </div>

  <div class="foot">OpenBook · every price is set by the market, not the retailer</div>
</div>

<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js"></script>
<script src="/config.js"></script>
<script>
initChrome();
(async () => {{
  const items = await getMarkets({{ category: '{cat_slug}', limit: 200 }});
  items.forEach(m => {{
    const row = document.getElementById('r-' + m.slug);
    if (!row) return;
    const meta = row.querySelector('.m-meta');
    const anchor = m.retail_price_pence || m.rrp_pence;
    if (m.last_matched_pence)
      meta.innerHTML = 'Last ' + P(m.last_matched_pence) + ' · <span class="off">' +
        PCT_OFF(m.last_matched_pence, anchor) + '% off</span> · ' + (m.live_bids||0) + ' bids';
    else if (m.retail_price_pence)
      meta.innerHTML = 'Retail ' + P(m.retail_price_pence) + ' · ' + (m.live_bids||0) + ' bids';
    else
      meta.innerHTML = 'RRP <span class="rrp">' + P(m.rrp_pence) + '</span> · ' + (m.live_bids||0) + ' bids';
    const cells = row.querySelectorAll('.cell');
    if (m.best_bid_pence) cells[0].outerHTML =
      '<div class="cell bid"><b class="num">' + P(m.best_bid_pence) + '</b><span>best bid</span></div>';
    if (m.best_ask_pence) cells[1].outerHTML =
      '<div class="cell ask"><b class="num">' + P(m.best_ask_pence) + '</b><span>best ask</span></div>';
    else if (m.retail_price_pence) cells[1].outerHTML =
      '<div class="cell ask"><b class="num">' + P(m.retail_price_pence) + '</b><span>retail</span></div>';
  }});
}})();
</script>
</body>
</html>
"""

def catnav_html(cats, active=None):
    links = ['<a href="/markets.html"%s>All</a>' % (' class="active"' if active is None else '')]
    for c in cats:
        cls = ' class="active"' if active == c['slug'] else ''
        links.append('<a href="/c/%s"%s>%s</a>' % (c['slug'], cls, esc(c['name'])))
    return '<nav class="catnav" aria-label="Categories">' + ''.join(links) + '</nav>'

def cat_row(r):
    return ('<a class="mrow" id="r-%s" href="/m/%s">'
            '<div><div class="m-name">%s</div>'
            '<div class="m-meta num">%s · RRP <span class="rrp">%s</span></div></div>'
            '<div class="cell empty"><b>—</b><span>no bids</span></div>'
            '<div class="cell empty"><b>—</b><span>no asks</span></div></a>'
            ) % (esc(r['slug']), esc(r['slug']), esc(r['name']),
                 esc(r['brand']), money(r['rrp_pence']))

def build_category(cat, rows_in_cat, cats):
    import json
    name = cat['name']
    brands = sorted({r['brand'] for r in rows_in_cat if r['brand']})
    lo = min(int(r['rrp_pence']) for r in rows_in_cat)
    hi = max(int(r['rrp_pence']) for r in rows_in_cat)
    title = f"{name} — Name Your Price on {len(rows_in_cat)} Models | OpenBook"
    desc = (f"Bid what you'd pay on {len(rows_in_cat)} {name.lower()} from "
            f"{', '.join(brands[:4])}{' and more' if len(brands)>4 else ''}. "
            f"RRPs {money(lo)}–{money(hi)}. Verified UK retailers accept bids in bulk. Free to bid.")
    intro = (f"{len(rows_in_cat)} live {name.lower()} markets from "
             f"{', '.join(brands[:5])}{' and more' if len(brands)>5 else ''}. "
             f"Recommended retail prices run from {money(lo)} to {money(hi)} — "
             f"the price you bid is up to you.")
    jsonld = json.dumps({
        "@context":"https://schema.org","@type":"ItemList","name":title,
        "itemListElement":[{"@type":"ListItem","position":i+1,
            "url":f"{DOMAIN}/m/{r['slug']}","name":r['name']}
            for i,r in enumerate(rows_in_cat)]})
    return CAT_PAGE.format(
        title=esc(title), description=esc(desc),
        canonical=f"{DOMAIN}/c/{cat['slug']}", jsonld=jsonld,
        cat_name=esc(name), cat_name_lc=esc(name.lower()),
        cat_slug=cat['slug'], intro=esc(intro),
        catnav=catnav_html(cats, active=cat['slug']),
        rows='\n    '.join(cat_row(r) for r in rows_in_cat))

def inject_catnav(path, nav):
    f = pathlib.Path(path)
    if not f.exists(): return
    t = f.read_text()
    start, end = '<!--CATNAV-->', '<!--/CATNAV-->'
    if start not in t: return
    pre = t.split(start)[0]
    post = t.split(end)[1]
    f.write_text(pre + start + '\n' + nav + '\n' + end + post)

def main():
    rows = []
    with open(ROOT / CSV_PATH, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            row = {k: (v or '').strip() for k, v in row.items()}
            if row.get('slug') and row.get('name') and row.get('rrp_pence'):
                rows.append(row)

    # categories in CSV order
    cats, seen = [], set()
    for r in rows:
        if r['category_slug'] not in seen:
            seen.add(r['category_slug'])
            cats.append({'slug': r['category_slug'], 'name': r['category_name']})
    nav_all = catnav_html(cats)

    # product pages (with catnav injected under the crumbs)
    for row in rows:
        page = build_page(row)
        page = page.replace('</div>\n\n  <div class="card prod-head">',
                            '</div>\n\n  ' + catnav_html(cats, active=row['category_slug']) +
                            '\n\n  <div class="card prod-head">', 1)
        (OUT_M / f"{row['slug']}.html").write_text(page, encoding='utf-8')

    # category pages
    OUT_C = ROOT / 'c'; OUT_C.mkdir(exist_ok=True)
    for cat in cats:
        in_cat = [r for r in rows if r['category_slug'] == cat['slug']]
        (OUT_C / f"{cat['slug']}.html").write_text(
            build_category(cat, in_cat, cats), encoding='utf-8')

    # inject nav into hand-written pages between markers
    inject_catnav(ROOT / 'index.html', nav_all)
    inject_catnav(ROOT / 'markets.html', nav_all)

    today = datetime.date.today().isoformat()
    urls = [f"{DOMAIN}/", f"{DOMAIN}/markets"] \
         + [f"{DOMAIN}/c/{c['slug']}" for c in cats] \
         + [f"{DOMAIN}/m/{r['slug']}" for r in rows]
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sitemap.append(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod></url>")
    sitemap.append('</urlset>')
    (ROOT / 'sitemap.xml').write_text('\n'.join(sitemap), encoding='utf-8')
    (ROOT / 'robots.txt').write_text(
        f"User-agent: *\nAllow: /\nSitemap: {DOMAIN}/sitemap.xml\n", encoding='utf-8')

    # Supabase seed for the same rows
    sql = ["-- generated by generate.py — categories & products upsert",
           "insert into categories(slug,name) values"]
    sql.append(',\n'.join(
        f" ('{c['slug']}','{c['name'].replace(chr(39), chr(39)*2)}')" for c in cats))
    sql.append("on conflict (slug) do nothing;")
    sql.append("\nwith c as (select slug,id from categories)")
    sql.append("insert into products(slug,name,model_code,brand,category_id,rrp_pence,spec_line)")
    sql.append("select v.slug,v.name,v.model,v.brand,(select id from c where c.slug=v.cat),v.rrp,v.spec from (values")
    q = lambda s: s.replace("'", "''")
    sql.append(',\n'.join(
        f" ('{q(r['slug'])}','{q(r['name'])}','{q(r['model_code'])}','{q(r['brand'])}',"
        f"'{q(r['category_slug'])}',{int(r['rrp_pence'])},'{q(r['spec_line'])}')" for r in rows))
    sql.append(") as v(slug,name,model,brand,cat,rrp,spec)")
    sql.append("on conflict (slug) do nothing;")
    (ROOT / 'seed-generated.sql').write_text('\n'.join(sql), encoding='utf-8')

    print(f"generated {len(rows)} product pages, {len(cats)} category pages, "
          f"sitemap ({len(urls)} urls), seed SQL")

if __name__ == '__main__':
    main()
