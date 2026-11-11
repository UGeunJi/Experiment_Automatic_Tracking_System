"""Central MLflow -> Notion summary sync; Python standard library only.

Notion API pinned to 2025-09-03. Run one worker per target data source.
Only terminal runs are published. This is a standalone public implementation,
not an in-place patch of an existing private sync_notion.py.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.request
import uuid

import tracker

SCHEMA = {
    'Name': 'title', 'Project': 'rich_text', 'Source': 'rich_text',
    'Env': 'select', 'Job': 'select', 'Model': 'rich_text', 'Started': 'date',
    'Status': 'select', 'Dice': 'number', 'Inference_s': 'number',
    'RunID': 'rich_text', 'MLflow': 'url', 'Pipeline_s': 'number', 'Total_s': 'number',
}
TERMINAL = {'FINISHED', 'FAILED', 'KILLED'}


def load_env(path):
    """Simple KEY=VALUE loader, no shell expansion; existing environment wins."""
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            key, sep, value = line.partition('=')
            if not sep:
                raise ValueError('Expected KEY=VALUE in env file')
            os.environ.setdefault(key.strip(), value.strip().strip('\"').strip("'"))


def notion_id(value):
    # Reject URLs to avoid accidentally selecting a view ID instead of a database.
    return str(uuid.UUID(value.strip()))


class Notion:
    def __init__(self, token):
        self.token = token
        self.last = 0.0

    def call(self, method, path, body=None):
        # Conservative pacing. On ambiguous writes retry by querying RunID next cycle.
        time.sleep(max(0, .4 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        request = urllib.request.Request(
            'https://api.notion.com/v1/' + path, method=method,
            data=None if body is None else json.dumps(body, allow_nan=False).encode(),
            headers={'Authorization': 'Bearer ' + self.token,
                     'Notion-Version': '2025-09-03', 'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 429:
                try:
                    delay = max(1, min(300, float(error.headers.get('Retry-After', '5'))))
                except ValueError:
                    delay = 5
                time.sleep(delay)
            # Do not print response bodies, tokens or page content.
            raise RuntimeError('Notion HTTP ' + str(error.code)) from None

    def resolve(self):
        direct = os.getenv('NOTION_DATA_SOURCE_ID', '').strip()
        if direct:
            return notion_id(direct)
        database = notion_id(os.environ['NOTION_DATABASE_ID'])
        sources = self.call('GET', 'databases/' + database).get('data_sources', [])
        if len(sources) != 1:
            raise ValueError('Database must have one data source; otherwise set NOTION_DATA_SOURCE_ID')
        return sources[0]['id']

    def validate(self, source):
        props = self.call('GET', 'data_sources/' + source)['properties']
        invalid = [name + ':' + kind for name, kind in SCHEMA.items()
                   if props.get(name, {}).get('type') != kind]
        if invalid:
            raise ValueError('Missing or incorrect Notion columns: ' + ', '.join(invalid))

    def upsert(self, source, run_id, props):
        found = self.call('POST', 'data_sources/' + source + '/query', {
            'filter': {'property': 'RunID', 'rich_text': {'equals': run_id}}, 'page_size': 2,
        })
        pages = found.get('results', [])
        if len(pages) > 1 or found.get('has_more'):
            raise ValueError('Duplicate RunID in Notion; resolve manually')
        if pages:
            self.call('PATCH', 'pages/' + pages[0]['id'], {'properties': props})
        else:
            self.call('POST', 'pages', {
                'parent': {'type': 'data_source_id', 'data_source_id': source},
                'properties': props,
            })


def text_prop(value, kind='rich_text'):
    return {kind: [{'text': {'content': str(value)[:1900]}}]}


def select_prop(value):
    return {'select': {'name': str(value)[:100] or 'unknown'}}


def number_prop(value):
    valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return {'number': float(value) if valid else None}


def properties(run, project, public_url):
    info = run['info']
    tags = {x['key']: x['value'] for x in run.get('data', {}).get('tags', [])}
    metrics = {x['key']: x['value'] for x in run.get('data', {}).get('metrics', [])}
    started = datetime.fromtimestamp(info['start_time'] / 1000, timezone.utc).isoformat()
    return {
        'Name': text_prop(tags.get('mlflow.runName', info['run_id']), 'title'),
        'Project': text_prop(project), 'Source': text_prop(tags.get('source', 'unknown')),
        'Env': select_prop(tags.get('execution_env', 'unknown')),
        'Job': select_prop(tags.get('job_type', 'unknown')),
        'Model': text_prop(tags.get('model_name', 'unknown')),
        'Started': {'date': {'start': started}}, 'Status': select_prop(info['status']),
        'Dice': number_prop(metrics.get('dice_mean')),
        'Inference_s': number_prop(metrics.get('model_inference_mean_sec')),
        'Pipeline_s': number_prop(metrics.get('python_pipeline_sec')),
        'Total_s': number_prop(metrics.get('pipeline_total_sec')),
        'RunID': text_prop(info['run_id']),
        'MLflow': {'url': public_url.rstrip('/') + '/#/experiments/' + info['experiment_id'] + '/runs/' + info['run_id']},
    }


def paged(api, endpoint, payload, key):
    payload = dict(payload)
    while True:
        response = api.call(endpoint, payload)
        yield from response.get(key, [])
        token = response.get('next_page_token')
        if not token:
            break
        payload['page_token'] = token


def cycle(api, notion, source, state, public_url):
    for experiment in paged(api, 'experiments/search', {'max_results': 100}, 'experiments'):
        for run in paged(api, 'runs/search', {'experiment_ids': [experiment['experiment_id']], 'max_results': 1000}, 'runs'):
            if run['info']['status'] not in TERMINAL:
                continue
            rid = run['info']['run_id']
            props = properties(run, experiment['name'], public_url)
            digest = hashlib.sha256(json.dumps(props, sort_keys=True).encode()).hexdigest()
            # Include source and tracking URI so caches for different hubs never collide.
            key = api.uri + '|' + source + '|' + rid
            previous = state.execute('SELECT digest FROM synced WHERE key=?', (key,)).fetchone()
            if previous and previous[0] == digest:
                continue
            try:
                notion.upsert(source, rid, props)
                with state:
                    state.execute('INSERT INTO synced VALUES(?,?) ON CONFLICT(key) DO UPDATE SET digest=excluded.digest', (key, digest))
                print('Notion synced:', rid, run['info']['status'], flush=True)
            except Exception as error:
                # Preserve unsynced state; next cycle queries RunID before writing again.
                print('Notion pending:', rid, type(error).__name__, flush=True)
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', default=str(Path(__file__).with_name('.env')))
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--check', action='store_true', help='Validate Notion schema without writing rows')
    args = parser.parse_args()
    if Path(args.env_file).exists():
        load_env(args.env_file)
    uri = os.getenv('MLFLOW_TRACKING_URI', 'http://127.0.0.1:5000')
    public = os.getenv('MLFLOW_PUBLIC_URL', uri)
    interval = max(5, int(os.getenv('SYNC_INTERVAL_SECONDS', '30')))
    state_dir = Path(os.getenv('NOTION_SYNC_STATE', str(Path.home() / '.experiment-notion-sync')))
    state_dir.mkdir(parents=True, exist_ok=True)
    tracker.HOME = state_dir  # reuse the cross-platform process lock, not tracker queue
    with tracker.sync_lock() as acquired:
        if not acquired:
            raise SystemExit('Another Notion worker is using this state directory')
        notion = Notion(os.environ['NOTION_TOKEN'])
        source = notion.resolve()
        notion.validate(source)
        print('Notion schema OK. Terminal runs only.', flush=True)
        if args.check:
            return
        with sqlite3.connect(str(state_dir / 'synced.sqlite3')) as state:
            state.execute('CREATE TABLE IF NOT EXISTS synced(key TEXT PRIMARY KEY, digest TEXT NOT NULL)')
            while True:
                try:
                    cycle(tracker.API(uri), notion, source, state, public)
                except Exception as error:
                    print('Sync paused; will retry:', type(error).__name__, str(error)[:200], flush=True)
                    if args.once:
                        raise SystemExit(1)
                if args.once:
                    break
                time.sleep(interval)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
