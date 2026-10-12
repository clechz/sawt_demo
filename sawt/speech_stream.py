"""One continuous MP3 stream from 24 kHz signed little-endian PCM segments."""
import av


async def pcm_frames(first, stream, frame_bytes=960):
    """Yield 20 ms PCM frames before waiting for the rest of synthesis."""
    pending=bytearray(first)
    while True:
        while len(pending)>=frame_bytes:
            data=bytes(pending[:frame_bytes]);del pending[:frame_bytes]
            yield data
        try:pending.extend(await anext(stream))
        except StopAsyncIteration:break
    if len(pending)%2:raise ValueError('Truncated speech PCM sample')
    if pending:yield bytes(pending)


class SpeechEncoder:
    def __init__(self):
        self.codec=av.CodecContext.create('libmp3lame','w')
        self.codec.sample_rate=24000
        self.codec.layout='mono'
        self.codec.format='fltp'
        self.codec.bit_rate=64000
        self.resampler=av.AudioResampler(format='fltp',layout='mono',rate=24000)
        self.pending=bytearray()

    def feed(self, data):
        self.pending.extend(data)
        packets=[]
        # Include partial network chunks, including an odd split inside a sample.
        while len(self.pending)>=2400:
            chunk=bytes(self.pending[:2400]);del self.pending[:2400]
            packets.extend(self.frame(chunk))
        return packets

    def frame(self, data):
        frame=av.AudioFrame(format='s16',layout='mono',samples=len(data)//2)
        frame.sample_rate=24000
        frame.planes[0].update(data)
        return [bytes(packet) for f in self.resampler.resample(frame) for packet in self.codec.encode(f)]

    def finish(self):
        if len(self.pending)%2:raise ValueError('Truncated speech PCM sample')
        packets=self.frame(bytes(self.pending)) if self.pending else []
        self.pending.clear()
        packets.extend(bytes(packet) for f in self.resampler.resample(None) for packet in self.codec.encode(f))
        packets.extend(bytes(packet) for packet in self.codec.encode(None))
        return packets
