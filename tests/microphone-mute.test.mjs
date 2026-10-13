import test from 'node:test';
import assert from 'node:assert/strict';
import {setMicrophoneSilenced} from '../static/v2/microphone-mute.js';

test('muting publishes silence without stopping voice audio or unpublishing microphone',()=>{
 const media={enabled:true,readyState:'live'};
 let changedSession=0;
 const room={localParticipant:{audioTrackPublications:new Map([['mic',{track:{mediaStreamTrack:media}}]]),setMicrophoneEnabled(){changedSession++;throw Error('Must never toggle publication');}}};
 const aiAudio={muted:false,paused:false};
 assert.equal(setMicrophoneSilenced(room,true),1);assert.equal(media.enabled,false);
 assert.equal(aiAudio.muted,false);assert.equal(aiAudio.paused,false);
 assert.equal(setMicrophoneSilenced(room,false),1);assert.equal(media.enabled,true);
 assert.equal(changedSession,0);
});
test('cannot silently claim mic mute if there is no live track',()=>{
 assert.throws(()=>setMicrophoneSilenced({localParticipant:{audioTrackPublications:new Map()}},true),/الميكروفون/);
 const dead={enabled:true,readyState:'ended'};
 assert.throws(()=>setMicrophoneSilenced({localParticipant:{audioTrackPublications:new Map([['dead',{track:{mediaStreamTrack:dead}}]])}},true));
 assert.equal(dead.enabled,true);
});
