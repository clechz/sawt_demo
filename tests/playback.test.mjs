import test from 'node:test';
import assert from 'node:assert/strict';
import {ReadbackPlayer} from '../static/v2/playback.js';

function fixture(override={}){
 const calls=[],phases=[],muting=[],errors=[];let audio;
 const player=new ReadbackPlayer({api:async(path,options)=>{calls.push([path,options]);return{json:async()=>({receipt_id:'r',url:'/audio'})};},createAudio:()=>audio={play:async()=>{},pause(){},removeAttribute(){},load(){},currentTime:12},mute:x=>muting.push(x),phase:x=>phases.push(x),failure:x=>errors.push(x),retry:()=>{},...override});
 return{player,calls,phases,muting,errors,get audio(){return audio;}};
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
