import test from 'node:test';
import assert from 'node:assert/strict';
import {selectedExperience,createExperienceControls,renderSupport} from '../static/v2/experience-ui.js';
test('voice selection is explicit and rejects unsupported IDs',()=>{
 for(const voice of ['cedar','ash','marin'])assert.equal(selectedExperience(voice,'new_order',true).voice,voice);
 assert.throws(()=>selectedExperience('spruce','new_order',true));
 assert.throws(()=>selectedExperience('cedar','invented',true));
 assert.equal(selectedExperience('cedar','new_order','true').recording_consent,false);
});
test('voice changes only for the next call and consent is explicit',()=>{
 const elements=new Map();
 const root={getElementById:id=>{if(!elements.has(id))elements.set(id,{value:id==='voice-choice'?'cedar':'new_order',checked:false,addEventListener(){}});return elements.get(id);}};
 const controls=createExperienceControls(root);
 assert.equal(controls.value().recording_consent,false);
 root.getElementById('experience-consent').checked=true;
 const a=controls.value();controls.setBusy(true);
 assert.equal(root.getElementById('voice-choice').disabled,true);
 controls.setBusy(false);root.getElementById('voice-choice').value='ash';const b=controls.value();
 assert.equal(a.voice,'cedar');assert.equal(b.voice,'ash');assert.equal(b.recording_consent,true);
});
test('support view renders plain text rather than executing caller content',()=>{
 const panel={dataset:{},replaceChildren(...nodes){this.nodes=nodes;}};
 const root={getElementById:()=>panel,createElement:()=>({})};
 renderSupport(root,{orders:{},cases:[{id:'<script>bad</script>',status:'open'}]});
 assert.equal(panel.nodes[0].textContent,'<script>bad</script> · البلاغ مفتوح');
 assert.equal(panel.hidden,false);
});
