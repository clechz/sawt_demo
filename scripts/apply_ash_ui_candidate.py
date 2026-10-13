"""One-off candidate application; the validation job removes this after testing."""
from pathlib import Path
import re
r=Path('.')
def edit(path,old,new):
 p=r/path;s=p.read_text();assert old in s,path;p.write_text(s.replace(old,new))
p=r/'static/v2/experience-ui.js';s=p.read_text();a=s.index('export function createExperienceControls');b=s.index('const statusText=',a)
s=s[:a]+'''export const DEFAULT_VOICE = 'ash';
export function createExperienceControls(root){
 const consent=root.getElementById('experience-consent');
 return {
  value:()=>selectedExperience(DEFAULT_VOICE,'new_order',consent.checked),
  setBusy:busy=>{consent.disabled=busy;}
 };
}
'''+s[b:];p.write_text(s)
p=r/'static/v2/index.html';s=p.read_text();s=s.replace('<link rel="stylesheet" href="/assets/experience.css">','<link rel="stylesheet" href="/assets/experience.css"><link rel="stylesheet" href="/assets/simple-call.css">')
s=s.replace('<span class="brand-credit">تحدي عبدالله</span><span class="experience-badge">صوت ذكي · محاكاة</span>','')
s=s.replace('      <div class="call-state"><h1 id="call-phase">جاهزين لك</h1><time id="call-time" dir="ltr" aria-label="مدة المكالمة">0:00</time></div>\n','')
s=s.replace('    <p id="status"','    <div class="call-state"><span class="activity-dot" aria-hidden="true"></span><h1 id="call-phase">جاهزين لك</h1><time id="call-time" dir="ltr" aria-label="مدة المكالمة">0:00</time></div>\n    <p id="status"')
a=s.index('    <p id="worker-version"');b=s.index('    <div id="controls"',a)
s=s[:a]+'''    <div class="pre-call-note">
      <p class="simulation-disclosure">تجربة بالذكاء الاصطناعي، بدون طلبات حقيقية.</p>
      <label class="recording-consent"><input id="experience-consent" type="checkbox"> أوافق على تسجيل المكالمة للمراجعة.</label>
    </div>
'''+s[b:]
s=s.replace('    <section id="support-result" class="support-result" aria-label="متابعة الطلب والبلاغات" aria-live="polite" hidden></section>\n','')
s=s.replace('  <div id="basket"></div>','  <section id="support-result" class="support-result" aria-label="متابعة الطلب والبلاغات" aria-live="polite" hidden></section>\n  <div id="basket"></div>');p.write_text(s)
(r/'static/v2/simple-call.css').write_text('''/* Keep the orb purely visual during a call. Details live in the receipt. */
.brand{height:80px;gap:0}.brand img{width:86px}
.call-panel{min-height:calc(100svh - 112px)}
.call-state{position:static;inset:auto;display:none;min-height:30px;gap:10px;margin:0 0 22px;pointer-events:none}
body[data-phase]:not([data-phase=idle]):not([data-phase=ended]) .call-state{display:flex}
#call-phase{font-size:13px;line-height:1.7;color:var(--secondary);font-weight:400}
#call-time{position:static;top:auto;font-size:12px;padding-inline-start:10px;border-inline-start:1px solid var(--line)}
.activity-dot{width:5px;height:5px;border-radius:50%;background:var(--secondary);opacity:.65}
body[data-phase=processing] .activity-dot,body[data-phase=connecting] .activity-dot,body[data-phase=reconnecting] .activity-dot,body[data-phase=preparing] .activity-dot{animation:quiet-pulse 1.25s ease-in-out infinite}
@keyframes quiet-pulse{50%{opacity:.2;transform:scale(.7)}}
.pre-call-note{max-width:330px;text-align:center;margin:6px 0 0}
.simulation-disclosure{font-size:11px;line-height:1.8;color:var(--muted);margin:0 0 12px;opacity:1}
.recording-consent{font-size:12px;line-height:1.8;color:var(--secondary);gap:8px}
.recording-consent input{margin:0;width:16px;height:16px;flex:none;accent-color:#a48bd0}
body.active .pre-call-note{display:none}
.support-result{border:0;border-bottom:1px solid var(--line);border-radius:0;padding:0 0 16px;margin:0 0 8px}
#worker-version{display:none!important}
@media(max-height:650px){.brand{height:54px}.call-panel{min-height:calc(100svh - 86px)}.call-state{margin-bottom:14px}#call-phase{font-size:12px}}
@media(prefers-reduced-motion:reduce){.activity-dot{animation:none!important}}
''')
(r/'static/v2/microphone-control.js').write_text('''// Muting capture must not mute playback, cancel work, or stop the audio clock.
export function setMicrophoneCapture(participant,muted){
 const tracks=[...participant.audioTrackPublications.values()]
  .filter(p=>p.source==='microphone'&&p.track?.mediaStreamTrack)
  .map(p=>p.track.mediaStreamTrack);
 if(!tracks.length)throw new Error('الميكروفون غير جاهز. حاول مرة ثانية.');
 for(const track of tracks)track.enabled=!muted;
}
export async function syncMicrophoneMute(participant,callId,muted,sequence){
 await participant.publishData(new TextEncoder().encode(JSON.stringify({
  call_id:callId,muted,sequence
 })),{reliable:true,topic:'sawt-mic'});
}
''')
s=(r/'static/v2/app.js').read_text()
s="import {setMicrophoneCapture,syncMicrophoneMute} from './microphone-control.js';\n"+s
s=s.replace("let phase='idle',readbackMuted=false,workerVerified=false,workerReadyTimer;","let phase='idle',readbackMuted=false,workerVerified=false,workerReadyTimer,micSequence=0,micBusy=false;")
s=s.replace(" renderSupport(document,state.hospitality);"," renderSupport(document,state.hospitality);\n if(!$('support-result').hidden)$('order-button').hidden=false;")
s=s.replace(" workerVerified=false;clearTimeout(workerReadyTimer);"," workerVerified=false;clearTimeout(workerReadyTimer);micSequence=0;micBusy=false;muted=false;$('mute').disabled=false;",1)
s=s.replace("      const label=$('worker-version');if(label){label.hidden=false;label.textContent=`${binding.conversation_mode} · ${binding.voice} · ${binding.source_fingerprint.slice(0,8)}`;}","      // Keep build identity in diagnostics, not on the caller's main screen.\n      document.body.dataset.voice=binding.voice;")
s=s.replace("setPhase(workerVerified?'listening':'connecting');refresh();","setPhase(workerVerified?'listening':'connecting');void syncMicrophoneMute(activeRoom.localParticipant,call.id,muted,++micSequence).catch(()=>error('تعذر مزامنة الميكروفون. حالة الكتم المحلية محفوظة.'));refresh();")
a=s.index("$('mute').onclick=");b=s.index("$('retry-audio').onclick",a)
s=s[:a]+'''$('mute').onclick=async()=>{
 if(!room||closing||micBusy)return;
 const activeRoom=room,activeCall=call.id,next=!muted;
 micBusy=true;$('mute').disabled=true;
 try{
  // MediaStreamTrack.enabled=false supplies silence without stopping capture's
  // transport. Remote tracks, ReadbackPlayer and in-flight replies stay alone.
  setMicrophoneCapture(activeRoom.localParticipant,next);
  muted=next;
  ($('mute-label')||$('mute')).textContent=muted?'تشغيل الميكروفون':'كتم الميكروفون';
  $('mute').setAttribute('aria-pressed',String(muted));
  await syncMicrophoneMute(activeRoom.localParticipant,activeCall,muted,++micSequence);
 }catch(e){if(room===activeRoom&&!closing)error(e.message||'تعذر مزامنة الميكروفون. حالة الكتم المحلية محفوظة.');}
 finally{if(room===activeRoom&&!closing){micBusy=false;$('mute').disabled=false;}}
};
'''+s[b:];(r/'static/v2/app.js').write_text(s)
(r/'sawt/microphone.py').write_text('''"""Bridge caller-only microphone state to native GPT-Live input controls.

No output mute, response interruption, transaction mutation or mic audio logging.
Browser capture also supplies silence so a lost command never leaks muted speech.
"""
from __future__ import annotations
import json


class MicrophoneBridge:
    def __init__(self, sid, room, session, audit):
        self.sid, self.room, self.session, self.audit = sid, room, session, audit
        self.sequence = -1
        self.muted = False
        self.pending = {}
        self.bound = False

    def bind(self):
        self.room.on('data_received', self.on_packet)
        self.session.on('openai_client_event_queued', self.on_client_event)
        self.session.on('openai_server_event_received', self.on_server_event)
        self.bound = True

    def close(self):
        if not self.bound:
            return
        self.bound = False
        self.room.off('data_received', self.on_packet)
        self.session.off('openai_client_event_queued', self.on_client_event)
        self.session.off('openai_server_event_received', self.on_server_event)
        self.pending.clear()

    def on_packet(self, packet):
        if (getattr(packet, 'topic', None) != 'sawt-mic'
                or getattr(getattr(packet, 'participant', None), 'identity', None) != 'caller-' + self.sid):
            return
        try:
            if len(packet.data) > 512:
                return
            data = json.loads(packet.data)
            if (not isinstance(data, dict) or set(data) != {'call_id', 'muted', 'sequence'}
                    or data['call_id'] != self.sid or type(data['muted']) is not bool
                    or type(data['sequence']) is not int or not 0 <= data['sequence'] <= 1000000
                    or data['sequence'] <= self.sequence):
                return
            method = getattr(self.session, 'mute_input' if data['muted'] else 'unmute_input', None)
            if not callable(method):
                self.audit('voice.input_mute_unavailable', {})
                return
            self.sequence, self.muted = data['sequence'], data['muted']
            method()
            self.audit('voice.input_mute_requested', {'muted': self.muted, 'sequence': self.sequence})
        except (ValueError, TypeError, UnicodeError):
            return
        except Exception as exc:
            self.audit('voice.input_mute_failed', {'error_type': type(exc).__name__})

    def on_client_event(self, event):
        kind = event.get('type')
        if kind not in ('session.input_audio.mute', 'session.input_audio.unmute'):
            return
        key = event.get('event_id')
        if isinstance(key, str):
            if len(self.pending) >= 32:
                self.pending.pop(next(iter(self.pending)))
            self.pending[key] = {'muted': kind.endswith('.mute'), 'sequence': self.sequence}

    def on_server_event(self, event):
        kind = event.get('type')
        if kind not in ('session.input_audio.muted', 'session.input_audio.unmuted'):
            return
        pending = self.pending.pop(event.get('client_event_id'), None)
        if pending is not None:
            applied = kind.endswith('.muted')
            if applied == pending['muted']:
                self.audit('voice.input_mute_applied', pending)
''')
p=r/'sawt/hospitality_voice.py';s=p.read_text();needle='        async def announce_ready(self):'
assert needle in s
s=s.replace(needle,'''        async def on_enter(self):
            await super().on_enter()
            from .microphone import MicrophoneBridge
            self.microphone_bridge = MicrophoneBridge(self.sid, self.room, self.duplex_session, self.audit)
            self.microphone_bridge.bind()

        async def on_exit(self):
            bridge = getattr(self, 'microphone_bridge', None)
            if bridge is not None:
                bridge.close()
            await super().on_exit()

'''+needle);p.write_text(s)
edit('sawt/experience.py','"default_voice": "cedar"','"default_voice": "ash"')
edit('sawt/experience.py','("cedar" if version == "v3"','("ash" if version == "v3"')
edit('sawt/release_contract.py',"'sawt/choice_permissions.py', 'sawt/release_contract.py',","'sawt/choice_permissions.py', 'sawt/release_contract.py', 'sawt/microphone.py',")
edit('tests/test_hospitality.py',"if voice=='':assert validate_experience(voice)['voice']=='cedar'","if voice=='':assert validate_experience(voice)['voice']=='ash'")
for name in ('.github/workflows/tests.yml','.github/workflows/deploy-livekit.yml'):
 p=r/name;s=p.read_text();s=re.sub(r'node --experimental-default-type=module --test tests/playback.test.mjs[^\n]*','node --experimental-default-type=module --test tests/*.test.mjs',s);p.write_text(s)
p=r/'tests/call-start.test.mjs';s=p.read_text();s="import {setMicrophoneCapture,syncMicrophoneMute} from '../static/v2/microphone-control.js';\n"+s;s=s.replace('const sandbox={validateCallBinding','const sandbox={setMicrophoneCapture,syncMicrophoneMute,validateCallBinding');p.write_text(s)
p=r/'tests/experience.test.mjs';s=p.read_text();a=s.index("test('voice changes only");b=s.index("test('support view",a)
s=s[:a]+'''test('simple caller UI always uses Ash; consent remains explicit',()=>{
 const consent={checked:false,disabled:false};
 const root={getElementById:id=>id==='experience-consent'?consent:null};
 const controls=createExperienceControls(root);
 assert.equal(controls.value().voice,'ash');
 assert.equal(controls.value().scenario,'new_order');
 assert.equal(controls.value().recording_consent,false);
 consent.checked=true;controls.setBusy(true);
 assert.equal(consent.disabled,true);assert.equal(controls.value().recording_consent,true);
 controls.setBusy(false);assert.equal(consent.disabled,false);
});
'''+s[b:];p.write_text(s)
(r/'.github/workflows/ash-ui-source-review.yml').unlink()
