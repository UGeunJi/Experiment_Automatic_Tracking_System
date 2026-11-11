'use strict';
// Only explicitly constructed metadata is persisted. Never pass req, paths or stdout.
const fs = require('fs');
const path = require('path');
const os = require('os');
const { randomUUID } = require('crypto');
const OUTBOX = process.env.SERVICE_TRACKER_OUTBOX || path.join(os.homedir(), '.service-tracker-outbox');
const TYPES = new Set(['shoulder', 'skull', 'ankle', 'talus', 'hip', 'knee', 'spine', 'mandible', 'fibula']);
function seconds(start) { return Number(process.hrtime.bigint() - start) / 1e9; }
function start(rawType) {
  try {
    const type = rawType == null || rawType === '' ? 'shoulder' : (TYPES.has(rawType) ? rawType : 'other');
    const id = randomUUID().replace(/-/g, '');
    const began = process.hrtime.bigint();
    const doc = {id, project:'service-auto-seg', name:`auto-seg-${type}-${id.slice(0,8)}`, start:Date.now(), status:'RUNNING', metrics:{}, tags:{source:'service', execution_env:'service', job_type:'inference', model_name:`configured-${type}-pipeline`, endpoint:'auto_seg_draft', seg_type:type, timing_scope:'request_processing_and_python_pipeline'}};
    let chain = Promise.resolve(), ended = false;
    function persist() {
      const body = JSON.stringify(doc);
      chain = chain.then(async () => {
        await fs.promises.mkdir(OUTBOX, {recursive:true});
        const tmp = path.join(OUTBOX, id + '.tmp');
        await fs.promises.writeFile(tmp, body, {encoding:'utf8', mode:0o600});
        await fs.promises.rename(tmp, path.join(OUTBOX,id+'.json'));
      }).catch(() => console.warn('[experiment tracker] local write failed; inference continues'));
    }
    persist();
    return {
      pipelineStart() {
        const clock = process.hrtime.bigint();
        doc.metrics.before_pipeline_sec = seconds(began);
        let completed = false;
        return function () {
          if (completed) return;
          completed = true;
          doc.metrics.python_pipeline_sec = seconds(clock);
        };
      },
      finish(ok, result) {
        if (ended) return;
        ended = true;
        doc.status = ok ? 'FINISHED' : 'FAILED';
        doc.end = Date.now();
        doc.metrics.pipeline_total_sec = seconds(began);
        if (ok && result) {
          doc.metrics.stl_count = Array.isArray(result.stl_files) ? result.stl_files.length : 0;
          doc.metrics.landmarks_generated = result.landmarks_generated === true ? 1 : 0;
        }
        // Do not persist raw error messages, patient IDs, file names or results.
        doc.tags.outcome = ok ? 'application_success' : 'application_failure';
        persist();
      },
      flush() { return chain; }
    };
  } catch (_) { return {pipelineStart:()=>()=>{}, finish:()=>{}, flush:()=>Promise.resolve()}; }
}
module.exports = {start};
