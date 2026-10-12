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


async def test_single_click_or_background_noise_cannot_suppress_missing_reply_recovery():
    sink=Sink();audible=[];gate=SpeechGate(sink,audible.append)
    for samples in ([100]*240, [20000]+[0]*239, [1000]*240):
        await gate.capture_frame(rtc.AudioFrame(array.array('h',samples).tobytes(),24000,1,240))
    assert not audible

async def test_mute_then_resume_keeps_existing_output_destination_and_timing():
    sink=Sink();audible=[];gate=SpeechGate(sink,audible.append)
    pcm=array.array('h',[1000]*240).tobytes()
    frame=rtc.AudioFrame(pcm,24000,1,240)
    gate.set_enabled(False)
    await gate.capture_frame(frame)
    assert sink.frames==[bytes(len(pcm))] and not audible
    gate.set_enabled(True)
    for _ in range(8):await gate.capture_frame(frame)
    assert sink.frames[-1]==pcm and len(audible)==1
    assert sink.cleared==1
    gate.flush()
    finished=await gate.wait_for_playout()
    assert not finished.interrupted


async def test_backend_result_does_not_unmute_tail_of_speculative_speech():
    sink=Sink();audible=[];gate=SpeechGate(sink,audible.append)
    pcm=array.array('h',[1000]*240).tobytes()
    frame=rtc.AudioFrame(pcm,24000,1,240)
    quiet=rtc.AudioFrame(bytes(len(pcm)),24000,1,240)
    gate.set_enabled(False)
    await gate.capture_frame(frame)
    gate.set_enabled(True,at_boundary=True)
    for _ in range(3):await gate.capture_frame(frame)
    assert not audible and all(not any(data) for data in sink.frames)
    for _ in range(13):await gate.capture_frame(quiet)
    for _ in range(8):await gate.capture_frame(frame)
    assert sink.frames[-1]==pcm and len(audible)==1


async def test_new_pause_cancels_pending_resume_and_explicit_recovery_can_override_it():
    sink=Sink();audible=[];gate=SpeechGate(sink,audible.append)
    frame=rtc.AudioFrame(array.array('h',[1000]*240).tobytes(),24000,1,240)
    gate.set_enabled(False);await gate.capture_frame(frame)
    gate.set_enabled(True,at_boundary=True)
    assert gate.resume_pending
    gate.set_enabled(False)
    for _ in range(13):await gate.capture_frame(rtc.AudioFrame(bytes(480),24000,1,240))
    await gate.capture_frame(frame)
    assert not audible and not gate.enabled
    gate.set_enabled(True)
    for _ in range(8):await gate.capture_frame(frame)
    assert len(audible)==1


async def test_new_reply_cannot_reuse_previous_turns_audible_duration():
    sink=Sink();audible=[];gate=SpeechGate(sink,audible.append)
    frame=rtc.AudioFrame(array.array('h',[1000]*240).tobytes(),24000,1,240)
    for _ in range(8):await gate.capture_frame(frame)
    assert len(audible)==1
    gate.set_enabled(True,at_boundary=True)
    await gate.capture_frame(frame)
    assert len(audible)==1
