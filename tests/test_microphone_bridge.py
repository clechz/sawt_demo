import json
from types import SimpleNamespace
import pytest
from sawt.microphone import MicrophoneBridge

class Emitter:
    def __init__(self): self.callbacks={}
    def on(self,event,fn): self.callbacks[event]=fn
    def off(self,event,fn): assert self.callbacks.pop(event)==fn

class Session(Emitter):
    def __init__(self): super().__init__();self.commands=[]
    def mute_input(self): self.commands.append('mute')
    def unmute_input(self): self.commands.append('unmute')

def setup():
    events=[];room=Emitter();session=Session()
    bridge=MicrophoneBridge('one',room,session,lambda k,p:events.append((k,p)))
    bridge.bind();return bridge,session,events

def packet(muted=True,sequence=1,identity='caller-one',**changes):
    data={'call_id':'one','muted':muted,'sequence':sequence,**changes}
    return SimpleNamespace(topic='sawt-mic',participant=SimpleNamespace(identity=identity),data=json.dumps(data).encode())

def test_mute_and_unmute_control_input_only():
    b,s,e=setup();b.on_packet(packet());b.on_packet(packet(False,2))
    assert s.commands==['mute','unmute'];assert b.muted is False
    assert [x[0] for x in e]==['voice.input_mute_requested']*2
    b.close();assert not s.callbacks and not b.room.callbacks

@pytest.mark.parametrize('p',[
    packet(identity='other'),packet(call_id='two'),packet(muted='true'),
    packet(sequence=True),packet(sequence=-1),packet(sequence=1000001),
    packet(unexpected='instruction'),
    SimpleNamespace(topic='other',participant=SimpleNamespace(identity='caller-one'),data=b'{}'),
    SimpleNamespace(topic='sawt-mic',participant=SimpleNamespace(identity='caller-one'),data=b'x'*513),
    SimpleNamespace(topic='sawt-mic',participant=SimpleNamespace(identity='caller-one'),data=b'not json')
])
def test_wrong_caller_or_malformed_controls_do_nothing(p):
    b,s,e=setup();b.on_packet(p);assert not s.commands and not e

def test_stale_or_duplicate_packet_cannot_revert_mute():
    b,s,e=setup();b.on_packet(packet(sequence=3));b.on_packet(packet(False,2));b.on_packet(packet(False,3))
    assert b.muted and s.commands==['mute']

def test_native_receipt_is_distinct_from_requested_state():
    b,s,e=setup();b.on_packet(packet())
    b.on_client_event({'type':'session.input_audio.mute','event_id':'x'})
    b.on_server_event({'type':'session.input_audio.muted','client_event_id':'unrelated'})
    assert len(e)==1
    b.on_server_event({'type':'session.input_audio.muted','client_event_id':'x'})
    assert e[-1]==('voice.input_mute_applied',{'muted':True,'sequence':1})

def test_rejected_mute_implementation_does_not_cancel_session():
    b,s,e=setup();s.mute_input=None;b.on_packet(packet())
    assert not s.commands;assert e[-1][0]=='voice.input_mute_unavailable'
