"""Read allowlisted service snapshots into local queue, then retry MLflow sync."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
import tracker

METRICS={'pipeline_total_sec','python_pipeline_sec','before_pipeline_sec','stl_count','landmarks_generated'}
TAGS={'source','execution_env','job_type','model_name','endpoint','seg_type','timing_scope','outcome'}

def ingest(folder):
    folder.mkdir(parents=True,exist_ok=True)
    for p in folder.glob('*.json'):
        try:
            raw=p.read_bytes(); d=json.loads(raw)
            if not re.fullmatch('[0-9a-f]{32}',d.get('id','')) or p.stem!=d['id']:
                raise ValueError('invalid id')
            if d.get('status') not in ('RUNNING','FINISHED','FAILED'): raise ValueError('status')
            if set(d.get('tags',{}))-TAGS: raise ValueError('unapproved tags')
            if set(d.get('metrics',{}))-METRICS: raise ValueError('unapproved metrics')
            if d.get('project')!='service-auto-seg': raise ValueError('project')
            clean={k:d[k] for k in ('id','project','name','start','status','tags')}
            clean['metrics']=tracker.valid_metrics(d['metrics'])
            if 'end' in d: clean['end']=int(d['end'])
            digest=hashlib.sha256(raw).hexdigest()
            with tracker.connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS service_ingest(id TEXT PRIMARY KEY, digest TEXT NOT NULL)')
                old=db.execute('SELECT digest FROM service_ingest WHERE id=?',(d['id'],)).fetchone()
                if old and old[0]==digest: continue
                previous=db.execute('SELECT body FROM jobs WHERE id=?',(d['id'],)).fetchone()
                if previous and json.loads(previous[0])['status']!='RUNNING' and d['status']=='RUNNING': continue
                body=json.dumps(clean,allow_nan=False)
                db.execute('INSERT INTO jobs(id,body,revision) VALUES(?,?,1) ON CONFLICT(id) DO UPDATE SET body=excluded.body,revision=jobs.revision+1',(d['id'],body))
                db.execute('INSERT INTO service_ingest VALUES(?,?) ON CONFLICT(id) DO UPDATE SET digest=excluded.digest',(d['id'],digest))
            print('Queued:',d['id'],d['status'],flush=True)
        except Exception:
            print('Snapshot could not be read/validated; retry next cycle.',flush=True)

def main():
    p=argparse.ArgumentParser(); p.add_argument('--once',action='store_true'); p.add_argument('--uri',default='http://127.0.0.1:5000'); args=p.parse_args()
    tracker.HOME=Path(os.environ.get('SERVICE_TRACKER_STATE',str(Path.home()/'.service-tracker-state')))
    tracker.HOME.mkdir(parents=True,exist_ok=True)
    cfg=tracker.HOME/'config.json'
    if not cfg.exists(): cfg.write_text(json.dumps({'env':'service','uri':args.uri}),encoding='utf-8')
    elif json.loads(cfg.read_text())['uri']!=args.uri: raise SystemExit('Existing state uses a different URI; do not reuse it for another server.')
    folder=Path(os.environ.get('SERVICE_TRACKER_OUTBOX',str(Path.home()/'.service-tracker-outbox')))
    print('Service worker started. Keep MLflow and sync_notion.py running.',flush=True)
    while True:
        ingest(folder)
        try: tracker.sync_once()
        except Exception as e: print('MLflow unavailable; local queue retained:',type(e).__name__,flush=True)
        if args.once: break
        time.sleep(15)
if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: pass
