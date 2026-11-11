'use strict';
// Framework-independent example. Wire this into the existing request handler.
// This module does not implement a web server or a segmentation model.
const tracker = require('./service_experiment_tracker');

async function trackedAutoSeg(segType, prepareInput, runPythonPipeline, makeResult) {
  const record = tracker.start(segType);
  try {
    const input = await prepareInput();
    // If a GPU queue exists, start timing INSIDE the queue after acquiring a slot.
    const endPipeline = record.pipelineStart();
    let output;
    try {
      output = await runPythonPipeline(input);
    } finally {
      endPipeline();
    }
    // HTTP 200 can still contain an application error.
    if (!output || output.status === 'error') throw new Error('Pipeline failed');
    const result = await makeResult(output);
    if (!result || result.status === 'error') throw new Error('Result generation failed');
    record.finish(true, result);
    return result;
  } catch (error) {
    record.finish(false);
    throw error; // existing API decides response status/body
  }
}
module.exports = {trackedAutoSeg};
