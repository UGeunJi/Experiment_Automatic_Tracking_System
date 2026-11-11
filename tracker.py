"""Local-first experiment tracking. Python 3.9+, standard library only."""
import argparse
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HOME = Path(os.environ.get('EXPERIMENT_TRACKER_HOME', str(Path.home() / '.experiment-tracker')))

def now():
    return int(time.time() * 1000)

def connect():
    HOME.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(HOME / 'queue.sqlite3'), timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL, revision INTEGER NOT NULL, sent INTEGER NOT NULL DEFAULT 0, remote TEXT)')
    return db

def config():
    p = HOME / 'config.json'
    if not p.exists():
        raise RuntimeError('Run init first in this OS/user account.')
    return json.loads(p.read_text(encoding='utf-8'))

def save(doc):
    with connect() as db:
        db.execute('INSERT INTO jobs(id,body,revision) VALUES(?,?,1) ON CONFLICT(id) DO UPDATE SET body=excluded.body, revision=jobs.revision+1', (doc['id'], json.dumps(doc, allow_nan=False)))

def valid_metrics(values):
    return {str(k): float(v) for k, v in values.items() if not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)}

@contextlib.contextmanager
def sync_lock():
    HOME.mkdir(parents=True, exist_ok=True)
    f = open(HOME / 'sync.lock', 'a+b')
    try:
        f.seek(0)
        if os.name == 'nt':
            import msvcrt
            if not f.read(1):
                f.write(b'0'); f.flush()
            f.seek(0)
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                yield False; return
        else:
            import fcntl
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False; return
        yield True
    finally:
        f.close()

class API:
    def __init__(self, uri):
        self.uri = uri.rstrip('/')
    def call(self, path, payload=None, query=None):
        url = self.uri + '/api/2.0/mlflow/' + path
        if query:
            url += '?' + urllib.parse.urlencode(query)
        req = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as res:
            return json.load(res)
    def experiment(self, name):
        try:
            return self.call('experiments/get-by-name', query={'experiment_name': name})['experiment']['experiment_id']
        except urllib.error.HTTPError as error:
            body = json.loads(error.read())
            if body.get('error_code') != 'RESOURCE_DOES_NOT_EXIST':
                raise RuntimeError(str(body))
        try:
            return self.call('experiments/create', {'name': name})['experiment_id']
        except urllib.error.HTTPError:
            return self.call('experiments/get-by-name', query={'experiment_name': name})['experiment']['experiment_id']

def sync_once():
    with sync_lock() as acquired:
        if not acquired:
            return
        api = API(config()['uri'])
        with connect() as db:
            rows = db.execute('SELECT id,body,revision,remote FROM jobs WHERE revision>sent ORDER BY rowid LIMIT 100').fetchall()
        for local_id, body, revision, remote in rows:
            doc = json.loads(body)
            try:
                exp = api.experiment(doc['project'])
                if not remote:
                    found = api.call('runs/search', {'experiment_ids': [exp], 'filter': "tags.tracker_id = '" + local_id + "'", 'max_results': 2}).get('runs', [])
                    if len(found) > 1:
                        raise RuntimeError('Duplicate tracker_id on server; review before syncing.')
                    if found:
                        remote = found[0]['info']['run_id']
                    else:
                        remote = api.call('runs/create', {'experiment_id': exp, 'start_time': doc['start'], 'tags': [{'key':'tracker_id','value':local_id}, {'key':'mlflow.runName','value':doc['name']} ]})['run']['info']['run_id']
                    with connect() as db:
                        db.execute('UPDATE jobs SET remote=? WHERE id=?', (remote,local_id))
                tags = dict(doc['tags'], tracker_id=local_id)
                api.call('runs/log-batch', {'run_id':remote, 'tags':[{'key':k,'value':str(v)[:4000]} for k,v in tags.items()], 'params': [], 'metrics':[{'key':k,'value':v,'timestamp':doc.get('end',doc['start']),'step':0} for k,v in doc['metrics'].items()]})
                update = {'run_id':remote, 'status':doc['status']}
                if 'end' in doc:
                    update['end_time'] = doc['end']
                api.call('runs/update', update)
                with connect() as db:
                    db.execute('UPDATE jobs SET sent=? WHERE id=?', (revision,local_id))
                print('Synced:',doc['name'],doc['status'],flush=True)
            except Exception as error:
                print('Sync pending (local data kept):', type(error).__name__, str(error)[:200],flush=True)
                break

class Experiment:
    """For Python backends: create one context per experiment/request."""
    def __init__(self, project, name=None, model='unknown', job='inference', source='vscode', tags=None):
        cfg = config()
        self.doc = {'id':uuid.uuid4().hex, 'project':project, 'name':name or project+'-'+time.strftime('%Y%m%d-%H%M%S'), 'start':now(), 'status':'RUNNING', 'metrics':{}, 'tags':{'execution_env':cfg['env'],'source':source,'host_name':socket.gethostname(),'job_type':job,'model_name':model}}
        self.doc['tags'].update(tags or {})
    def __enter__(self):
        save(self.doc)
        self.clock = time.monotonic()
        return self
    def log(self, **metrics):
        self.doc['metrics'].update(valid_metrics(metrics))
        save(self.doc)
    def __exit__(self, typ, value, tb):
        self.doc['end'] = now()
        self.doc['status'] = 'FINISHED' if typ is None else ('KILLED' if typ is KeyboardInterrupt else 'FAILED')
        self.doc['metrics']['pipeline_total_sec'] = time.monotonic()-self.clock
        if typ:
            self.doc['tags']['error_type'] = typ.__name__
        save(self.doc)
        return False

def signature(path):
    if not path or not path.is_file():
        return None
    s = path.stat()
    return (s.st_mtime_ns, s.st_size, hashlib.sha256(path.read_bytes()).hexdigest())

def nnunet_info(cmd):
    if not cmd or Path(cmd[0]).name not in ('nnUNetv2_train','nnUNetv2_train.exe') or len(cmd)<4:
        return None
    ds, configuration, fold = cmd[1:4]
    def opt(key, default):
        return cmd[cmd.index(key)+1] if key in cmd else default
    plans, trainer = opt('-p','nnUNetPlans'), opt('-tr','nnUNetTrainer')
    root = os.getenv('nnUNet_results')
    if not root:
        raise ValueError('nnUNet_results is missing; activate nnunet conda environment first.')
    matches = list(Path(root).glob('Dataset'+f'{int(ds):03d}'+'_*')) if ds.isdigit() else [Path(root)/ds]
    if not matches and ds.isdigit() and os.getenv('nnUNet_preprocessed'):
        candidates=list(Path(os.environ['nnUNet_preprocessed']).glob('Dataset'+f'{int(ds):03d}'+'_*'))
        if len(candidates)==1:
            matches=[Path(root)/candidates[0].name]
    if len(matches)!=1:
        raise ValueError('Dataset folder is ambiguous/missing. Check nnUNet_results and nnUNet_preprocessed.')
    folder = matches[0]/(trainer+'__'+plans+'__'+configuration)/('fold_'+fold)
    return {'project':matches[0].name,'model':plans,'name':matches[0].name+'-fold'+fold+'-'+time.strftime('%Y%m%d-%H%M%S'), 'summary':folder/'validation'/'summary.json', 'tags':{'dataset_id':ds,'fold':fold,'configuration':configuration,'plans':plans,'trainer':trainer}}

def run_command(args):
    cmd = args.command
    if cmd and cmd[0]=='--': cmd=cmd[1:]
    if not cmd: raise ValueError('Missing command after --')
    auto = nnunet_info(cmd) if not args.project else None
    project = args.project or (auto or {}).get('project')
    if not project: raise ValueError('For generic commands specify --project NAME')
    path = Path(args.metrics_file).resolve() if args.metrics_file else (auto or {}).get('summary')
    before = signature(path)
    tags = dict((auto or {}).get('tags',{}))
    tags['cuda_visible_devices'] = os.getenv('CUDA_VISIBLE_DEVICES','unspecified')
    # Keep result paths local; do not publish filesystem identifiers.
    exp = Experiment(project, args.name or (auto or {}).get('name'), args.model or (auto or {}).get('model','unknown'), args.job, args.source, tags)
    stop = threading.Event()
    def pump():
        while not stop.is_set():
            try: sync_once()
            except Exception as e: print('Sync worker:', str(e)[:200],flush=True)
            stop.wait(15)
    log = HOME/'logs'/(exp.doc['id']+'.log')
    log.parent.mkdir(parents=True,exist_ok=True)
    # Log path is printed locally, not sent to MLflow.
    code=1
    with exp:
        thread=threading.Thread(target=pump,daemon=True); thread.start()
        print('Local ID:',exp.doc['id'],'\nOutput log:',log,flush=True)
        with log.open('wb') as output:
            child=subprocess.Popen(cmd,stdout=output,stderr=subprocess.STDOUT)
            def terminate(signum,frame):
                child.terminate()
                raise KeyboardInterrupt()
            previous=signal.signal(signal.SIGTERM,terminate)
            try:
                code=child.wait()
            except KeyboardInterrupt:
                child.terminate()
                try: child.wait(timeout=20)
                except subprocess.TimeoutExpired: child.kill(); child.wait()
                raise
            finally:
                signal.signal(signal.SIGTERM,previous)
        exp.doc['tags']['exit_code']=str(code)
        if code!=0:
            raise subprocess.CalledProcessError(code,cmd)
        try:
            after=signature(path)
            if after is not None and after!=before:
                data=json.loads(path.read_text(encoding='utf-8'))
                if auto:
                    exp.log(dice_mean=float(data['foreground_mean']['Dice']))
                    exp.doc['tags']['dice_definition']='nnUNet foreground_mean Dice'
                else:
                    exp.log(**valid_metrics(data))
            elif path:
                exp.doc['tags']['metric_warning']='No new result file; old metrics deliberately skipped'
        except Exception as e:
            exp.doc['tags']['metric_warning']='Metric parsing failed: '+type(e).__name__
    stop.set()
    thread.join(timeout=1)
    sync_once()
    return code

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('init'); p.add_argument('--env',choices=['service','local','ai-1','ai-2'],required=True); p.add_argument('--uri',default='http://127.0.0.1:5000')
    p=sub.add_parser('sync'); p.add_argument('--once',action='store_true')
    sub.add_parser('status')
    p=sub.add_parser('run'); p.add_argument('--project'); p.add_argument('--name'); p.add_argument('--model'); p.add_argument('--job',default='train'); p.add_argument('--source',default='vscode'); p.add_argument('--metrics-file'); p.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    if args.action=='init':
        HOME.mkdir(parents=True,exist_ok=True)
        target=HOME/'config.json'
        if target.exists():
            old=json.loads(target.read_text())
            if old['uri']!=args.uri:
                raise SystemExit('Changing server URI is not supported for an existing queue. Use a new EXPERIMENT_TRACKER_HOME.')
        target.write_text(json.dumps({'env':args.env,'uri':args.uri}),encoding='utf-8')
        print('Configured:',target)
    elif args.action=='status':
        with connect() as db:
            for body,rev,sent in db.execute('SELECT body,revision,sent FROM jobs ORDER BY rowid DESC LIMIT 30'):
                d=json.loads(body); print(d['id'], d['name'],d['status'],'synced' if rev==sent else 'PENDING')
    elif args.action=='sync':
        while True:
            try: sync_once()
            except Exception as e: print(type(e).__name__,str(e)[:200],flush=True)
            if args.once: break
            time.sleep(15)
    else:
        try: sys.exit(run_command(args))
        except subprocess.CalledProcessError as e:
            try: sync_once()
            except Exception: pass
            sys.exit(e.returncode if e.returncode>0 else 1)
        except KeyboardInterrupt:
            try: sync_once()
            except Exception: pass
            sys.exit(130)

if __name__=='__main__':
    main()
