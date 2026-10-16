from types import SimpleNamespace
from sawt.hospitality_voice import make_voice_class,context_chunks

class Gate:
 def __init__(self):self.calls=[]
 def set_enabled(self,v):self.calls.append(v)
class Base:
 def __init__(self,sid,room,**kw):self.kw=kw;self.ending=False;self.audio_gate=Gate();self.events=[]
 def spawn(self,coro):
  coro.close();return None
 def audit(self,*a):self.events.append(a)
 def on_provider_event(self,event):self.events.append(event)

def test_caption_final_is_not_forced_backend_or_blanket_mute():
 voice=make_voice_class(Base)('id',None,{'voice':'cedar'})
 voice.on_transcript(SimpleNamespace(item_id='1',is_final=True,transcript='هلا والله كيفك'))
 assert voice.audio_gate.calls==[]
 assert voice.current_item=='1'

def test_new_input_revokes_explicit_playback_but_not_normal_live_speech():
 voice=make_voice_class(Base)('id',None,{'voice':'ash'})
 voice.on_provider_event({'type':'session.input_transcript.delta','delta':'اه'})
 assert voice.audio_gate.calls==[]
 voice.explicit_playing=True
 voice.on_provider_event({'type':'session.input_transcript.delta','delta':'لا لحظة'})
 assert voice.audio_gate.calls==[False] and voice.playback_interrupted
 assert voice.input_generation==2

def test_context_splitting_never_silently_loses_arabic_facts():
 text=' '.join(['التوصيل إلى حي النرجس والمجموع ثلاثون ريال']*50)
 chunks=list(context_chunks(text))
 assert ' '.join(chunks)==text
 assert all(len(chunk.encode())<=460 for chunk in chunks)


import pytest
@pytest.mark.asyncio
async def test_support_answer_dispatches_without_native_event():
 import asyncio
 class PendingBase(Base):
  def __init__(self,*a,**k):
   super().__init__(*a,**k);self.fragments=['لا شكرا'];self.consumed=0;self.pending=None;self.dispatched=[]
  def spawn(self,coro):return asyncio.create_task(coro)
  def on_delegation(self,d):self.dispatched.append(d)
 voice=make_voice_class(PendingBase)('id',None,{'voice':'cedar'})
 voice.awaiting_resolution=True
 voice.on_transcript(SimpleNamespace(item_id='1',is_final=True,transcript='لا شكرا'))
 await voice.resolution_dispatch
 assert len(voice.dispatched)==1
 voice.consumed=1
 await voice.dispatch_resolution_reply()
 assert len(voice.dispatched)==1


@pytest.mark.asyncio
async def test_exhausted_private_replans_resume_unconsumed_request_only():
 import asyncio, time
 class PendingBase(Base):
  def __init__(self,*a,**k):
   super().__init__(*a,**k);self.fragments=['أبي شاورما',' صاج',' بدون حار'];self.consumed=0;self.pending=None;self.dispatched=[];self.last_input=time.monotonic()-1
  def on_delegation(self,d):self.dispatched.append(d)
 voice=make_voice_class(PendingBase)('id',None,{'voice':'cedar'})
 voice.pending=asyncio.create_task(asyncio.sleep(.01))
 await voice.resume_delegated_request()
 assert len(voice.dispatched)==1 and voice.delegation_start==0
 voice.consumed=len(voice.fragments)
 await voice.resume_delegated_request()
 assert len(voice.dispatched)==1
 voice.consumed=0;voice.ending=True
 await voice.resume_delegated_request()
 assert len(voice.dispatched)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('blocked', ['none','business_ack','speech','input','pending','waiting','reading','checkout','consumed','ending'])
async def test_silent_recovery_only_delegates_unhandled_quiet_input(blocked, monkeypatch):
 import time
 from unittest.mock import AsyncMock
 monkeypatch.setattr('sawt.hospitality_voice.asyncio.sleep', AsyncMock())
 class RecoveryBase(Base):
  def __init__(self,*a,**k):
   super().__init__(*a,**k)
   self.fragments=['أبي شاي'];self.consumed=0;self.pending=None;self.dispatched=[]
   self.last_input=time.monotonic()-4;self.waiting=False;self.reading=False;self.checkout_context=None
  def on_delegation(self,d):self.dispatched.append(d)
 voice=make_voice_class(RecoveryBase)('id',None,{'voice':'cedar'})
 if blocked=='business_ack':voice.last_native_output=time.monotonic()
 if blocked=='speech':
  voice.last_native_output=time.monotonic();voice.fragments=['هلا']
 if blocked=='input':voice.input_generation=1
 if blocked=='pending':voice.pending=SimpleNamespace(done=lambda:False)
 if blocked=='waiting':voice.waiting=True
 if blocked=='reading':voice.reading=True
 if blocked=='checkout':voice.checkout_context={'token':'pending'}
 if blocked=='consumed':voice.consumed=1
 if blocked=='ending':voice.ending=True
 await voice.recover_silent_request(0)
 assert len(voice.dispatched)==(1 if blocked in ('none','business_ack') else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize('text,delay',[
 ('انهي المكالمة لو سمحت',.6),('انتظر شوي لو سمحت',.6),('تسمعني',.6),
 ('لا تقفل المكالمة خليها مفتوحة',3),('أبي شاورما وبعدين اقفل المكالمة',3),
])
async def test_complete_controls_dispatch_early_without_bypassing_guards(text,delay,monkeypatch):
 import time
 from unittest.mock import AsyncMock
 sleep=AsyncMock();monkeypatch.setattr('sawt.hospitality_voice.asyncio.sleep',sleep)
 class ControlBase(Base):
  def __init__(self,*a,**k):
   super().__init__(*a,**k)
   self.fragments=[text];self.consumed=0;self.pending=None;self.dispatched=[]
   self.last_input=time.monotonic()-4;self.waiting=False;self.reading=False;self.checkout_context=None
  def on_delegation(self,d):self.dispatched.append(d)
 voice=make_voice_class(ControlBase)('id',None,{'voice':'cedar'})
 await voice.recover_silent_request(0)
 sleep.assert_awaited_with(delay)
 assert len(voice.dispatched)==1
 voice.input_generation=1
 await voice.recover_silent_request(0)
 assert len(voice.dispatched)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('interrupted', [False, True])
async def test_confirmed_close_preserves_order_and_yields_to_new_speech(interrupted, monkeypatch, tmp_path):
 from unittest.mock import AsyncMock
 import sawt.v2_runtime as runtime
 from sawt.transactions import Transactions
 tx=Transactions(tmp_path/'calls.db',runtime.engine);sid,_=tx.create()
 import json
 row=tx.load(sid);row['state']['order_id']='S-TEST'
 with tx.connect() as db:db.execute('UPDATE calls SET state=? WHERE id=?',(json.dumps(row['state']),sid))
 monkeypatch.setattr(runtime,'tx',tx)
 monkeypatch.setattr('sawt.hospitality_voice.asyncio.sleep',AsyncMock())
 room=SimpleNamespace(disconnect=AsyncMock())
 voice=make_voice_class(Base)(sid,room,{'voice':'cedar'})
 voice.sid=sid;voice.room=room
 voice.session=SimpleNamespace(aclose=AsyncMock());voice.send=AsyncMock()
 if interrupted:voice.input_generation=1
 await voice.finish_confirmed_call('S-TEST',0)
 saved=tx.load(sid)
 assert bool(saved['closed']) is (not interrupted)
 assert saved['state']['order_id']=='S-TEST'
 assert voice.session.aclose.await_count==(0 if interrupted else 1)
