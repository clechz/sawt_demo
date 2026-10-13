import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {PlaybackMeter,MicrophoneMeter} from '../static/v2/audio-meter.js';

test('blocked autoplay still publishes mic; direct caller and AI samples drive the orb',async()=>{
 const elements=new Map(),levels=[],order=[];let frame,instance,sample=0;
 const element=id=>{if(!elements.has(id))elements.set(id,{hidden:true,style:{},setAttribute(){},addEventListener(){},append(){}});return elements.get(id);};
 const context={state:'running',resume:async()=>{},close:async()=>{},createMediaStreamSource:()=>({connect(){},disconnect(){}}),createAnalyser:()=>({fftSize:0,getFloatTimeDomainData:a=>a.fill(sample),disconnect(){}})};
 const oldStream=globalThis.MediaStream;globalThis.MediaStream=class{constructor(tracks){this.tracks=tracks;}};
 // Meter factories execute in this test realm, so inject the primed context.
 class Meter extends MicrophoneMeter{constructor(factory){super(factory||(()=>context));}}
 class Playback extends PlaybackMeter{constructor(){super(()=>context);}}
 class Room {
  constructor(){instance=this;this.events={};this.remoteParticipants=new Map();this.localParticipant={audioLevel:0,setMicrophoneEnabled:async()=>order.push('microphone')};}
  on(name,fn){this.events[name]=fn;}
  async startAudio(){order.push('unlock');throw Error('autoplay blocked');}
  async connect(){order.push('connect');}
  async disconnect(){}
 }
 const events=Object.fromEntries(['LocalTrackPublished','LocalTrackUnpublished','TrackSubscribed','TrackUnsubscribed','DataReceived','Reconnecting','Reconnected','Disconnected'].map(x=>[x,x]));
 const sandbox={createExperienceControls:()=>({value:()=>({recording_consent:true,experience_version:"v3",voice:"cedar",scenario:"new_order"}),setBusy(){}}),renderSupport:()=>{},PlaybackMeter:Playback,MicrophoneMeter:Meter,ReadbackPlayer:class{cancel(){}},createOrderView:()=>()=>{},createCallStatus:()=>({reset(){},phase(){},audio(){}}),document:{getElementById:element,body:{dataset:{},classList:{add(){},remove(){}}},documentElement:{style:{setProperty(){}}}},window:{addEventListener(){},dispatchEvent:e=>levels.push(e.detail)},CustomEvent:class{constructor(type,options){this.detail=options.detail;}},location:{pathname:'/'},localStorage:{setItem(){}},LivekitClient:{Room,RoomEvent:events},fetch:async path=>{order.push('fetch');return{ok:true,json:async()=>path==='/api/calls'?{id:'test',token:'token',max_seconds:600}:{state:{}}};},setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},requestAnimationFrame:fn=>{frame=fn;return 1;},cancelAnimationFrame(){},console};
 try{
  const code=readFileSync(new URL('../static/v2/app.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'');
  vm.runInNewContext(code,sandbox);await element('start').onclick();
  assert.ok(order.indexOf('unlock')<order.indexOf('fetch'),'speaker unlock precedes network request');
  assert.ok(order.includes('microphone'),'autoplay rejection must not abort microphone');
  assert.equal(element('controls').hidden,false);
  instance.events.LocalTrackPublished({track:{kind:'audio',mediaStreamTrack:{}}});sample=.08;frame(100);
  assert.ok(levels.at(-1)>.5,'caller PCM moves orb even when SDK level is zero');
  instance.events.LocalTrackUnpublished({kind:'audio'});
  const track={kind:'audio',mediaStreamTrack:{},attach:()=>({play:async()=>{},remove(){}}),detach:()=>[]};
  instance.events.TrackSubscribed(track);frame(150);
  assert.ok(levels.at(-1)>.5,'AI PCM moves orb even when SDK level is zero');
  sample=0;frame(200);assert.equal(levels.at(-1),0,'silence stops speech energy');
  instance.events.TrackUnsubscribed(track);await element('end').onclick();
 }finally{globalThis.MediaStream=oldStream;}
});
