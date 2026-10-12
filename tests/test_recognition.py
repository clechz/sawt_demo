import asyncio
import base64
import io
import wave
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
import voice_worker
from sawt.recognition import AudioWindow, AudioWindowError, check_recognition
from sawt.voice_routing import route_transcript


def test_audio_window_preserves_exact_pcm_and_timing():
    audio=AudioWindow(seconds=3)
    pcm=b'\x01\x02'*24000*2
    audio.append(base64.b64encode(pcm).decode())
    wav,span=audio.wav([{'start_ms':500,'end_ms':1000}])
    assert span=={'start_ms':0,'end_ms':1450}
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate()==24000 and w.getnchannels()==1
        assert w.readframes(w.getnframes())==pcm[:1450*48]


def test_expired_or_invalid_audio_never_falls_back_to_a_caption():
    audio=AudioWindow(seconds=1)
    audio.append(base64.b64encode(b'\x01\x00'*24000*3).decode())
    assert len(audio.data)==48000 and audio.duration_ms==3000
    for spans in [[],[{'start_ms':None,'end_ms':200}], [{'start_ms':0,'end_ms':200}],
                  [{'start_ms':5000,'end_ms':5100}], [{'start_ms':2500,'end_ms':2400}]]:
        with pytest.raises(AudioWindowError):audio.wav(spans)

def test_provider_clock_ahead_after_stall_uses_captured_pcm_anchor():
    audio=AudioWindow()
    audio.append(base64.b64encode(b'\x01\x00'*24000*30).decode())
    wav,span=audio.wav([{'start_ms':31200,'end_ms':31400,'captured_ms':27800},
                        {'start_ms':32400,'end_ms':32600,'captured_ms':28800}])
    assert span=={'start_ms':26200,'end_ms':29250}
    assert len(wav)>24000

def test_caption_burst_invalidates_once_but_new_work_can_be_superseded(monkeypatch):
    interrupt=Mock(return_value=2)
    monkeypatch.setattr(voice_worker.tx,'interrupt',interrupt)
    monkeypatch.setattr(voice_worker.tx,'load',Mock(return_value={'state':{'quote':None}}))
    voice=SimpleNamespace(sid='s',provider_failed=False,ending=False,last_input=0,
        fragments=[],fragment_spans=[],input_audio=SimpleNamespace(duration_ms=1000),
        audit=Mock(),input_invalidated=False,send=AsyncMock(),reading=False,
        spawn=lambda coroutine:coroutine.close())
    event={'type':'session.input_transcript.delta','delta':'أبي','start_ms':100,'end_ms':300}
    voice_worker.RestaurantVoice.on_provider_event(voice,event)
    voice_worker.RestaurantVoice.on_provider_event(voice,event)
    assert interrupt.call_count==1 and len(voice.fragments)==2
    voice.input_invalidated=False  # verification starts a new work boundary
    voice_worker.RestaurantVoice.on_provider_event(voice,event)
    assert interrupt.call_count==2


def test_pause_and_audio_complaint_have_opposite_routes():
    assert route_transcript('يا حبيبي تراك ما قاعد تتكلم. هلا، خلاص.')=='recover'
    assert route_transcript('يا حبيبي، ما قاعد أتكلم')=='wait'
    assert route_transcript('أنت ما قاعد تتكلم')=='recover'
    for text in ['لا تسكت', 'اكتب في الملاحظات ما أسمعك', 'ما أسمعك وأبي شاورما', 'لا تقفل المكالمة']:
        assert route_transcript(text)=='backend'


@pytest.mark.parametrize('caption,verified',[
    ('كم سندويش شاورما؟','سندويش شاورما'),
    ('لا تقفل المكالمة','قفل المكالمة'),
    ('بدون صوص','مع صوص'),
    ('أبي اثنين شاورما','أبي ثلاثة شاورما'),
    ('أبي ثلاث شاورما','أبي شاورما')])
def test_meaningful_disagreement_requires_clarification(caption,verified):
    with pytest.raises(AudioWindowError):check_recognition(caption,verified)


def test_spelling_and_digit_style_do_not_cause_a_false_disagreement():
    check_recognition('بكم سندوتش شاورما','بكم سندويتش الشاورما؟')
    check_recognition('اثنين شاورما','2 شاورما')
    check_recognition('ما قاعد أتكلم','أنت ما قاعد تتكلم')


def work_voice(verified):
    return SimpleNamespace(sid='s',last_input=0,fragments=['ما قاعد أتكلم'],consumed=0,current_item='i',processed='',
        checkout_context=False,reading=False,waiting=False,output_held=True,session=Mock(),duplex_session=Mock(),
        send=AsyncMock(),verify_transcript=AsyncMock(return_value=verified),recover_audio=AsyncMock(),wait_requested=AsyncMock(),
        end_requested=AsyncMock(),clarify_recognition=AsyncMock(),audit=Mock())


def test_corrected_audio_controls_routing_instead_of_wrong_live_caption(monkeypatch):
    monkeypatch.setattr(voice_worker.tx,'load',Mock(return_value={'epoch':1}))
    backend=AsyncMock();monkeypatch.setattr(voice_worker,'delegate',backend)
    voice=work_voice('يا حبيبي تراك ما قاعد تتكلم')
    asyncio.run(voice_worker.RestaurantVoice.work(voice,None))
    voice.recover_audio.assert_awaited_once_with(1)
    voice.wait_requested.assert_not_awaited();backend.assert_not_awaited()


@pytest.mark.parametrize('failure',[AudioWindowError('missing'),TimeoutError(),voice_worker.ProviderError('unavailable')])
def test_unverified_words_cannot_trigger_an_order_or_call_control(monkeypatch,failure):
    monkeypatch.setattr(voice_worker.tx,'load',Mock(return_value={'epoch':1}))
    backend=AsyncMock();monkeypatch.setattr(voice_worker,'delegate',backend)
    voice=work_voice('');voice.verify_transcript.side_effect=failure
    asyncio.run(voice_worker.RestaurantVoice.work(voice,None))
    voice.clarify_recognition.assert_awaited_once_with(1,1)
    voice.wait_requested.assert_not_awaited();voice.end_requested.assert_not_awaited();backend.assert_not_awaited()


def test_empty_verified_audio_never_replays_hallucinated_order(monkeypatch):
    monkeypatch.setattr(voice_worker.tx,'load',Mock(return_value={'epoch':1,'state':{'quote':None}}))
    backend=AsyncMock();monkeypatch.setattr(voice_worker,'delegate',backend)
    voice=work_voice('');voice.fragments=['أبي ثلاثة شاورما']
    asyncio.run(voice_worker.RestaurantVoice.work(voice,None))
    assert voice.consumed==1
    backend.assert_not_awaited();voice.wait_requested.assert_not_awaited()


def test_noise_cannot_release_explicit_wait_or_leave_canceled_readback_muted(monkeypatch):
    monkeypatch.setattr(voice_worker.tx,'load',Mock(return_value={'epoch':1,'state':{'quote':None}}))
    for waiting in (True,False):
        voice=work_voice('');voice.waiting=waiting;voice.reading=True;voice.checkout_context=True
        asyncio.run(voice_worker.RestaurantVoice.work(voice,None))
        voice.session.output.set_audio_enabled.assert_called_with(not waiting)
        voice.send.assert_awaited_with('waiting' if waiting else 'updated',epoch=1)


def test_new_speech_during_verification_invalidates_its_result(monkeypatch):
    monkeypatch.setattr(voice_worker.tx,'load',Mock(return_value={'epoch':2,'closed':False}))
    voice=SimpleNamespace(sid='s',fragments=['نعم','لا'],fragment_spans=[{},{}],input_audio=Mock(),send=AsyncMock(),audit=Mock(),provider=SimpleNamespace(recognize=AsyncMock(return_value='نعم')))
    voice.input_audio.wav.return_value=(b'wav',{})
    with pytest.raises(voice_worker.Conflict):
        asyncio.run(voice_worker.RestaurantVoice.verify_transcript(voice,0,1,'نعم',1))
    voice.audit.assert_not_called()
