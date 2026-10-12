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


@pytest.mark.parametrize('caption,verified', [
    ('الذي اطلب كله', 'الذي الطلب كله.'), ('الذي الطلب كله', 'الذي الطلب كله'),
    ('ألغي الطلب كله', 'الدي الطلب كله'), ('الذي الطلب كله', 'هذا الطلب كله'),
])
def test_agreed_garbled_order_request_requires_repeat_not_cancel_or_checkout(caption, verified):
    from sawt.recognition import check_transcript_clarity
    with pytest.raises(AudioWindowError, match='Unclear whole-order'):
        check_transcript_clarity(caption, verified)


@pytest.mark.parametrize('text', ['هذا الطلب كله', 'ألغي الطلب كله', 'كنسل طلبي', 'لا تلغي الطلب', 'الطلب كله بدون حار'])
def test_clear_whole_order_requests_are_not_rejected_as_garbled(text):
    from sawt.recognition import check_transcript_clarity
    check_transcript_clarity(text, text)


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
    assert span=={'start_ms':24600,'end_ms':29250}
    assert len(wav)>24000


def test_late_cloud_caption_retains_opening_word_without_replaying_previous_turn():
    audio=AudioWindow()
    pcm=b'\x01\x02'*24000*12
    audio.append(base64.b64encode(pcm).decode())
    spans=[{'start_ms':8000,'end_ms':9000,'captured_ms':9300}]
    wav,span=audio.wav(spans)
    assert span['start_ms']==5000  # actual price question began at 6000
    bounded,span=audio.wav(spans,after_ms=5500)
    with wave.open(io.BytesIO(bounded)) as w:
        assert w.readframes(w.getnframes())==pcm[5500*48:9450*48]
    with pytest.raises(AudioWindowError):audio.wav(spans,after_ms=10000)


@pytest.mark.parametrize('text',['كانسل طلبي','كنسل طلبي','كانسل الطلب'])
def test_cancellation_spelling_variants_remain_full_utterance_only(text):
    from sawt.conversation import requests_cancel
    assert requests_cancel(text)
    assert not requests_cancel('لا '+text)
    assert not requests_cancel(text+' لو السعر غالي')

async def test_caption_burst_invalidates_once_but_new_work_can_be_superseded(monkeypatch):
    interrupt=Mock(return_value=2)
    monkeypatch.setattr(voice_worker.tx,'interrupt',interrupt)
    monkeypatch.setattr(voice_worker.tx,'load',Mock(return_value={'state':{'quote':None}}))
    voice=SimpleNamespace(sid='s',provider_failed=False,ending=False,last_input=0,
        fragments=[],fragment_spans=[],input_audio=SimpleNamespace(duration_ms=1000),
        audit=Mock(),input_invalidated=False,send=AsyncMock(),reading=False,
        spawn=asyncio.create_task)
    event={'type':'session.input_transcript.delta','delta':'أبي','start_ms':100,'end_ms':300}
    voice_worker.RestaurantVoice.on_provider_event(voice,event)
    voice_worker.RestaurantVoice.on_provider_event(voice,event)
    await voice.input_boundary
    assert interrupt.call_count==1 and len(voice.fragments)==2
    voice.input_invalidated=False  # verification starts a new work boundary
    voice_worker.RestaurantVoice.on_provider_event(voice,event)
    await voice.input_boundary
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


def test_saudi_wahda_is_same_quantity_as_wahida_but_not_two():
    from sawt.recognition import check_recognition
    check_recognition('خل الشكشوكة وحدة بدل اثنين', 'خل الشكشوكة واحدة بدل اثنين')
    with pytest.raises(AudioWindowError):
        check_recognition('خل الشكشوكة وحدة', 'خل الشكشوكة اثنين')


def test_price_spelling_variant_keeps_question_intent():
    check_recognition('بكم سندويش الشاورما','بيكم سندويش الشاورما')

def test_cancel_disagreement_requires_clarification_not_an_unrelated_option_question():
    with pytest.raises(AudioWindowError,match='Cancellation'):
        check_recognition('ألغي الطلب كله','الغي القلب كله')


@pytest.mark.parametrize('verified',['Cancel طلبي.','cancel الطلب','cancel الطلب كله'])
def test_code_switched_cancel_keeps_whole_draft_cancellation_intent(verified):
    from sawt.conversation import requests_cancel
    assert requests_cancel(verified)
    check_recognition('كنسل طلبي',verified)
    assert not requests_cancel('لا '+verified)
    assert not requests_cancel('إذا تأخر '+verified)
    assert not requests_cancel('اكتب بالملاحظات '+verified)


def test_spacing_reconciliation_preserves_negation_without_changing_words_or_digits():
    from sawt.recognition import reconcile_spacing
    caption='خل الخبز بر مو صاج'
    fixed=reconcile_spacing(caption,'خل الخبز برموصاج.')
    assert fixed==caption
    check_recognition(caption,fixed)
    assert reconcile_spacing('الغي الطلب','الغي القلب')=='الغي القلب'
    assert reconcile_spacing('1 2','12')=='12'


def test_caption_spacing_cannot_break_an_intact_verified_wait_command():
    from sawt.recognition import reconcile_spacing
    assert reconcile_spacing('إن تظر شويّ لو سمحت','انتظر شوي لو سمحت')=='انتظر شوي لو سمحت'
    assert route_transcript('إن تظر شويّ لو سمحت')=='wait'
    assert route_transcript('لا انتظر شوي لو سمحت')=='backend'
    assert route_transcript('اكتب بالملاحظات إن تظر شوي لو سمحت')=='backend'
    assert route_transcript('إن تظر شوي وأبي شاورما')=='backend'

def test_audio_check_uses_explicit_playback_not_passive_model_commentary(monkeypatch):
    monkeypatch.setattr(voice_worker.tx,'load',Mock(return_value={'epoch':1}))
    voice=SimpleNamespace(sid='s',consumed=0,waiting=True,output_held=True,session=Mock(),audit=Mock(),
        duplex_session=Mock(),play_message=AsyncMock(),send=AsyncMock())
    asyncio.run(voice_worker.RestaurantVoice.recover_audio(voice,1))
    voice.play_message.assert_awaited_once_with('معك، تسمعني الحين؟')
    voice.duplex_session.append_commentary.assert_not_called()


def test_dropped_price_prefix_preserves_information_intent_only_for_identical_dish():
    from sawt.recognition import reconcile_transcripts
    assert reconcile_transcripts('بكم سندويش الشاورما','سندويش الشاورما.')=='بكم سندويش الشاورما'
    assert reconcile_transcripts('بكم سندويش الشاورما','سندويش دجاج')=='سندويش دجاج'
    assert reconcile_transcripts('أبي اثنين شاورما','شاورما')=='شاورما'
    assert reconcile_transcripts('لا تضيف شاورما','ضيف شاورما')=='ضيف شاورما'


@pytest.mark.parametrize('reason',['audible','new_speech','closed','epoch','waiting','reading','held','ending','missing'])
def test_missing_reply_fallback_never_replays_answered_or_stale_turn(monkeypatch,reason):
    monkeypatch.setattr(voice_worker.asyncio,'sleep',AsyncMock())
    monkeypatch.setattr(voice_worker.tx,'load',Mock(return_value={'closed':reason=='closed','epoch':2 if reason=='epoch' else 1}))
    voice=SimpleNamespace(sid='s',ending=reason=='ending',waiting=reason=='waiting',reading=reason=='reading',output_held=reason=='held',
        fragments=['a','b'] if reason=='new_speech' else ['a'],last_output_audio=11 if reason=='audible' else 0,
        audit=Mock(),play_message=AsyncMock())
    asyncio.run(voice_worker.RestaurantVoice.ensure_reply(voice,'verified answer',10,1,1))
    assert voice.play_message.await_count==(1 if reason=='missing' else 0)


def test_reply_fallback_rechecks_after_speech_generation(monkeypatch):
    closed=[]
    async def chunks(*args):
        try:
            yield b'\0'*960
            raise AssertionError('Stale synthesis must not be consumed')
        finally:closed.append(True)
    voice=SimpleNamespace(provider=SimpleNamespace(speech_chunks=chunks),session=Mock())
    guard=AsyncMock(return_value=False)
    asyncio.run(voice_worker.RestaurantVoice.play_message(voice,'old answer',can_play=guard))
    guard.assert_awaited_once()
    voice.session.say.assert_not_called()
    assert closed==[True]


def test_streaming_reply_rechecks_new_input_after_interrupting_old_audio():
    closed=[]
    async def chunks(*args):
        try:yield b'\0'*960
        finally:closed.append(True)
    session=Mock();session.interrupt=AsyncMock()
    voice=SimpleNamespace(provider=SimpleNamespace(speech_chunks=chunks),session=session)
    guard=AsyncMock(side_effect=[True,False])
    asyncio.run(voice_worker.RestaurantVoice.play_message(voice,'superseded reply',can_play=guard))
    session.interrupt.assert_awaited_once_with(force=True)
    session.say.assert_not_called()
    assert closed==[True]
