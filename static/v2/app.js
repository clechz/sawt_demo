import {validateCallBinding,validateReadyBinding} from './worker-binding.js';
import {createExperienceControls, renderSupport} from './experience-ui.js';
import {ReadbackPlayer} from './playback.js';
import {PlaybackMeter,MicrophoneMeter} from './audio-meter.js';
import {createOrderView} from './order-view.js';
import {createCallStatus} from './call-status.js';
import {setMicrophoneSilenced} from './microphone-mute.js';
import {createCompletionView} from './completion.js';
import {stopMediaNow,animateHangup,closeSavedCall} from './call-lifecycle.js';
const $=id=>document.getElementById(id);
const renderOrder=createOrderView();
const completion=createCompletionView(document);
let call,room,poll,timer,clockTimer,frame,closing=false,muted=false,quoteSeen,accessCode='',refreshing=false,currentState;
const audioElements=new Set();
const playbackMeter=new PlaybackMeter();
const microphoneMeter=new MicrophoneMeter();
const remoteMeters=new Map();
let lastMeterTime=0;
let phase='idle',readbackMuted=false,workerVerified=false,workerReadyTimer;
const callStatus=createCallStatus((next,text)=>{phase=next;document.body.dataset.phase=next;$('call-phase').textContent=text;$('status').textContent=text;});
function setPhase(next){callStatus.phase(next);}
const error=text=>{$('error').textContent=text;$('error').hidden=!text;};
async function api(path,options={}){
 const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...(call?{Authorization:`Bearer ${call.token}`} : {}),'X-Access-Code':accessCode,...options.headers}});
 if(!response.ok){const body=await response.json().catch(()=>({detail:'تعذر الاتصال'}));const e=new Error(body.detail);e.status=response.status;e.code=body.code;throw e;}return response;
}
const player=new ReadbackPlayer({api,createAudio:()=>{const audio=new Audio();playbackMeter.attach(audio);return audio;},releaseAudio:()=>playbackMeter.detach(),mute:value=>{readbackMuted=value;audioElements.forEach(a=>a.muted=value||!workerVerified);},phase:setPhase,failure:error,retry:value=>{$('retry-audio').hidden=!value;}});
const experienceControls=createExperienceControls(document);
const lab=location.pathname==='/lab';let fixture,fixtureContext,fixtureDestination;
if(lab){const panel=document.createElement('section');panel.innerHTML='<p>Local test lab · synthetic file input, no microphone</p><label>Caller fixture <input id="fixture-file" type="file" accept="audio/*"></label><audio id="fixture-player" controls></audio><button id="send-fixture" class="secondary" disabled>Send synthetic speech</button>';document.querySelector('main').append(panel);fixture=$('fixture-player');$('send-fixture').onclick=()=>fixture.play();$('fixture-file').onchange=e=>{if(e.target.files[0]){if(fixture.src)URL.revokeObjectURL(fixture.src);fixture.src=URL.createObjectURL(e.target.files[0]);}};}
function render(state){
 currentState=state;
 renderOrder(state);
 renderSupport(document,state.hospitality,state.order_id);
 if(state.quote&&!state.quote.presented&&quoteSeen!==state.quote.token&&room&&workerVerified&&!closing){quoteSeen=state.quote.token;player.play(call.id);}
 if(!state.quote&&player.active){player.cancel();if(!closing)setPhase('processing');}
 completion.render(state);
}
async function refresh(){
 if(!call||closing||refreshing)return;
 const id=call.id;refreshing=true;
 try{const response=await api(`/api/calls/${id}?after=999999999`);const data=await response.json();if(call?.id!==id||closing)return;render(data.state);if(data.closed)await end();}
 catch(e){if(call?.id===id&&!closing)error('الاتصال متقطع. نحاول استعادة حالة طلبك.');}
 finally{refreshing=false;}
}
function publishLevel(level){level=Number.isFinite(level)?Math.sqrt(Math.max(0,Math.min((level-.008)/.65,1))):0;document.documentElement.style.setProperty('--level',String(1+level*.15));document.documentElement.style.setProperty('--voice-energy',String(level));window.dispatchEvent(new CustomEvent('sawt:audio-level',{detail:level}));}
function animate(time=0){if(!room)return;if(time-lastMeterTime>=25){const local=muted?0:Math.max(microphoneMeter.level(),room.localParticipant.audioLevel||0);let remote=0;if(!readbackMuted&&workerVerified){for(const meter of remoteMeters.values())remote=Math.max(remote,meter.level());for(const participant of room.remoteParticipants.values())remote=Math.max(remote,participant.audioLevel||0);}publishLevel(Math.max(local,remote,playbackMeter.level()));callStatus.audio(local,remote,muted,time);lastMeterTime=time;}frame=requestAnimationFrame(animate);}
async function start(){
 if(room||$('start').disabled)return;
 completion.reset();$('new-call').hidden=true;$('call-ended-note').hidden=true;
 playbackMeter.prepare();microphoneMeter.prepare();lastMeterTime=0;
 workerVerified=false;clearTimeout(workerReadyTimer);
 callStatus.reset();$('start').disabled=true;error('');setPhase('connecting');closing=false;quoteSeen=null;currentState=null;call=null;refreshing=false;
 $('order-button').hidden=true;$('order-note').textContent='';
 renderSupport(document,null);
 try{
  // Called by the start button or access-form submission, after the visible notice.
  const experience=experienceControls.value({startRequested:true});
  if(!experience.recording_consent)throw new Error('تعذر بدء المكالمة. حدّث الصفحة وحاول مرة ثانية.');
  experienceControls.setBusy(true);
  room=new LivekitClient.Room({adaptiveStream:true,dynacast:true});
  const activeRoom=room;
  // Unlock playback inside the click gesture, before network awaits. A blocked
  // speaker must not stop microphone publication or tear down the call.
  void room.startAudio().catch(()=>{$('retry-audio').hidden=false;});
  const response=await api('/api/calls',{method:'POST',body:JSON.stringify(experience)});call=await response.json();validateCallBinding(call,experience);localStorage.setItem('sawt-debug-call',JSON.stringify({id:call.id,token:call.token}));
  room.on(LivekitClient.RoomEvent.LocalTrackPublished,publication=>{if(publication.track?.kind==='audio')microphoneMeter.attachTrack(publication.track.mediaStreamTrack);});
  room.on(LivekitClient.RoomEvent.LocalTrackUnpublished,publication=>{if(publication.kind==='audio')microphoneMeter.detach();});
  room.on(LivekitClient.RoomEvent.TrackSubscribed,track=>{if(room!==activeRoom||closing)return;if(track.kind==='audio'){const meter=new MicrophoneMeter(()=>microphoneMeter.context);meter.prepare();meter.attachTrack(track.mediaStreamTrack);remoteMeters.set(track,meter);const element=track.attach();element.autoplay=true;element.muted=readbackMuted||!workerVerified;audioElements.add(element);$('media').append(element);element.play().catch(()=>{error('المتصفح منع الصوت. اضغط تشغيل الصوت.');$('retry-audio').hidden=false;});}});
  room.on(LivekitClient.RoomEvent.TrackUnsubscribed,track=>{remoteMeters.get(track)?.detach();remoteMeters.delete(track);for(const element of track.detach()){audioElements.delete(element);element.remove();}});
  room.on(LivekitClient.RoomEvent.DataReceived,(bytes,participant,kind,topic)=>{
   if(room!==activeRoom||closing||topic!=='sawt'||participant?.identity===room?.localParticipant.identity)return;
   try{const event=JSON.parse(new TextDecoder().decode(bytes));
    if(event.type==='ready'){
     try{const binding=validateReadyBinding(call,event);workerVerified=true;clearTimeout(workerReadyTimer);
      audioElements.forEach(a=>a.muted=readbackMuted);
      // Keep diagnostic identity machine-readable, not visible UI clutter.
      document.body.dataset.workerRelease=binding.source_fingerprint.slice(0,8);
      setPhase('listening');if(lab)$('send-fixture').disabled=false;
     }catch(e){error(e.message);void end();return;}
    }
    if(!workerVerified&&event.type!=='error')return;
    if(event.type==='processing'){error('');callStatus.progress(event);}
    if(event.type==='input')callStatus.interrupt(event);
    if(event.type==='waiting'&&callStatus.wait(event))player.cancel();
    if(event.type==='readback')refresh();
    if(event.type==='readback.cancelled'){player.cancel();setPhase('listening');}
    if(event.type==='updated'&&callStatus.updated(event)){player.cancel();error('');refresh();}
    if(event.type==='error'){error(event.message);if(event.fatal)end();else setPhase('paused');}
    if(event.type==='ended')end();
    if(event.type==='ending'){player.cancel();setPhase('ending');}
   }catch{}
  });
  room.on(LivekitClient.RoomEvent.Reconnecting,()=>{if(room!==activeRoom||closing)return;player.cancel();quoteSeen=null;setPhase('reconnecting');});
  room.on(LivekitClient.RoomEvent.Reconnected,()=>{if(room!==activeRoom||closing)return;setPhase(workerVerified?'listening':'connecting');refresh();});
  room.on(LivekitClient.RoomEvent.Disconnected,()=>{if(room===activeRoom&&!closing){error('انقطعت المكالمة. طلبك المحفوظ موجود في تفاصيل الطلب.');end();}});
  let connectTimeout;
  try{await Promise.race([room.connect(call.url,call.room_token),new Promise((_,reject)=>{connectTimeout=setTimeout(()=>reject(new Error('تعذر اتصال الصوت. جرّب Chrome أو Edge وتحقق من الشبكة.')),25000);})]);}finally{clearTimeout(connectTimeout);}
  void room.startAudio().catch(()=>{error('اضغط تشغيل الصوت عشان تسمع الرد.');$('retry-audio').hidden=false;});
  if(lab){if(!fixtureContext){fixtureContext=new AudioContext();fixtureDestination=fixtureContext.createMediaStreamDestination();fixtureContext.createMediaElementSource(fixture).connect(fixtureDestination);}await fixtureContext.resume();await room.localParticipant.publishTrack(fixtureDestination.stream.getAudioTracks()[0].clone(),{source:LivekitClient.Track.Source.Microphone});}
  else await room.localParticipant.setMicrophoneEnabled(true);
  if(closing||room!==activeRoom)return;
  if(!workerVerified)workerReadyTimer=setTimeout(()=>{if(room===activeRoom&&!closing&&!workerVerified){error('ما وصل تأكيد نسخة الوكيل الصوتي. انتهت المحاولة بدون بدء تجربة غير مؤكدة.');void end();}},25000);
  document.body.classList.add('active');$('start-label').textContent='المكالمة مستمرة';$('controls').hidden=false;$('access').hidden=true;
  const connectedAt=Date.now();const tick=()=>{const seconds=Math.floor((Date.now()-connectedAt)/1000);$('call-time').textContent=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;};tick();clockTimer=setInterval(tick,1000);
  poll=setInterval(refresh,800);timer=setTimeout(end,call.max_seconds*1000);animate();await refresh();
 }catch(e){const needsCode=e.status===401;await end();if(needsCode){$('access').hidden=false;$('status').textContent='أدخل رمز التجربة للبدء.';}else error(e.name==='NotAllowedError'?'نحتاج إذن الميكروفون للمكالمة. اسمح له من إعدادات المتصفح ثم حاول.':e.message);}
}
async function end(){
 if(lab)$('send-fixture').disabled=true;
 if(closing)return;closing=true;
 const endedRoom=room,endedCall=call;room=null;
 void stopMediaNow(endedRoom,audioElements,player,fixture);
 clearTimeout(workerReadyTimer);workerVerified=false;
 clearInterval(poll);clearInterval(clockTimer);clearTimeout(timer);cancelAnimationFrame(frame);player.cancel();fixture?.pause();
 playbackMeter.close();microphoneMeter.close();for(const meter of remoteMeters.values())meter.detach();remoteMeters.clear();publishLevel(0);
 setPhase('ending');$('mute').disabled=true;$('end').disabled=true;
 void closeSavedCall(endedCall,accessCode).then(data=>{
  if(data&&call?.id===endedCall?.id&&closing){render(data.state);showEndedReceipt();}
 }).catch(()=>{if(call?.id===endedCall?.id&&closing)error('انتهت المكالمة. تعذّر تحديث آخر حالة للطلب.');});
 if(endedRoom)await animateHangup(document);
 experienceControls.setBusy(false);
 $('controls').hidden=true;$('start').disabled=false;$('start-label').textContent='ابدأ المكالمة';document.body.classList.remove('active');setPhase('ended');
 muted=false;($('mute-label')||$('mute')).textContent='كتم الميكروفون';$('mute').title='كتم ميكروفوني فقط';$('mute').setAttribute('aria-pressed','false');
 $('mute').disabled=false;$('end').disabled=false;showEndedReceipt();
}
function showEndedReceipt(){
 if(!closing)return;
 const saved=completion.render(currentState);$('new-call').hidden=!saved;
 $('call-ended-note').hidden=false;
 $('call-ended-note').textContent=saved?'انتهت المكالمة':currentState?.basket?.length?'انتهت المكالمة · الطلب ما تأكد':'انتهت المكالمة';
}
$('start').onclick=start;$('new-call').onclick=start;$('end').onclick=end;
$('mute').onclick=()=>{if(!room||closing)return;const next=!muted;try{
 // Do not unpublish/stop the microphone: the AI must keep receiving a live silent track.
 setMicrophoneSilenced(room,next);muted=next;
 const label=muted?'تشغيل ميكروفوني':'كتم ميكروفوني';
 ($('mute-label')||$('mute')).textContent=label;$('mute').title=label;
 $('mute').setAttribute('aria-pressed',String(muted));
 error('');
 }catch(e){error(e.message||'تعذر تغيير الميكروفون. حاول مرة ثانية.');}};
$('retry-audio').onclick=()=>{error('');playbackMeter.prepare();microphoneMeter.prepare();for(const meter of remoteMeters.values())meter.prepare();for(const audio of audioElements)void audio.play().catch(()=>{});if(workerVerified&&currentState?.quote&&!currentState.quote.presented)player.play(call.id);else room?.startAudio().then(()=>$('retry-audio').hidden=true).catch(e=>error(e.message));};
$('order-button').onclick=()=>$('order').showModal();$('close-order').onclick=()=>$('order').close();
for(const dialog of [$('order')])dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)dialog.close();});
$('access').onsubmit=e=>{e.preventDefault();accessCode=$('code').value;start();};
window.addEventListener('pagehide',()=>{void stopMediaNow(room,audioElements,player,fixture);playbackMeter.close();microphoneMeter.close();});

// Recover only authenticated committed state; never reconnect media on reload.
async function restoreReceipt(){
 try{
  const saved=JSON.parse(localStorage.getItem('sawt-debug-call')||'null');
  if(!saved||!/^[a-f0-9]{32}$/.test(saved.id)||typeof saved.token!=='string')return;
  const response=await api(`/api/calls/${saved.id}?after=999999999`,{headers:{Authorization:`Bearer ${saved.token}`}});
  const data=await response.json();
  if(!room&&!call&&data.state?.order_id){closing=true;render(data.state);setPhase('ended');showEndedReceipt();}
 }catch{}
}
void restoreReceipt();
