"""One-off integration of reviewed completion modules into current main's UI."""
from pathlib import Path
import re
r=Path('.')
p=r/'static/v2/playback.js';s=p.read_text().replace('setTimer=setTimeout, clearTimer=clearTimeout','setTimer=(fn,ms)=>globalThis.setTimeout(fn,ms), clearTimer=id=>globalThis.clearTimeout(id)');p.write_text(s)
p=r/'static/v2/microphone-mute.js';s=p.read_text();s+='''\n// This is a control packet, never an instruction in the conversation context.
export async function syncMicrophoneMute(participant,callId,muted,sequence){
 await participant.publishData(new TextEncoder().encode(JSON.stringify({call_id:callId,muted,sequence})),{reliable:true,topic:'sawt-mic'});
}
''';p.write_text(s)
p=r/'static/v2/app.js';s=p.read_text()
s=s.replace("import {setMicrophoneSilenced}","import {setMicrophoneSilenced,syncMicrophoneMute}")
s="import {createCompletionView} from './completion.js';\nimport {stopMediaNow,animateHangup,closeSavedCall} from './call-lifecycle.js';\n"+s
s=s.replace('const renderOrder=createOrderView();','const renderOrder=createOrderView();\nconst completion=createCompletionView(document);')
s=s.replace('workerVerified=false,workerReadyTimer;', 'workerVerified=false,workerReadyTimer,micSequence=0,micBusy=false;')
s=s.replace(" if(state.order_id&&workerVerified&&!closing&&phase!=='ending')setPhase('completed');",' completion.render(state);')
s=s.replace(" if(room)return;\n playbackMeter.prepare();", " if(room||$('start').disabled)return;\n completion.reset();$('new-call').hidden=true;$('call-ended-note').hidden=true;\n playbackMeter.prepare();")
s=s.replace(' workerVerified=false;clearTimeout(workerReadyTimer);'," workerVerified=false;clearTimeout(workerReadyTimer);micSequence=0;micBusy=false;muted=false;$('mute').disabled=false;$('end').disabled=false;",1)
s=s.replace("      document.body.dataset.workerRelease=binding.source_fingerprint.slice(0,8);","      document.body.dataset.workerRelease=binding.source_fingerprint.slice(0,8);document.body.dataset.voice=binding.voice;")
s=s.replace("setPhase(workerVerified?'listening':'connecting');refresh();","setPhase(workerVerified?'listening':'connecting');setMicrophoneSilenced(activeRoom,muted);void syncMicrophoneMute(activeRoom.localParticipant,call.id,muted,++micSequence).catch(()=>{});refresh();")
a=s.index('async function end(){');b=s.index("$('retry-audio').onclick",a)
s=s[:a]+'''async function end(){
 if(closing)return;closing=true;
 const endedRoom=room,endedCall=call;room=null;
 const hadMedia=!!endedRoom;
 clearTimeout(workerReadyTimer);workerVerified=false;
 clearInterval(poll);clearInterval(clockTimer);clearTimeout(timer);cancelAnimationFrame(frame);
 // No await before this: neither the API nor the animation can keep audio alive.
 void stopMediaNow(endedRoom,audioElements,player,fixture);
 for(const meter of [playbackMeter,microphoneMeter,...remoteMeters.values()]){try{meter.close();}catch{}}
 remoteMeters.clear();publishLevel(0);
 if(lab)$('send-fixture').disabled=true;
 $('mute').disabled=true;$('end').disabled=true;
 setPhase('ending');
 void closeSavedCall(endedCall,accessCode).then(data=>{
  if(data&&call?.id===endedCall?.id&&closing){render(data.state);showEndedReceipt();}
 }).catch(()=>{if(call?.id===endedCall?.id&&closing)error('انتهت المكالمة. تعذّر تحديث آخر حالة للطلب.');});
 if(hadMedia)await animateHangup(document);
 experienceControls.setBusy(false);
 $('controls').hidden=true;$('start').disabled=false;$('start-label').textContent='ابدأ المكالمة';document.body.classList.remove('active');setPhase('ended');
 muted=false;micBusy=false;($('mute-label')||$('mute')).textContent='كتم الميكروفون';$('mute').title='كتم ميكروفوني فقط';$('mute').setAttribute('aria-pressed','false');
 showEndedReceipt();
}
function showEndedReceipt(){
 if(!closing)return;
 const saved=completion.render(currentState);
 $('new-call').hidden=!saved;
 const note=$('call-ended-note');note.hidden=false;
 note.textContent=saved?'انتهت المكالمة':currentState?.basket?.length?'انتهت المكالمة · الطلب ما تأكد':'انتهت المكالمة';
}
$('start').onclick=start;$('new-call').onclick=start;$('end').onclick=end;
$('mute').onclick=async()=>{
 if(!room||closing||micBusy)return;
 const activeRoom=room,activeCall=call.id,next=!muted;micBusy=true;$('mute').disabled=true;
 try{
  setMicrophoneSilenced(activeRoom,next);muted=next;
  const label=muted?'تشغيل ميكروفوني':'كتم ميكروفوني';
  ($('mute-label')||$('mute')).textContent=label;$('mute').title=label;$('mute').setAttribute('aria-pressed',String(muted));
  await syncMicrophoneMute(activeRoom.localParticipant,activeCall,muted,++micSequence);
 }catch(e){if(room===activeRoom&&!closing)error(e.message||'تعذر مزامنة الميكروفون. حالة الكتم المحلية محفوظة.');}
 finally{if(room===activeRoom&&!closing){micBusy=false;$('mute').disabled=false;}}
};
'''+s[b:]
s=s.replace("window.addEventListener('pagehide',()=>{player.cancel();playbackMeter.close();microphoneMeter.close();room?.disconnect();});", "window.addEventListener('pagehide',()=>{void stopMediaNow(room,audioElements,player,fixture);try{playbackMeter.close();microphoneMeter.close();}catch{};});")
s=s.replace("room.on(LivekitClient.RoomEvent.TrackSubscribed,track=>{if(track.kind", "room.on(LivekitClient.RoomEvent.TrackSubscribed,track=>{if(room!==activeRoom||closing)return;if(track.kind")
p.write_text(s)
p=r/'static/v2/index.html';s=p.read_text().replace('<link rel="stylesheet" href="/assets/experience.css">','<link rel="stylesheet" href="/assets/experience.css"><link rel="stylesheet" href="/assets/completion.css">')
s=s.replace('    <p id="order-note"', '''    <p id="call-ended-note" class="call-ended-note" role="status" hidden></p>
    <section id="completion" class="completion-card" aria-labelledby="completion-title" aria-live="polite" hidden></section>
    <button id="new-call" class="secondary new-call" aria-describedby="recording-notice" hidden>مكالمة جديدة</button>
    <p id="order-note"''');p.write_text(s)
p=r/'tests/call-start.test.mjs';s=p.read_text().replace("import {setMicrophoneSilenced}","import {setMicrophoneSilenced,syncMicrophoneMute}")
s=s.replace("import vm from 'node:vm';", "import vm from 'node:vm';\nimport {stopMediaNow} from '../static/v2/call-lifecycle.js';")
s=s.replace("setMicrophoneEnabled:async()=>order.push('microphone')", "publishData:async()=>{},setMicrophoneEnabled:async()=>order.push('microphone')")
s=s.replace('const sandbox={validateCallBinding','const sandbox={createCompletionView:()=>({reset(){},render(){return false;}}),stopMediaNow,animateHangup:async()=>{},closeSavedCall:async()=>null,syncMicrophoneMute,validateCallBinding')
s=s.replace("element('mute').onclick();", "await element('mute').onclick();");p.write_text(s)
