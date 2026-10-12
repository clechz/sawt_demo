import array
import io
import math
from pathlib import Path
import av
import pytest
from sawt.speech_stream import SpeechEncoder
from sawt.v2_provider import V2Provider


def tone(hz,seconds):
    return array.array('h',(int(6000*math.sin(2*math.pi*hz*i/24000)) for i in range(int(24000*seconds)))).tobytes()


def decode(data):
    with av.open(io.BytesIO(data)) as container:
        resampler=av.AudioResampler(format='s16',layout='mono',rate=24000)
        return b''.join(bytes(p.planes[0])[:p.samples*2] for frame in container.decode(audio=0) for p in resampler.resample(frame))


def test_one_stream_preserves_both_segments_across_odd_network_chunk_boundaries():
    encoder=SpeechEncoder();encoded=[]
    pcm=tone(440,.5)+tone(880,.5)
    for start in range(0,len(pcm),733):encoded.extend(encoder.feed(pcm[start:start+733]))
    encoded.extend(encoder.finish())
    samples=array.array('h',decode(b''.join(encoded)))
    assert .99<=len(samples)/24000<=1.1
    def crossings(part):return sum(a<=0<b or b<=0<a for a,b in zip(part,part[1:]))
    # Both sides must decode, with the distinct tail still audible.
    assert 200<crossings(samples[2400:9600])<330
    assert 400<crossings(samples[15600:22800])<620


async def test_checkout_separates_body_and_includes_verified_confirmation_asset(monkeypatch):
    monkeypatch.setattr('sawt.v2_provider.voice_name',lambda:'marin')
    requests=[]
    async def chunks(self,text,response_format='mp3'):
        requests.append((text,response_format))
        yield tone(440,.5)
    monkeypatch.setattr(V2Provider,'speech_chunks',chunks)
    audio=await V2Provider().speak('المجموع 18 ريال. نأكد الطلب؟')
    tail=(Path(__file__).resolve().parents[1]/'data/voice/confirmation-marin.pcm').read_bytes()
    assert requests==[('المجموع 18 ريال.','pcm')]
    assert len(decode(audio))/48000>=.5+len(tail)/48000


def test_incomplete_pcm_cannot_silently_finish_a_playback_receipt():
    encoder=SpeechEncoder();encoder.feed(b'\0')
    with pytest.raises(ValueError):encoder.finish()
