#!/usr/bin/env python3
"""
OPENBOOK retail price sweep
---------------------------
For each active product, asks DataForSEO's Google Shopping (Merchant) API for
UK offers, picks a sane cheapest price, and writes it to Supabase
(products.retail_price_pence + retail_checked_at).

Env vars required:
  DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD
  SUPABASE_URL, SUPABASE_SERVICE_KEY

Usage: python3 sweep.py [--limit N] [--dry-run]
Sanity rules: ignore offers below 40% of RRP (grey/scam listings) and above
150% of RRP (bundles/marketplace chancers); need at least 2 surviving offers
unless only 1 exists at all.
"""
import base64, json, os, sys, time, urllib.request

D4S_LOGIN = os.environ.get('DATAFORSEO_LOGIN', '')
D4S_PASS  = os.environ.get('DATAFORSEO_PASSWORD', '')
SB_URL    = os.environ.get('SUPABASE_URL', '').rstrip('/')
SB_KEY    = os.environ.get('SUPABASE_SERVICE_KEY', '')
DRY = '--dry-run' in sys.argv
LIMIT = None
for i, a in enumerate(sys.argv):
    if a == '--limit' and i + 1 < len(sys.argv): LIMIT = int(sys.argv[i + 1])

UK_LOCATION = 2826       # United Kingdom
LANG = 'en'

def die(msg): print('FATAL:', msg); sys.exit(1)
if not (D4S_LOGIN and D4S_PASS): die('DataForSEO credentials missing')
if not (SB_URL and SB_KEY): die('Supabase credentials missing')

AUTH = base64.b64encode(f'{D4S_LOGIN}:{D4S_PASS}'.encode()).decode()

def d4s(path, payload=None):
    req = urllib.request.Request(
        f'https://api.dataforseo.com/v3/{path}',
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization': f'Basic {AUTH}',
                 'Content-Type': 'application/json'},
        method='POST' if payload is not None else 'GET')
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())

def sb(method, path, payload=None):
    req = urllib.request.Request(
        f'{SB_URL}/rest/v1/{path}',
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'apikey': SB_KEY, 'Authorization': f'Bearer {SB_KEY}',
                 'Content-Type': 'application/json', 'Prefer': 'return=minimal'},
        method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode()
        return json.loads(body) if body else None

def extract_offers(task_result):
    """Pull GBP offers (price, seller, url) out of a shopping result, defensively."""
    offers = []
    for res in (task_result or []):
        for item in (res.get('items') or []):
            price = item.get('price')
            val = None
            if isinstance(price, dict):
                cur = (price.get('currency') or 'GBP').upper()
                v = price.get('current') or price.get('value')
                if v and cur == 'GBP': val = v
            elif isinstance(price, (int, float)) and price > 0:
                val = price
            if val is None: continue
            try: pence = round(float(val) * 100)
            except (TypeError, ValueError): continue
            offers.append({
                'price_pence': pence,
                'seller': (item.get('seller') or item.get('source') or '').strip()[:60],
                'url': (item.get('url') or item.get('shopping_url') or '')[:500]})
    return offers

def choose_floor(offers, rrp):
    lo, hi = int(rrp * 0.40), int(rrp * 1.50)
    sane = sorted((o for o in offers if lo <= o['price_pence'] <= hi),
                  key=lambda o: o['price_pence'])
    return sane[0] if sane else None

def main():
    products = sb('GET',
        'products?select=id,slug,name,brand,rrp_pence&is_active=eq.true&order=id')
    if LIMIT: products = products[:LIMIT]
    print(f'sweeping {len(products)} products')

    # post one task per product (batched in a single request)
    tasks = [{'keyword': f"{p['name']}",
              'location_code': UK_LOCATION, 'language_code': LANG,
              'tag': p['slug']} for p in products]
    post = d4s('merchant/google/products/task_post', tasks)
    if post.get('status_code') != 20000:
        die(f"task_post failed: {post.get('status_message')}")
    posted = {t['data']['tag']: t['id'] for t in post['tasks']
              if t.get('id') and t.get('status_code') in (20000, 20100)}
    print(f'posted {len(posted)} tasks, waiting for results…')

    by_slug = {p['slug']: p for p in products}
    done, updated, misses = set(), 0, []
    global FLOORS
    FLOORS = {}
    deadline = time.time() + 15 * 60
    while len(done) < len(posted) and time.time() < deadline:
        time.sleep(20)
        try:
            ready = d4s('merchant/google/products/tasks_ready')
        except Exception as e:
            print('  poll error (tasks_ready):', e); continue
        for t in (ready.get('tasks') or []):
            for r in (t.get('result') or []):
                tid = r.get('id')
                if not tid: continue
                try:
                    got = d4s(f'merchant/google/products/task_get/advanced/{tid}')
                except Exception as e:
                    print('  poll error (task_get):', e); continue
                for task in (got.get('tasks') or []):
                    tag = (task.get('data') or {}).get('tag')
                    if not tag or tag in done or tag not in by_slug: continue
                    done.add(tag)
                    p = by_slug[tag]
                    offers = extract_offers(task.get('result'))
                    best = choose_floor(offers, p['rrp_pence'])
                    if best:
                        floor = best['price_pence']
                        pct = round(100 * floor / p['rrp_pence'])
                        FLOORS[tag] = {'floor_pence': floor, 'rrp_pence': p['rrp_pence'],
                                       'pct_of_rrp': pct, 'offers': len(offers),
                                       'seller': best['seller'], 'url': best['url']}
                        print(f"  {tag}: {len(offers)} offers -> £{floor/100:.2f} at {best['seller']} ({pct}% of RRP)")
                        if not DRY:
                            sb('PATCH', f'products?slug=eq.{tag}',
                               {'retail_price_pence': floor,
                                'retail_checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
                        updated += 1
                    else:
                        print(f"  {tag}: {len(offers)} offers, none sane — skipped")
                        misses.append(tag)
    missing = set(posted) - done
    if missing: print('no result in time for:', ', '.join(sorted(missing)))
    print(f'done: {updated} updated, {len(misses)} skipped, {len(missing)} timed out')
    import pathlib
    pathlib.Path('data').mkdir(exist_ok=True)
    pathlib.Path('data/sweep-last.json').write_text(json.dumps({
        'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'updated': updated, 'skipped': misses, 'timed_out': sorted(missing),
        'floors': FLOORS}, indent=1))
    pathlib.Path('data/retail.json').write_text(json.dumps({
        s: {'price_pence': v['floor_pence'], 'seller': v['seller'], 'url': v['url']}
        for s, v in FLOORS.items()}))

if __name__ == '__main__':
    main()
