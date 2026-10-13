import test from 'node:test';
import assert from 'node:assert/strict';
import {createCallStatus} from '../static/v2/call-status.js';
test('quiet progress never exposes individual tool or reasoning stages',()=>{
 const updates=[];const s=createCallStatus((...x)=>updates.push(x));
 s.phase('listening');s.progress({stage:'search_menu',epoch:3});
 assert.deepEqual(updates.at(-1),['processing','جاري الرد']);
 s.interrupt({epoch:4});s.progress({stage:'saving',epoch:3});
 assert.deepEqual(updates.at(-1),['listening','نسمعك']);
});
test('audio activity cannot replace checkout or saving status',()=>{
 const updates=[];const s=createCallStatus((...x)=>updates.push(x));
 for(const phase of ['preparing','readback','confirm','reconnecting','completed']){
  s.phase(phase);const last=updates.at(-1);s.audio(.5,.3,false,2000);assert.equal(updates.at(-1),last);
 }
 s.reset();s.progress({stage:'saving',epoch:1});s.audio(.5,.3,false,2000);
 assert.deepEqual(updates.at(-1),['processing','جاري الرد']);
});
test('audible activity has a quiet hold and mute indication',()=>{
 const updates=[];const s=createCallStatus((...x)=>updates.push(x));s.phase('listening');
 s.audio(.5,0,false,1000);assert.equal(updates.at(-1)[1],'نسمعك');
 s.audio(0,0,false,1200);assert.equal(updates.at(-1)[1],'نسمعك');
 s.audio(0,0,true,2000);assert.equal(updates.at(-1)[1],'الميكروفون مكتوم');
 s.audio(0,.5,true,2100);assert.equal(updates.at(-1)[1],'صوت يتكلم');
});
test('closing cannot be overwritten by delayed progress or audio',()=>{
 const updates=[];const s=createCallStatus((...x)=>updates.push(x));s.phase('ending');
 const closing=updates.at(-1);s.progress({stage:'saving',epoch:9});s.updated({epoch:10});s.wait({epoch:11});s.audio(.8,.8,false,2000);
 assert.equal(updates.at(-1),closing);assert.deepEqual(closing,['ending','مع السلامة']);
});
test('waiting survives audio and delayed work, and new speech resumes it',()=>{
 const updates=[];const s=createCallStatus((...x)=>updates.push(x));s.phase('listening');
 assert.equal(s.wait({epoch:5}),true);
 const waiting=updates.at(-1);assert.deepEqual(waiting,['waiting','بانتظارك']);
 s.audio(.5,.5,false,2000);
 assert.equal(s.progress({stage:'saving',epoch:4}),false);
 assert.equal(s.progress({stage:'saving',epoch:5}),false);
 assert.equal(s.updated({epoch:4}),false);
 assert.equal(s.interrupt({epoch:5}),false);
 assert.equal(updates.at(-1),waiting);
 s.interrupt({epoch:6});assert.deepEqual(updates.at(-1),['listening','نسمعك']);
 assert.equal(s.wait({epoch:5}),false);
 s.progress({epoch:6,stage:'search_menu'});assert.equal(s.updated({epoch:6}),true);
 assert.deepEqual(updates.at(-1),['listening','معك']);
 s.phase('ended');assert.equal(s.wait({epoch:7}),false);
});
