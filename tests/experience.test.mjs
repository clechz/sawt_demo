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
function controlsFixture(){
 const notice={textContent:'ببدء المكالمة، توافق على تسجيلها للمراجعة.'};
 const root={getElementById:id=>id==='recording-notice'?notice:null};
 return createExperienceControls(root);
}
test('Cedar starts in one action with the disclosed recording and no checkbox',()=>{
 const controls=controlsFixture();
 assert.deepEqual(controls.value(),{voice:'cedar',scenario:'new_order',recording_consent:false,experience_version:'v3',conversation_mode:'model_led'});
 assert.deepEqual(controls.value({startRequested:true}),{voice:'cedar',scenario:'new_order',recording_consent:true,experience_version:'v3',conversation_mode:'model_led'});
 assert.equal(controls.value({startRequested:false}).recording_consent,false);
 assert.equal(controls.value({startRequested:'true'}).recording_consent,false);
 assert.equal(controls.value().recording_consent,false,'start acknowledgment is not a sticky setting');
});
test('a busy call cannot authorize another start; ending restores one-click start',()=>{
 const controls=controlsFixture();
 controls.setBusy(true);
 assert.equal(controls.value({startRequested:true}).recording_consent,false);
 controls.setBusy(false);
 assert.equal(controls.value({startRequested:true}).recording_consent,true);
});
test('the customer interface must include a nonempty recording notice',()=>{
 assert.throws(()=>createExperienceControls({getElementById:()=>null}),/Recording notice/);
 assert.throws(()=>createExperienceControls({getElementById:()=>({textContent:' '})}),/Recording notice/);
});
test('Abdullah challenge is restored, with no checkbox, selectors or thinking telemetry',()=>{
 const html=readFileSync(new URL('../static/v2/index.html',import.meta.url),'utf8');
 assert.match(html,/<header class="brand">[\s\S]*?<span class="brand-credit">تحدي عبدالله<\/span><\/header>/);
 assert.match(html,/id="voice-orb"/);
 assert.match(html,/id="mute"/);
 assert.match(html,/<button id="start"[^>]*aria-describedby="recording-notice"/);
 assert.match(html,/<p id="recording-notice"[^>]*>ببدء المكالمة، توافق على تسجيلها للمراجعة\.<\/p>/);
 assert.doesNotMatch(html,/id="experience-consent"|type="checkbox"|id="voice-choice"|id="scenario-choice"|id="experience-settings"|id="worker-version"/);
 assert.match(html,/مساعد صوتي تجريبي/);
 const css=readFileSync(new URL('../static/v2/experience.css',import.meta.url),'utf8');
 assert.match(css,/\.brand\{gap:16px\}/);
 assert.doesNotMatch(css,/recording-consent/);
});
test('application requests the disclosed recording only through its start handler',()=>{
 const app=readFileSync(new URL('../static/v2/app.js',import.meta.url),'utf8');
 assert.match(app,/async function start\(\)[\s\S]*?experienceControls\.value\(\{startRequested:true\}\)/);
 assert.match(app,/\$\('start'\)\.onclick=start/);
 assert.match(app,/\$\('access'\)\.onsubmit=e=>\{e\.preventDefault\(\);accessCode=\$\('code'\)\.value;start\(\);\}/);
 assert.doesNotMatch(app,/experience-consent|وافق على تسجيل المكالمة قبل البدء/);
});
test('support view renders plain text rather than executing caller content',()=>{
 const panel={dataset:{},replaceChildren(...nodes){this.nodes=nodes;}};
 const root={getElementById:()=>panel,createElement:()=>({})};
 renderSupport(root,{orders:{},cases:[{id:'<script>bad</script>',status:'open'}]});
 assert.equal(panel.nodes[0].textContent,'<script>bad</script> · البلاغ مفتوح');
 assert.equal(panel.hidden,false);
});
