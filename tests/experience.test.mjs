import {readFileSync} from 'node:fs';
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
test('Ash is the only visible default; consent is still explicit',()=>{
 const consent={checked:false,disabled:false};
 const root={getElementById:id=>id==='experience-consent'?consent:null};
 const controls=createExperienceControls(root);
 assert.deepEqual(controls.value(),{voice:'ash',scenario:'new_order',recording_consent:false,experience_version:'v3',conversation_mode:'model_led'});
 consent.checked=true;
 assert.equal(controls.value().recording_consent,true);
 controls.setBusy(true);assert.equal(consent.disabled,true);
 controls.setBusy(false);assert.equal(consent.disabled,false);
});
test('customer page has one orb, consent, no voice or scenario selection or thinking telemetry',()=>{
 const html=readFileSync(new URL('../static/v2/index.html',import.meta.url),'utf8');
 assert.match(html,/id="voice-orb"/);
 assert.match(html,/id="experience-consent"/);
 assert.match(html,/id="mute"/);
 assert.doesNotMatch(html,/id="voice-choice"|id="scenario-choice"|id="experience-settings"|id="worker-version"/);
 assert.match(html,/مساعد صوتي تجريبي/);
});
test('support view renders plain text rather than executing caller content',()=>{
 const panel={dataset:{},replaceChildren(...nodes){this.nodes=nodes;}};
 const root={getElementById:()=>panel,createElement:()=>({})};
 renderSupport(root,{orders:{},cases:[{id:'<script>bad</script>',status:'open'}]});
 assert.equal(panel.nodes[0].textContent,'<script>bad</script> · البلاغ مفتوح');
 assert.equal(panel.hidden,false);
});
