import {validateCallBinding,validateReadyBinding} from '../static/v2/worker-binding.js';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {PlaybackMeter,MicrophoneMeter} from '../static/v2/audio-meter.js';
import {stopMediaNow,closeSavedCall} from '../static/v2/call-lifecycle.js';
import {setMicrophoneSilenced} from '../static/v2/microphone-mute.js';

test('blocked autoplay still publishes mic; direct caller and AI samples drive the orb',async()=>{
 const binding={protocol:1,source_fingerprint:'a'.repeat(64),experience_version:'v3',conversation_mode:'model_led',voice:'ash',planner_model:'test-model',voice_model:'gpt-live-1'};
 const elements=new Map(),levels=[],order=[];let frame,instance,sample=0;
 const micTrack={enabled:true,readyState:'live'}; let remoteElement,attachments=0;
 const element=id=>{if(!elements.has(id))elements.set(id,{hidden:true,style:{},setAttribute(){},addEventListener(){},append(){}});return elements.get(id);};
 const context={state:'running',resume:async()=>{},close:async()=>{},createMediaStreamSource:()=>({connect(){},disconnect(){}}),createAnalyser:()=>({fftSize:0,getFloatTimeDomainData:a=>a.fill(sample),disconnect(){}})};
 const oldStream=globalThis.MediaStream;globalThis.MediaStream=class{constructor(tracks){this.tracks=tracks;}};
 // Meter factories execute in this test realm, so inject the primed context.
 class Meter extends MicrophoneMeter{constructor(factory){super(factory||(()=>context));}}
 class Playback extends PlaybackMeter{constructor(){super(()=>context);}}
 class Room {
  constructor(){instance=this;this.events={};this.remoteParticipants=new Map();this.localParticipant={audioLevel:0,audioTrackPublications:new Map([['mic',{track:{mediaStreamTrack:micTrack}}]]),setMicrophoneEnabled:async()=>order.push('microphone')};}
  on(name,fn){this.events[name]=fn;}
  async startAudio(){order.push('unlock');throw Error('autoplay blocked');}
  async connect(){order.push('connect');}
  async disconnect(){}
 }
 const events=Object.fromEntries(['LocalTrackPublished','LocalTrackUnpublished','TrackSubscribed','TrackUnsubscribed','DataReceived','Reconnecting','Reconnected','Disconnected'].map(x=>[x,x]));
 const sandbox={createCompletionView:()=>({reset(){},render:()=>false}),stopMediaNow:()=>Promise.resolve(),animateHangup:()=>Promise.resolve(),closeSavedCall:()=>Promise.resolve(null),validateCallBinding,validateReadyBinding,setMicrophoneSilenced,TextDecoder,createExperienceControls:()=>({value:()=>({recording_consent:true,experience_version:"v3",conversation_mode:"model_led",voice:"ash",scenario:"new_order"}),setBusy(){}}),renderSupport:()=>{},PlaybackMeter:Playback,MicrophoneMeter:Meter,ReadbackPlayer:class{unlock(){order.push('readback-unlock');}cancel(){}},createOrderView:()=>()=>{},createCallStatus:()=>({reset(){},phase(){},audio(){}}),document:{getElementById:element,body:{dataset:{},classList:{add(){},remove(){}}},documentElement:{style:{setProperty(){}}}},window:{addEventListener(){},dispatchEvent:e=>levels.push(e.detail)},CustomEvent:class{constructor(type,options){this.detail=options.detail;}},location:{pathname:'/'},localStorage:{setItem(){}},LivekitClient:{Room,RoomEvent:events},fetch:async path=>{order.push('fetch');return{ok:true,json:async()=>path==='/api/calls'?{id:'test',token:'token',max_seconds:600,required_worker:binding}:{state:{}}};},setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},requestAnimationFrame:fn=>{frame=fn;return 1;},cancelAnimationFrame(){},console};
 try{
  const code=readFileSync(new URL('../static/v2/app.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'');
  sandbox.stopMediaNow=stopMediaNow; sandbox.closeSavedCall=(call,code)=>closeSavedCall(call,code,sandbox.fetch);
  vm.runInNewContext(code,sandbox);await element('start').onclick();
  assert.ok(order.indexOf('readback-unlock')<order.indexOf('fetch'),'readback unlock precedes network request');
  assert.ok(order.indexOf('unlock')<order.indexOf('fetch'),'speaker unlock precedes network request');
  assert.ok(order.includes('microphone'),'autoplay rejection must not abort microphone');
  assert.equal(element('controls').hidden,false);
  instance.events.LocalTrackPublished({track:{kind:'audio',mediaStreamTrack:{}}});sample=.08;frame(100);
  assert.ok(levels.at(-1)>.5,'caller PCM moves orb even when SDK level is zero');
  instance.events.LocalTrackUnpublished({kind:'audio'});
  const track={kind:'audio',mediaStreamTrack:{},attach:()=>{attachments++;return remoteElement={play:async()=>{},remove(){},muted:false};},detach:()=>[]};
  instance.events.TrackSubscribed(track);frame(150);
  assert.equal(levels.at(-1),0,'unverified worker cannot appear as audible');
  instance.events.DataReceived(new TextEncoder().encode(JSON.stringify({type:'ready',call_id:'test',worker_contract:binding})),{identity:'voice-worker'},null,'sawt');
  frame(180);
  assert.ok(levels.at(-1)>.5,'AI PCM moves orb even when SDK level is zero');
  assert.equal(remoteElement.muted,false);
  const publicationToggleCount=order.filter(x=>x==='microphone').length;
  element('mute').onclick();
  assert.equal(micTrack.enabled,false,'mute sends silence while keeping the published track');
  assert.equal(remoteElement.muted,false,'the customer must still hear the AI while mic is muted');
  assert.equal(order.filter(x=>x==='microphone').length,publicationToggleCount,'mute cannot change SDK publication');
  element('mute').onclick();assert.equal(micTrack.enabled,true);
  sample=0;frame(220);assert.equal(levels.at(-1),0,'silence stops speech energy');
  // Hold the server cleanup request. Audio must be cut before it resolves.
  let finishEnd;const originalFetch=sandbox.fetch;
  sandbox.fetch=path=>path.endsWith('/end')?new Promise(resolve=>{finishEnd=()=>resolve({ok:true});}):originalFetch(path);
  const ending=element('end').onclick();
  assert.equal(remoteElement.muted,true,'hangup silences AI immediately even if server is stuck');
  const beforeAttachments=attachments;instance.events.TrackSubscribed(track);
  assert.equal(attachments,beforeAttachments,'late subscription is ignored');
  assert.equal(remoteElement.muted,true,'late subscription cannot resurrect audio after hangup');
  finishEnd();await ending;
 }finally{globalThis.MediaStream=oldStream;}
});
