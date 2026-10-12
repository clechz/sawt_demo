import test from 'node:test';
import assert from 'node:assert/strict';
import {ReadbackPlayer} from '../static/v2/playback.js';

function fixture(override={}){
 const calls=[],phases=[],muting=[],errors=[],retries=[],timers=new Map();let audio,id=0;
 const player=new ReadbackPlayer({api:async(path,options)=>{calls.push([path,options]);return{json:async()=>({receipt_id:'r',url:'/audio'})};},createAudio:()=>audio={play:async()=>{},pause(){},removeAttribute(){},load(){},currentTime:12},mute:x=>muting.push(x),phase:x=>phases.push(x),failure:x=>errors.push(x),retry:x=>retries.push(x),setTimer:fn=>{timers.set(++id,fn);return id;},clearTimer:id=>timers.delete(id),...override});
 return{player,calls,phases,muting,errors,retries,timers,get audio(){return audio;}};
}
test('completion uses actual playback position, after the start acknowledgment',async()=>{
 const f=fixture();await f.player.play('s');f.audio.onplaying();await f.audio.onended();
 assert.deepEqual(f.phases,['preparing','readback','confirm']);
 assert.equal(JSON.parse(f.calls[2][1].body).position,12);
 assert.equal(f.muting.at(-1),false);
});
test('canceled old ended callback cannot acknowledge or overwrite new audio',async()=>{
 const f=fixture();await f.player.play('s');f.audio.onplaying();const oldEnded=f.audio.onended;
 f.player.cancel();await f.player.play('s');await oldEnded();
 assert.equal(f.calls.filter(([,o])=>o.body&&JSON.parse(o.body).phase==='completed').length,0);
 assert.equal(f.phases.at(-1),'preparing');
});
test('cancel while prepare is pending discards late response',async()=>{
 let resolve;const f=fixture({api:()=>new Promise(r=>resolve=r)});
 const pending=f.player.play('s');assert.equal(f.player.active,true);f.player.cancel();resolve({json:async()=>({receipt_id:'old',url:'/old'})});await pending;
 assert.equal(f.audio,undefined);assert.equal(f.muting.at(-1),false);
 assert.equal(f.player.active,false);
});
test('audio error restores conversational audio and never confirms',async()=>{
 const f=fixture();await f.player.play('s');f.audio.onerror();
 assert.equal(f.muting.at(-1),false);assert.equal(f.phases.at(-1),'paused');assert.equal(f.calls.length,1);
});
test('start acknowledgment failure prevents completion',async()=>{
 const f=fixture({api:async(path,options)=>{if(options.body)throw new Error('offline');return{json:async()=>({receipt_id:'r',url:'/audio'})};}});
 await f.player.play('s');const a=f.audio;a.onplaying();await Promise.resolve();
 assert.equal(f.phases.at(-1),'paused');assert.equal(f.player.audio,null);
});

test('visualization teardown failure cannot prevent canceling actual speech',async()=>{
 const f=fixture({releaseAudio:()=>{throw new Error('meter failed');}});
 await f.player.play('s');assert.doesNotThrow(()=>f.player.cancel());
 assert.equal(f.player.audio,null);assert.equal(f.muting.at(-1),false);
});

test('incomplete stream can retry but cannot mark checkout heard',async()=>{
 const f=fixture({api:async(path,options)=>{
  if(options.body&&JSON.parse(options.body).phase==='completed')throw Object.assign(new Error('Readback has not finished playing'),{status:409,code:'readback_incomplete'});
  return{json:async()=>({receipt_id:'r',url:'/audio'})};
 }});
 await f.player.play('s');f.audio.onplaying();await f.audio.onended();
 assert.equal(f.phases.at(-1),'paused');assert.equal(f.retries.at(-1),true);
 assert.match(f.errors.at(-1),/الملخص ما اكتمل/);assert.ok(!f.phases.includes('confirm'));
});

test('changed order still rejects stale playback without retrying old summary',async()=>{
 const f=fixture({api:async()=>{throw Object.assign(new Error('Invalid playback receipt'),{status:409,code:'conflict'});}});
 await f.player.play('s');assert.equal(f.retries.at(-1),false);assert.match(f.errors.at(-1),/طلبك تغيّر/);
});

test('stalled stream restores conversation and offers retry without confirming',async()=>{
 const f=fixture();await f.player.play('s');f.audio.onplaying();assert.equal(f.timers.size,0);
 f.audio.onwaiting();assert.equal(f.timers.size,1);[...f.timers.values()][0]();
 assert.equal(f.phases.at(-1),'paused');assert.equal(f.retries.at(-1),true);assert.equal(f.muting.at(-1),false);
 assert.equal(f.timers.size,0);assert.ok(!f.phases.includes('confirm'));
});

test('old stall timer cannot cancel a later playback generation',async()=>{
 const f=fixture();await f.player.play('s');const oldTimeout=[...f.timers.values()][0];
 await f.player.play('s');oldTimeout();
 assert.equal(f.player.active,true);assert.equal(f.phases.at(-1),'preparing');assert.equal(f.errors.length,0);
 f.player.cancel();assert.equal(f.timers.size,0);
});
