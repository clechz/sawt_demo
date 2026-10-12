"""Mute samples without detaching the LiveKit speech task from its output."""
import time
from livekit import rtc
from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities


class SpeechGate(AudioOutput):
    def __init__(self, sink, on_audible):
        super().__init__(label='SawtSpeechGate',capabilities=AudioOutputCapabilities(pause=False),next_in_chain=sink,sample_rate=sink.sample_rate)
        self.enabled=True
        self.on_audible=on_audible

    def set_enabled(self, enabled):
        if self.enabled and not enabled:
            self.clear_buffer()
        self.enabled=enabled

    async def capture_frame(self, frame):
        await super().capture_frame(frame)
        if not self.enabled:
            frame=rtc.AudioFrame(bytes(len(frame.data)*2),frame.sample_rate,frame.num_channels,frame.samples_per_channel)
        await self.next_in_chain.capture_frame(frame)
        if self.enabled and any(abs(v)>500 for v in frame.data):
            self.on_audible(time.monotonic())

    def flush(self):
        super().flush()
        self.next_in_chain.flush()

    def clear_buffer(self):
        self.next_in_chain.clear_buffer()
