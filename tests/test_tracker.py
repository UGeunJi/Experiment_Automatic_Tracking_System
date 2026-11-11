import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import tracker

class FakeAPI:
    runs={}
    def __init__(self,uri): pass
    def experiment(self,name): return '1'
    def call(self,path,payload=None,query=None):
        if path=='runs/search':
            key=payload['filter'].split("'")[1]
            return {'runs':[{'info':{'run_id':rid}} for rid,r in self.runs.items() if r['key']==key]}
        if path=='runs/create':
            rid=str(len(self.runs)+1)
            self.runs[rid]={'key':payload['tags'][0]['value'],'metrics':{},'start':payload['start_time']}
            return {'run':{'info':{'run_id':rid}}}
        if path=='runs/log-batch':
            self.runs[payload['run_id']]['metrics'].update({m['key']:m['value'] for m in payload['metrics']})
        if path=='runs/update': self.runs[payload['run_id']].update(payload)
        return {}

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); tracker.HOME=Path(self.temp.name)
        (tracker.HOME/'config.json').write_text(json.dumps({'env':'ai-1','uri':'http://127.0.0.1:1'}))
        FakeAPI.runs={}
    def tearDown(self): self.temp.cleanup()
    def test_offline_then_replay_idempotent(self):
        with tracker.Experiment('test') as e: e.log(dice_mean=.9)
        with contextlib.redirect_stdout(io.StringIO()): tracker.sync_once()
        with tracker.connect() as db: self.assertEqual(db.execute('SELECT sent FROM jobs').fetchone()[0],0)
        with patch.object(tracker,'API',FakeAPI): tracker.sync_once(); tracker.sync_once()
        self.assertEqual(len(FakeAPI.runs),1)
        r=next(iter(FakeAPI.runs.values())); self.assertEqual(r['status'],'FINISHED'); self.assertEqual(r['metrics']['dice_mean'],.9)
    def test_failure_status(self):
        with self.assertRaises(ValueError):
            with tracker.Experiment('test'): raise ValueError('test')
        with tracker.connect() as db: self.assertEqual(json.loads(db.execute('SELECT body FROM jobs').fetchone()[0])['status'],'FAILED')
    def test_running_then_final_same_run(self):
        e=tracker.Experiment('test'); e.__enter__()
        with patch.object(tracker,'API',FakeAPI):
            tracker.sync_once(); e.log(dice_mean=.7); e.__exit__(None,None,None); tracker.sync_once()
        self.assertEqual(len(FakeAPI.runs),1)
        self.assertEqual(next(iter(FakeAPI.runs.values()))['status'],'FINISHED')
    def test_metric_validation(self):
        self.assertEqual(tracker.valid_metrics({'a':1,'b':float('nan'),'c':True,'d':'x'}),{'a':1.})
    def test_summary_change(self):
        p=tracker.HOME/'summary.json'; p.write_text('{"foreground_mean":{"Dice":0.8}}')
        first=tracker.signature(p); self.assertEqual(first,tracker.signature(p))
        p.write_text('{"foreground_mean":{"Dice":0.9}}'); self.assertNotEqual(first,tracker.signature(p))
    def test_auto_dataset(self):
        root=tracker.HOME/'results'; (root/'Dataset303_Test').mkdir(parents=True)
        with patch.dict(os.environ,{'nnUNet_results':str(root)}):
            a=tracker.nnunet_info(['nnUNetv2_train','303','3d_fullres','0','-p','nnUNetResEncUNetMPlans'])
        self.assertEqual(a['project'],'Dataset303_Test'); self.assertEqual(a['tags']['fold'],'0')
    def test_real_child_offline_metrics(self):
        f=tracker.HOME/'metrics.json'
        env=dict(os.environ,EXPERIMENT_TRACKER_HOME=str(tracker.HOME))
        cmd=[sys.executable,str(Path(tracker.__file__)),'run','--project','demo','--metrics-file',str(f),'--',sys.executable,'-c',"import json;json.dump({'dice_mean':0.88},open("+repr(str(f))+",'w'))"]
        res=subprocess.run(cmd,env=env,capture_output=True,timeout=20)
        self.assertEqual(res.returncode,0,res.stderr.decode())
        with tracker.connect() as db: d=json.loads(db.execute('SELECT body FROM jobs').fetchone()[0])
        self.assertEqual(d['metrics']['dice_mean'],.88); self.assertEqual(d['status'],'FINISHED')
    def test_real_child_failed_exit(self):
        env=dict(os.environ,EXPERIMENT_TRACKER_HOME=str(tracker.HOME))
        res=subprocess.run([sys.executable,tracker.__file__,'run','--project','bad','--',sys.executable,'-c','raise SystemExit(7)'],env=env,capture_output=True,timeout=20)
        self.assertEqual(res.returncode,7)
        with tracker.connect() as db: d=json.loads(db.execute('SELECT body FROM jobs').fetchone()[0])
        self.assertEqual(d['status'],'FAILED')

if __name__=='__main__': unittest.main()
