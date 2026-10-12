import test from 'node:test';
import assert from 'node:assert/strict';
import {PlaybackMeter,MicrophoneMeter} from '../static/v2/audio-meter.js';

function fixture(){
 const events=new EventTarget(),stream=new EventTarget();
 const track={stopped:0,stop(){this.stopped++;}};
 stream.getAudioTracks=stream.getTracks=()=>[track];
 const source={connections:[],disconnects:0,connect(x){this.connections.push(x);},disconnect(){this.disconnects++;}};
 const analyser={fftSize:0,getFloatTimeDomainData:buffer=>buffer.fill(.1),disconnect(){}};
 const context={state:'running',resume:async()=>{},close:async()=>{context.state='closed';},createAnalyser:()=>analyser,createMediaStreamSource:()=>source};
 const audio=Object.assign(events,{captureStream:()=>stream});
 const meter=new PlaybackMeter(()=>context);
 return{meter,context,audio,source,analyser,track};
}

test('microphone meter observes existing track immediately and never stops or plays it',()=>{
 const previous=globalThis.MediaStream;
 globalThis.MediaStream=class {constructor(tracks){this.tracks=tracks;}};
 try {
  const f=fixture(),meter=new MicrophoneMeter(()=>f.context);
  meter.prepare();meter.attachTrack(f.track);
  assert.ok(meter.level()>.39);
  assert.deepEqual(f.source.connections,[f.analyser]);
  meter.close();assert.equal(f.track.stopped,0);assert.equal(f.source.disconnects,1);
 } finally {globalThis.MediaStream=previous;}
});
test('readback meter measures captured speech without a speaker connection',()=>{
 const f=fixture();f.meter.prepare();f.meter.attach(f.audio);
 assert.equal(f.meter.level(),0);f.audio.dispatchEvent(new Event('playing'));
 assert.ok(Math.abs(f.meter.level()-.4)<.001);
 assert.deepEqual(f.source.connections,[f.analyser]);
 f.meter.close();assert.equal(f.meter.level(),0);assert.equal(f.track.stopped,1);
 assert.equal(f.source.disconnects,1);
});
test('cancel before playback removes listener and cannot resurrect a stale meter',()=>{
 const f=fixture();f.meter.prepare();f.meter.attach(f.audio);f.meter.detach();
 f.audio.dispatchEvent(new Event('playing'));
 assert.equal(f.source.connections.length,0);assert.equal(f.meter.level(),0);
});
test('unsupported capture and unavailable Web Audio degrade without affecting playback',()=>{
 const f=fixture();f.meter.prepare();f.meter.attach(new EventTarget());
 assert.equal(f.meter.level(),0);f.meter.close();
 const unavailable=new PlaybackMeter(()=>{throw new Error('unsupported');});
 assert.doesNotThrow(()=>{unavailable.prepare();unavailable.attach(f.audio);unavailable.close();});
});
test('replacing readback releases only the previous captured stream',()=>{
 const f=fixture();f.meter.prepare();f.meter.attach(f.audio);f.audio.dispatchEvent(new Event('playing'));
 f.meter.attach(new EventTarget());assert.equal(f.track.stopped,1);
 assert.equal(f.meter.level(),0);f.meter.detach();assert.equal(f.track.stopped,1);
});
