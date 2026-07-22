#!/usr/bin/env python3
"""Sync products.csv -> Supabase (upsert categories + products on slug).
merge-duplicates means RRP/spec edits in the CSV also update existing rows."""
import csv, json, os, sys, time, pathlib, urllib.request

SB_URL = os.environ.get('SUPABASE_URL','').rstrip('/')
SB_KEY = os.environ.get('SUPABASE_SERVICE_KEY','')
if not (SB_URL and SB_KEY):
    print('FATAL: Supabase credentials missing'); sys.exit(1)

def rest(method, path, payload=None, prefer='return=minimal'):
    req = urllib.request.Request(f'{SB_URL}/rest/v1/{path}',
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'apikey': SB_KEY, 'Authorization': f'Bearer {SB_KEY}',
                 'Content-Type': 'application/json', 'Prefer': prefer},
        method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read().decode()
        return json.loads(b) if b else None

rows = list(csv.DictReader(open('products.csv')))
cats = {}
for r in rows: cats[r['category_slug']] = r['category_name']

rest('POST', 'categories?on_conflict=slug',
     [{'slug': s, 'name': n} for s, n in cats.items()],
     'resolution=merge-duplicates,return=minimal')
cat_ids = {c['slug']: c['id'] for c in rest('GET', 'categories?select=id,slug')}

payload = [{'slug': r['slug'], 'name': r['name'], 'model_code': r['model_code'],
            'brand': r['brand'], 'category_id': cat_ids[r['category_slug']],
            'rrp_pence': int(r['rrp_pence']), 'spec_line': r['spec_line'],
            'is_active': True} for r in rows]
for i in range(0, len(payload), 100):
    rest('POST', 'products?on_conflict=slug', payload[i:i+100],
         'resolution=merge-duplicates,return=minimal')

count = rest('GET', 'products?select=id&is_active=eq.true')
receipt = {'synced': len(payload), 'db_active_products': len(count),
           'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
pathlib.Path('data').mkdir(exist_ok=True)
pathlib.Path('data/db-sync-last.json').write_text(json.dumps(receipt))
print('synced', receipt)
