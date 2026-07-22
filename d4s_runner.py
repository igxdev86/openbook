#!/usr/bin/env python3
"""
OPENBOOK DataForSEO runner
--------------------------
Processes every JSON file in tasks/pending/, calls the matching DataForSEO
live endpoint, writes results to data/<task-id>.json, moves the task file
to tasks/done/. Designed to run in GitHub Actions on push.

Task file format (one JSON object):
  { "id": "phones-volumes-001",
    "type": "search_volume" | "serp" | "keyword_suggestions" | "ranked_keywords",
    "params": { ... } }

Types:
  search_volume       params: {"keywords": [...]}                    (max 1000)
  serp                params: {"keyword": "..."}                     (top 100 UK results)
  keyword_suggestions params: {"keyword": "...", "limit": 100}
  ranked_keywords     params: {"target": "domain.com", "limit": 100}
"""
import base64, json, os, sys, pathlib, urllib.request

ROOT = pathlib.Path(__file__).parent
PENDING = ROOT / 'tasks' / 'pending'
DONE = ROOT / 'tasks' / 'done'
DATA = ROOT / 'data'
for d in (PENDING, DONE, DATA): d.mkdir(parents=True, exist_ok=True)

LOGIN = os.environ.get('DATAFORSEO_LOGIN', '')
PASS  = os.environ.get('DATAFORSEO_PASSWORD', '')
if not (LOGIN and PASS):
    print('FATAL: DataForSEO credentials missing'); sys.exit(1)
AUTH = base64.b64encode(f'{LOGIN}:{PASS}'.encode()).decode()

UK, LANG = 2826, 'en'

def d4s(path, payload):
    req = urllib.request.Request(
        f'https://api.dataforseo.com/v3/{path}',
        data=json.dumps(payload).encode(),
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())

def run_task(task):
    t, p = task['type'], task.get('params', {})
    if t == 'search_volume':
        return d4s('keywords_data/google_ads/search_volume/live',
            [{'keywords': p['keywords'][:1000],
              'location_code': UK, 'language_code': LANG}])
    if t == 'serp':
        return d4s('serp/google/organic/live/advanced',
            [{'keyword': p['keyword'], 'location_code': UK,
              'language_code': LANG, 'depth': p.get('depth', 100)}])
    if t == 'keyword_suggestions':
        return d4s('dataforseo_labs/google/keyword_suggestions/live',
            [{'keyword': p['keyword'], 'location_code': UK,
              'language_code': LANG, 'limit': p.get('limit', 100),
              'include_seed_keyword': True}])
    if t == 'ranked_keywords':
        return d4s('dataforseo_labs/google/ranked_keywords/live',
            [{'target': p['target'], 'location_code': UK,
              'language_code': LANG, 'limit': p.get('limit', 100)}])
    raise ValueError(f'unknown task type: {t}')

def main():
    files = sorted(PENDING.glob('*.json'))
    if not files:
        print('no pending tasks'); return
    for f in files:
        task = json.loads(f.read_text())
        tid = task.get('id', f.stem)
        print(f'running {tid} ({task["type"]})…')
        try:
            result = run_task(task)
            status = result.get('status_code')
            cost = result.get('cost')
            (DATA / f'{tid}.json').write_text(json.dumps(result, indent=1))
            print(f'  -> data/{tid}.json (status {status}, cost ${cost})')
        except Exception as e:
            (DATA / f'{tid}.error.txt').write_text(str(e))
            print(f'  -> ERROR: {e}')
        f.rename(DONE / f.name)

if __name__ == '__main__':
    main()
