from types import SimpleNamespace
from sawt.hospitality_voice import make_voice_class,context_chunks

class Gate:
 def __init__(self):self.calls=[]
 def set_enabled(self,v):self.calls.append(v)
class Base:
 def __init__(self,sid,room,**kw):self.kw=kw;self.ending=False;self.audio_gate=Gate();self.events=[]
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
