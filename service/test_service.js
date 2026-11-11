'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const vm=require('node:vm');
(async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'service-track-test-'));
 process.env.SERVICE_TRACKER_OUTBOX=dir;
 const track=require('./service_experiment_tracker');
 const a=track.start('shoulder'), b=track.start('patient-name-secret');
 const end=a.pipelineStart(); end(); end();
 a.finish(true,{stl_files:[{name:'PRIVATE_PATIENT_FILENAME'}],landmarks_generated:true,patient_id:'PRIVATE_PATIENT_ID'});
 a.finish(false); b.finish(false,{message:'SECRET_ERROR_PATH'});
 await Promise.all([a.flush(),b.flush()]);
 const files=fs.readdirSync(dir).filter(f=>f.endsWith('.json')); assert.equal(files.length,2);
 const rows=files.map(f=>JSON.parse(fs.readFileSync(path.join(dir,f),'utf8')));
 assert.deepEqual(rows.map(x=>x.status).sort(),['FAILED','FINISHED']);
 const ok=rows.find(x=>x.status==='FINISHED'); assert.equal(ok.metrics.stl_count,1);
 assert.ok(ok.metrics.python_pipeline_sec>=0); assert.equal(rows.find(x=>x.status==='FAILED').tags.seg_type,'other');
 assert.ok(!JSON.stringify(rows).match(/PRIVATE|SECRET|patient-name/));
 // Disk failure must not reject the request or finish call.
 const bad=path.join(dir,'not-a-directory'); fs.writeFileSync(bad,'x');
 delete require.cache[require.resolve('./service_experiment_tracker')]; process.env.SERVICE_TRACKER_OUTBOX=bad;
 const c=require('./service_experiment_tracker').start('skull'); c.finish(true,{}); await c.flush();
 fs.rmSync(dir,{recursive:true,force:true});
 console.log('PASS: concurrent isolation, success/failure, idempotent finish, privacy, timing, disk failure');
})().catch(e=>{console.error(e);process.exitCode=1});
