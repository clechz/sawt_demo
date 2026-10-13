import test from 'node:test';
import assert from 'node:assert/strict';
import {validateCallBinding,validateReadyBinding} from '../static/v2/worker-binding.js';
const requested={experience_version:'v3',conversation_mode:'model_led',voice:'cedar'};
const contract={protocol:1,source_fingerprint:'a'.repeat(64),...requested,planner_model:'test-model',voice_model:'gpt-live-1'};
const call={id:'this-call',required_worker:contract};
test('matching API and ready event pass',()=>{
 validateCallBinding(call,requested);
 assert.equal(validateReadyBinding(call,{call_id:call.id,worker_contract:{...contract}}).conversation_mode,'model_led');
});
for(const field of Object.keys(contract))test(`ready rejects different ${field}`,()=>{
 assert.throws(()=>validateReadyBinding(call,{call_id:call.id,worker_contract:{...contract,[field]:'old'}}));
});
test('old API and generic ready messages do not masquerade as model-led calls',()=>{
 assert.throws(()=>validateCallBinding({id:'old'},requested));
 assert.throws(()=>validateReadyBinding(call,{type:'ready'}));
 assert.throws(()=>validateReadyBinding(call,{call_id:'old-call',worker_contract:contract}));
});
test('API cannot silently change requested mode or voice',()=>{
 assert.throws(()=>validateCallBinding(call,{...requested,voice:'ash'}));
 assert.throws(()=>validateCallBinding(call,{...requested,conversation_mode:'legacy'}));
});
