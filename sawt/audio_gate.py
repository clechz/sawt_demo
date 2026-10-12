"""Mute samples without detaching the LiveKit speech task from its output."""
import time
import math
from contextvars import ContextVar
from livekit import rtc
from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities

_playback_source = ContextVar('sawt_playback_source', default=None)


class SpeechGate(AudioOutput):
    def __init__(self, sink, on_audible):
        super().__init__(label='SawtSpeechGate',capabilities=AudioOutputCapabilities(pause=False),next_in_chain=sink,sample_rate=sink.sample_rate)
        self.enabled=True
        self.on_audible=on_audible
        self.resume_pending=False
        self.last_signal=0.0
        self.quiet_seconds=0.0
        self.audible_seconds=0.0
        self.model_allowed=True
        self.playback_permit=None

    def allow_model(self, allowed):
        self.model_allowed=allowed
        if not allowed:self.clear_buffer()

    def begin_playback(self):
        self.playback_permit=object()
        return self.playback_permit

    def bind_playback(self, permit):
        # LiveKit forwards/resamples each yielded frame in this same task.
        # Task-local provenance survives resampling; a parallel model task
        # cannot inherit permission created inside the explicit frame iterator.
        _playback_source.set(permit)

    def end_playback(self, permit):
        if self.playback_permit is permit:self.playback_permit=None

    def set_enabled(self, enabled, *, at_boundary=False):
        if not enabled:self.playback_permit=None
        if not enabled or at_boundary or not self.enabled:
            self.audible_seconds=0.0
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
            if self.quiet_seconds>=.12:
                self.audible_seconds=0.0
        if self.resume_pending and self.quiet_seconds>=.12:
            self.resume_pending=False
            self.enabled=True
        permitted=self.model_allowed or (self.playback_permit is not None and _playback_source.get() is self.playback_permit)
        if not self.enabled or not permitted:
            frame=rtc.AudioFrame(bytes(len(frame.data)*2),frame.sample_rate,frame.num_channels,frame.samples_per_channel)
            rms=0.0
        await self.next_in_chain.capture_frame(frame)
        # A short residual frame does not establish a spoken reply. Require
        # sustained signal before suppressing the missing-reply fallback.
        # This still measures outgoing audio, not a receiver playback receipt.
        if self.enabled and rms > .01:
            self.audible_seconds+=frame.samples_per_channel/frame.sample_rate
            if self.audible_seconds>=.075:
                self.on_audible(time.monotonic())

    def flush(self):
        super().flush()
        self.next_in_chain.flush()

    def clear_buffer(self):
        self.next_in_chain.clear_buffer()
