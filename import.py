#!/usr/bin/env python3
"""
OPENBOOK feed importer
----------------------
Pulls affiliate product feeds (AWIN / Webgains style CSV), finds products we
don't have yet (by EAN, fallback slug), appends them to products.csv,
regenerates the site, and upserts categories+products into Supabase.

Feed URLs come from the FEED_URLS env var (comma-separated) or feeds.txt
(one per line, # comments allowed). Supabase upsert requires env vars
SUPABASE_URL and SUPABASE_SERVICE_KEY; without them it skips that step
(the generated seed-generated.sql can be run manually instead).

Usage: python3 import.py [--dry-run] [--max N]
"""
import csv, io, os, re, sys, json, gzip, pathlib, subprocess, urllib.request

ROOT = pathlib.Path(__file__).parent
MAX_NEW = 200
DRY = '--dry-run' in sys.argv
for i, a in enumerate(sys.argv):
    if a == '--max' and i + 1 < len(sys.argv):
        MAX_NEW = int(sys.argv[i + 1])

# ---------- column aliases across feed formats ----------
ALIASES = {
    'name':   ['product_name', 'name', 'title', 'product name'],
    'brand':  ['brand_name', 'brand', 'manufacturer'],
    'ean':    ['ean', 'gtin', 'barcode', 'upc', 'product_gtin'],
    'model':  ['model_number', 'mpn', 'model', 'merchant_product_id', 'product_model'],
    'price':  ['search_price', 'price', 'store_price', 'current_price'],
    'rrp':    ['rrp_price', 'rrp', 'recommended_retail_price', 'base_price', 'high_price'],
    'cat':    ['merchant_category', 'category_name', 'category', 'merchant_product_category_path', 'google_taxonomy'],
    'desc':   ['description', 'product_short_description', 'short_description'],
}

# ---------- feed-category / name keywords -> our category slugs ----------
CAT_RULES = [
    ('washing-machines', 'Washing machines', ['washing machine', 'washer ']),
    ('tumble-dryers',    'Tumble dryers',    ['tumble dryer', 'heat pump dryer', 'condenser dryer']),
    ('dishwashers',      'Dishwashers',      ['dishwasher']),
    ('fridge-freezers',  'Fridge freezers',  ['fridge freezer', 'refrigerator', 'american fridge']),
    ('air-fryers',       'Air fryers',       ['air fryer', 'airfryer', 'dual zone fryer']),
    ('kitchen',          'Kitchen',          ['coffee machine', 'espresso', 'stand mixer', 'blender', 'microwave', 'kettle', 'toaster', 'food processor', 'ice cream maker']),
    ('tvs',              'TVs',              [' tv', 'oled', 'qled', 'television', 'smart tv']),
    ('vacuums',          'Vacuums',          ['vacuum', 'cordless stick', 'robot vac']),
    ('laptops',          'Laptops',          ['laptop', 'macbook', 'notebook', 'chromebook']),
    ('phones',           'Phones',           ['smartphone', 'iphone', 'galaxy s', 'pixel ', 'mobile phone']),
    ('audio',            'Audio',            ['headphone', 'earbud', 'speaker', 'soundbar', 'airpods']),
    ('gaming',           'Gaming',           ['playstation', 'xbox', 'nintendo', 'games console', 'steam deck', 'vr headset']),
]

def slugify(s):
    s = re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')
    return re.sub(r'-{2,}', '-', s)[:80]

def pick(row, key):
    for a in ALIASES[key]:
        for k in row:
            if k and k.strip().lower() == a:
                v = (row[k] or '').strip()
                if v: return v
    return ''

def to_pence(s):
    s = re.sub(r'[^0-9.]', '', s or '')
    if not s: return 0
    try: return round(float(s) * 100)
    except ValueError: return 0

def map_category(cat_text, name):
    hay = (cat_text + ' ' + name).lower()
    for slug, cname, kws in CAT_RULES:
        if any(kw in hay for kw in kws):
            return slug, cname
    return None, None

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'OpenBookImporter/1.0'})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if url.endswith('.gz') or data[:2] == b'\x1f\x8b':
        data = gzip.decompress(data)
    return data.decode('utf-8', errors='replace')

def load_feed_urls():
    urls = [u.strip() for u in os.environ.get('FEED_URLS', '').split(',') if u.strip()]
    f = ROOT / 'feeds.txt'
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                urls.append(line)
    return urls

def main():
    urls = load_feed_urls()
    if not urls:
        print('No feed URLs configured (FEED_URLS env or feeds.txt) — nothing to do.')
        return

    # existing catalogue keys
    existing_eans, existing_slugs = set(), set()
    with open(ROOT / 'products.csv', newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r.get('ean'): existing_eans.add(r['ean'].strip())
            existing_slugs.add(r['slug'])

    new_rows, skipped = [], {'nocat': 0, 'dupe': 0, 'bad': 0}
    for url in urls:
        try:
            text = fetch(url)
        except Exception as e:
            print(f'FEED ERROR {url[:80]}: {e}'); continue
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            if len(new_rows) >= MAX_NEW: break
            name, brand = pick(row, 'name'), pick(row, 'brand')
            ean, model = pick(row, 'ean'), pick(row, 'model')
            rrp = to_pence(pick(row, 'rrp')) or to_pence(pick(row, 'price'))
            if not name or rrp < 2000:            # skip junk & sub-£20 noise
                skipped['bad'] += 1; continue
            cat_slug, cat_name = map_category(pick(row, 'cat'), name)
            if not cat_slug:
                skipped['nocat'] += 1; continue
            if ean and ean in existing_eans:
                skipped['dupe'] += 1; continue
            slug = slugify(f"{brand} {name}" if brand.lower() not in name.lower() else name)
            if not slug or slug in existing_slugs:
                skipped['dupe'] += 1; continue
            desc = re.sub(r'\s+', ' ', pick(row, 'desc'))[:90]
            spec = desc if desc else 'New & boxed'
            new_rows.append({
                'slug': slug, 'name': name[:90], 'model_code': model[:40],
                'brand': brand[:40], 'category_slug': cat_slug,
                'category_name': cat_name, 'rrp_pence': str(rrp),
                'ean': ean, 'spec_line': spec})
            existing_slugs.add(slug)
            if ean: existing_eans.add(ean)

    print(f'feeds: {len(urls)} · new products: {len(new_rows)} · skipped {skipped}')
    if not new_rows or DRY:
        if DRY and new_rows:
            for r in new_rows[:10]: print('  would add:', r['slug'])
        return

    # append to catalogue
    with open(ROOT / 'products.csv', 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['slug','name','model_code','brand',
            'category_slug','category_name','rrp_pence','ean','spec_line'])
        for r in new_rows: w.writerow(r)

    # regenerate the site
    domain = os.environ.get('SITE_DOMAIN', 'https://openbook-pi.vercel.app')
    subprocess.run([sys.executable, str(ROOT / 'generate.py'), 'products.csv',
                    '--domain', domain], check=True)

    # upsert into Supabase (service key required)
    sb_url = os.environ.get('SUPABASE_URL', '').rstrip('/')
    sb_key = os.environ.get('SUPABASE_SERVICE_KEY', '')
    if sb_url and sb_key:
        def rest(path, payload, params=''):
            req = urllib.request.Request(
                f'{sb_url}/rest/v1/{path}{params}',
                data=json.dumps(payload).encode(),
                headers={'apikey': sb_key, 'Authorization': f'Bearer {sb_key}',
                         'Content-Type': 'application/json',
                         'Prefer': 'resolution=merge-duplicates,return=representation'},
                method='POST')
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        cats = {(r['category_slug'], r['category_name']) for r in new_rows}
        rest('categories', [{'slug': s, 'name': n} for s, n in cats],
             '?on_conflict=slug')
        # fetch category ids
        req = urllib.request.Request(f'{sb_url}/rest/v1/categories?select=id,slug',
            headers={'apikey': sb_key, 'Authorization': f'Bearer {sb_key}'})
        with urllib.request.urlopen(req, timeout=60) as r:
            cat_ids = {c['slug']: c['id'] for c in json.loads(r.read().decode())}
        payload = [{'slug': r['slug'], 'name': r['name'],
                    'model_code': r['model_code'], 'brand': r['brand'],
                    'category_id': cat_ids[r['category_slug']],
                    'rrp_pence': int(r['rrp_pence']), 'spec_line': r['spec_line']}
                   for r in new_rows]
        for i in range(0, len(payload), 100):
            rest('products', payload[i:i+100], '?on_conflict=slug')
        print(f'supabase: upserted {len(payload)} products')
    else:
        print('supabase env not set — run seed-generated.sql manually')

if __name__ == '__main__':
    main()
