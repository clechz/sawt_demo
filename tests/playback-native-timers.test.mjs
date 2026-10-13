import test from 'node:test';
import assert from 'node:assert/strict';
import {ReadbackPlayer} from '../static/v2/playback.js';
test('native timer callbacks retain the global receiver',async()=>{
 const old=globalThis.clearTimeout;let called=false;
 try{globalThis.clearTimeout=function(){assert.equal(this,globalThis);called=true;};
 const p=new ReadbackPlayer({api(){},mute(){},phase(){},failure(){},retry(){}});p.cancel();assert.ok(called);
 }finally{globalThis.clearTimeout=old;}
});
