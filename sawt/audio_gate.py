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
        self.resume_pending=False
        self.last_signal=0.0
        self.quiet_seconds=0.0

    def set_enabled(self, enabled, *, at_boundary=False):
        if self.enabled and not enabled:
            self.clear_buffer()
        # Do not expose the tail of a speculative phrase when the backend
        # finishes halfway through that phrase. Keep the same output attached
        # and resume at the next short silence. Explicit TTS can enable at once.
        self.resume_pending=bool(enabled and at_boundary and not self.enabled
            and time.monotonic()-self.last_signal<.12 and self.quiet_seconds<.12)
        if self.resume_pending:return
        self.enabled=enabled

    async def capture_frame(self, frame):
        await super().capture_frame(frame)
        rms = math.sqrt(sum(v*v for v in frame.data)/max(1,len(frame.data)))/32768
        if rms>.01:
            self.last_signal=time.monotonic()
            self.quiet_seconds=0.0
        else:
            self.quiet_seconds+=frame.samples_per_channel/frame.sample_rate
        if self.resume_pending and self.quiet_seconds>=.12:
            self.resume_pending=False
            self.enabled=True
        if not self.enabled:
            frame=rtc.AudioFrame(bytes(len(frame.data)*2),frame.sample_rate,frame.num_channels,frame.samples_per_channel)
            rms=0.0
        await self.next_in_chain.capture_frame(frame)
        # A single peak/click does not mean the caller heard a reply. Use the
        # same frame-level RMS threshold as the received-audio acceptance test.
        if self.enabled and rms > .01:
            self.on_audible(time.monotonic())

    def flush(self):
        super().flush()
        self.next_in_chain.flush()

    def clear_buffer(self):
        self.next_in_chain.clear_buffer()
