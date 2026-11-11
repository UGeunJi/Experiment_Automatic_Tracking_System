import json
from pathlib import Path
import tempfile
import unittest
import tracker
import service_worker

class WorkerTest(unittest.TestCase):
    def test_ingestion(self):
        with tempfile.TemporaryDirectory() as t:
            tracker.HOME=Path(t)/'state'; out=Path(t)/'out'; out.mkdir()
            d={'id':'a'*32,'project':'service-auto-seg','name':'test','start':1,'status':'RUNNING','metrics':{},'tags':{'source':'service'}}
            p=out/(d['id']+'.json'); p.write_text(json.dumps(d))
            service_worker.ingest(out); service_worker.ingest(out)
            with tracker.connect() as db: self.assertEqual(db.execute('SELECT revision FROM jobs').fetchone()[0],1)
            d.update(status='FINISHED',end=2); d['metrics']['python_pipeline_sec']=1.2; p.write_text(json.dumps(d))
            service_worker.ingest(out)
            d['status']='RUNNING'; p.write_text(json.dumps(d)); service_worker.ingest(out)
            with tracker.connect() as db:
                row=db.execute('SELECT body,revision FROM jobs').fetchone()
                self.assertEqual(json.loads(row[0])['status'],'FINISHED'); self.assertEqual(row[1],2)
if __name__=='__main__': unittest.main()
