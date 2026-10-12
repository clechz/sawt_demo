"""Mute samples without detaching the LiveKit speech task from its output."""
import time
import math
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
        # A single peak/click does not mean the caller heard a reply. Use the
        # same frame-level RMS threshold as the received-audio acceptance test.
        rms = math.sqrt(sum(v*v for v in frame.data)/max(1,len(frame.data)))/32768
        if self.enabled and rms > .01:
            self.on_audible(time.monotonic())

    def flush(self):
        super().flush()
        self.next_in_chain.flush()

    def clear_buffer(self):
        self.next_in_chain.clear_buffer()
