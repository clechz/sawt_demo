import test from 'node:test';
import assert from 'node:assert/strict';
import {ReadbackPlayer} from '../static/v2/playback.js';

test('default playback timers preserve native global receiver for cancellation and stall checks',async()=>{
 const originals={setTimeout:globalThis.setTimeout,clearTimeout:globalThis.clearTimeout};
 const observed=[];
 try{
  globalThis.setTimeout=function(fn,ms){assert.equal(this,globalThis);observed.push(['set',ms]);return 17;};
  globalThis.clearTimeout=function(id){assert.equal(this,globalThis);observed.push(['clear',id]);};
  const player=new ReadbackPlayer({api:async()=>({json:async()=>({receipt_id:'r',url:'synthetic'})}),
   createAudio:()=>({play:async()=>{},pause(){},removeAttribute(){},load(){}}),
   mute(){},phase(){},failure(e){throw Error(e);},retry(){}});
  player.cancel();await player.play('call');player.cancel();
  assert.ok(observed.some(([type,ms])=>type==='set'&&ms===10000));
  assert.ok(observed.some(([type,id])=>type==='clear'&&id===17));
 }finally{Object.assign(globalThis,originals);}
});
