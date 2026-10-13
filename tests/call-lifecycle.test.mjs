import test from 'node:test';
import assert from 'node:assert/strict';
import {stopMediaNow,animateHangup,closeSavedCall} from '../static/v2/call-lifecycle.js';

test('hangup disables and stops microphone and pauses received audio before async disconnect finishes',async()=>{
 const order=[];let resolveDisconnect;const mic={enabled:true,stop(){order.push('mic-stopped');}};
 const audio={muted:false,pause(){order.push('speaker-paused');},remove(){order.push('speaker-removed');}};const elements=new Set([audio]);
 const room={localParticipant:{audioTrackPublications:new Map([['m',{track:{mediaStreamTrack:mic}}]])},disconnect(){order.push('disconnect-started');return new Promise(r=>resolveDisconnect=r);}};
 const done=stopMediaNow(room,elements,{cancel(){order.push('readback-cancelled');}});
 assert.equal(mic.enabled,false);assert.equal(audio.muted,true);assert.equal(elements.size,0);
 assert.deepEqual(order,['mic-stopped','readback-cancelled','speaker-paused','speaker-removed','disconnect-started']);
 resolveDisconnect();await done;
});
test('visualization/player failures cannot keep speaker or microphone active',async()=>{
 const mic={enabled:true,stop(){throw Error('already stopped');}};let paused=false,disconnected=false;
 await stopMediaNow({localParticipant:{audioTrackPublications:new Map([['m',{track:{mediaStreamTrack:mic}}]])},disconnect(){disconnected=true;}},new Set([{pause(){paused=true;},remove(){}}]),{cancel(){throw Error('player');}});
 assert.equal(mic.enabled,false);assert.ok(paused&&disconnected);
});
test('reduced motion skips animation, and cancellation cannot block hangup',async()=>{
 const old=globalThis.matchMedia;let ran=false;
 try{
  globalThis.matchMedia=()=>({matches:true});await animateHangup({querySelector:()=>({animate(){ran=true;}})});assert.equal(ran,false);
  globalThis.matchMedia=()=>({matches:false});let cancelled=false;
  await animateHangup({querySelector:()=>({animate(){return {finished:Promise.reject(Error('cancelled')),cancel(){cancelled=true;}};}})});assert.equal(cancelled,true);
 }finally{globalThis.matchMedia=old;}
});
test('server closure uses the ended call credentials then retrieves the saved final state',async()=>{
 const requests=[];const response=await closeSavedCall({id:'old',token:'old-token'},'code',async(path,options)=>{requests.push([path,options]);return{ok:true,json:async()=>({closed:true,state:{order_id:'S-123'}})};});
 assert.equal(response.state.order_id,'S-123');assert.equal(requests[0][0],'/api/calls/old/end');assert.equal(requests[0][1].headers.Authorization,'Bearer old-token');assert.equal(requests[1][1].cache,'no-store');
});
test('failed closure is not reported as successful',async()=>{
 await assert.rejects(closeSavedCall({id:'a',token:'b'},'',async()=>({ok:false})));
});
