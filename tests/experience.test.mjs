import './worker-binding.test.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {selectedExperience,createExperienceControls,renderSupport} from '../static/v2/experience-ui.js';
test('voice selection is explicit and rejects unsupported IDs',()=>{
 for(const voice of ['cedar','ash','marin'])assert.equal(selectedExperience(voice,'new_order',true).voice,voice);
 assert.throws(()=>selectedExperience('spruce','new_order',true));
 assert.throws(()=>selectedExperience('cedar','invented',true));
 assert.equal(selectedExperience('cedar','new_order','true').recording_consent,false);
});
test('simple caller UI always uses Ash; consent remains explicit',()=>{
 const consent={checked:false,disabled:false};
 const root={getElementById:id=>id==='experience-consent'?consent:null};
 const controls=createExperienceControls(root);
 assert.equal(controls.value().voice,'ash');
 assert.equal(controls.value().scenario,'new_order');
 assert.equal(controls.value().recording_consent,false);
 consent.checked=true;controls.setBusy(true);
 assert.equal(consent.disabled,true);assert.equal(controls.value().recording_consent,true);
 controls.setBusy(false);assert.equal(consent.disabled,false);
});
test('support view renders plain text rather than executing caller content',()=>{
 const panel={dataset:{},replaceChildren(...nodes){this.nodes=nodes;}};
 const root={getElementById:()=>panel,createElement:()=>({})};
 renderSupport(root,{orders:{},cases:[{id:'<script>bad</script>',status:'open'}]});
 assert.equal(panel.nodes[0].textContent,'<script>bad</script> · البلاغ مفتوح');
 assert.equal(panel.hidden,false);
});
