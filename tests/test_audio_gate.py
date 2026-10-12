import array
from livekit import rtc
from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities
from sawt.audio_gate import SpeechGate

class Sink(AudioOutput):
    def __init__(self):
        super().__init__(label='test',capabilities=AudioOutputCapabilities(pause=False),sample_rate=24000)
        self.frames=[];self.cleared=0
    async def capture_frame(self,frame):
        await super().capture_frame(frame)
        self.frames.append(frame.data.tobytes())
    def flush(self):
        super().flush()
        self.on_playback_finished(playback_position=.01,interrupted=False)
    def clear_buffer(self):
        self.cleared+=1

async def test_mute_then_resume_keeps_existing_output_destination_and_timing():
    sink=Sink();audible=[];gate=SpeechGate(sink,audible.append)
    pcm=array.array('h',[1000]*240).tobytes()
    frame=rtc.AudioFrame(pcm,24000,1,240)
    gate.set_enabled(False)
    await gate.capture_frame(frame)
    assert sink.frames==[bytes(len(pcm))] and not audible
    gate.set_enabled(True)
    await gate.capture_frame(frame)
    assert sink.frames[-1]==pcm and len(audible)==1
    assert sink.cleared==1
    gate.flush()
    finished=await gate.wait_for_playout()
    assert not finished.interrupted
