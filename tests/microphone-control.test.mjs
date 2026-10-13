import test from 'node:test';
import assert from 'node:assert/strict';
import {setMicrophoneCapture,syncMicrophoneMute} from '../static/v2/microphone-control.js';
import {readFileSync} from 'node:fs';

test('mic mute supplies silence without muting speaker, stopping track or unpublishing',async()=>{
 let forbidden=0;const mic={enabled:true,stop(){forbidden++;}};
 const screen={enabled:true};const speaker={muted:false};
 const participant={audioTrackPublications:new Map([
  ['mic',{source:'microphone',track:{mediaStreamTrack:mic},mute(){forbidden++;}}],
  ['screen',{source:'screen_share_audio',track:{mediaStreamTrack:screen}}]
 ]),setMicrophoneEnabled(){forbidden++;}};
 setMicrophoneCapture(participant,true);
 assert.equal(mic.enabled,false);assert.equal(screen.enabled,true);assert.equal(speaker.muted,false);
 setMicrophoneCapture(participant,false);assert.equal(mic.enabled,true);assert.equal(forbidden,0);
});
test('mute state is bound to the call and sent reliably, not as a conversation instruction',async()=>{
 let sent;await syncMicrophoneMute({publishData:async(data,options)=>{sent={body:JSON.parse(new TextDecoder().decode(data)),options};}},'call-1',true,8);
 assert.deepEqual(sent,{body:{call_id:'call-1',muted:true,sequence:8},options:{reliable:true,topic:'sawt-mic'}});
});
test('failed remote synchronization leaves the microphone locally muted',async()=>{
 const mic={enabled:true};const participant={audioTrackPublications:new Map([['m',{source:'microphone',track:{mediaStreamTrack:mic}}]]),publishData:async()=>{throw Error('network');}};
 setMicrophoneCapture(participant,true);await assert.rejects(syncMicrophoneMute(participant,'call-1',true,1));assert.equal(mic.enabled,false);
});
test('missing microphone is reported instead of claiming successful mute',()=>{
 assert.throws(()=>setMicrophoneCapture({audioTrackPublications:new Map()},true));
});
test('main screen removes selectors and puts status outside the orb while retaining explicit recording consent',()=>{
 const html=readFileSync(new URL('../static/v2/index.html',import.meta.url),'utf8');
 assert.ok(!html.includes('<select'));assert.ok(!html.includes('id="worker-version"'));
 assert.ok(html.indexOf('class="call-state"')>html.indexOf('</div>',html.indexOf('id="start-label"')));
 assert.match(html,/<input id="experience-consent" type="checkbox">/);
 assert.match(html,/بدون طلبات حقيقية/);
});
