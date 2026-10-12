from types import SimpleNamespace
from unittest.mock import Mock
import voice_worker

def test_short_answer_after_controlled_readback_routes_without_model_delegation(monkeypatch):
    monkeypatch.setattr(voice_worker.tx,'event',Mock())
    voice=SimpleNamespace(sid='s',checkout_context=True,audit=Mock(),on_delegation=Mock(),output_held=False,session=Mock())
    voice_worker.RestaurantVoice.on_transcript(voice,SimpleNamespace(transcript='نعم',item_id='i',is_final=True))
    voice.on_delegation.assert_called_once()
    assert voice.on_delegation.call_args.args[0].id is None

def test_small_talk_outside_checkout_does_not_force_reasoning(monkeypatch):
    monkeypatch.setattr(voice_worker.tx,'event',Mock())
    voice=SimpleNamespace(sid='s',checkout_context=False,audit=Mock(),on_delegation=Mock(),output_held=False,session=Mock(),fragments=['هلا'],consumed=0)
    voice_worker.RestaurantVoice.on_transcript(voice,SimpleNamespace(transcript='هلا',item_id='i',is_final=True))
    voice.on_delegation.assert_not_called()


def test_repeated_provider_close_events_only_trigger_one_failure_close(monkeypatch):
    monkeypatch.setattr(voice_worker.tx,'event',Mock())
    monkeypatch.setattr(voice_worker.tx,'load',Mock(return_value={'closed':False}))
    async def close():pass
    close_request=Mock(side_effect=close)
    voice=SimpleNamespace(sid='s',provider_failed=False,audit=Mock(),close_failed_voice=close_request,spawn=lambda coroutine:coroutine.close())
    voice_worker.RestaurantVoice.on_provider_event(voice,{'type':'error','error':{'code':'context_injection_incomplete'}})
    voice_worker.RestaurantVoice.on_provider_event(voice,{'type':'session.closed'})
    voice_worker.RestaurantVoice.on_provider_event(voice,{'type':'session.closed'})
    close_request.assert_called_once()
    assert voice.provider_failed


def test_short_size_answer_routes_and_holds_speculative_audio(monkeypatch):
    monkeypatch.setattr(voice_worker.tx,'event',Mock())
    voice=SimpleNamespace(sid='s',checkout_context=False,audit=Mock(),on_delegation=Mock(),output_held=False,session=Mock())
    voice_worker.RestaurantVoice.on_transcript(voice,SimpleNamespace(transcript='حجم عادي عادي',item_id='i',is_final=True))
    voice.on_delegation.assert_called_once()
    voice.session.output.set_audio_enabled.assert_called_once_with(False)


def test_end_command_is_exact_and_does_not_end_negation_or_question():
    from sawt.voice_routing import route_transcript
    assert route_transcript('انهي المكالمة يلا') == 'end'
    assert route_transcript('انهِ المكالمة يلا') == 'end'
    assert route_transcript('أنهِ المكالمة لو سمحت') == 'end'
    for text in ['لا تقفل المكالمة', 'كيف اقفل المكالمة', 'اقفل المكالمة بعد ما تؤكد طلبي', 'حجم عادي عادي']:
        assert route_transcript(text) == 'backend'


def test_same_transcript_fallback_does_not_cancel_running_delegation():
    pending=Mock();pending.done.return_value=False
    voice=SimpleNamespace(pending=pending,pending_end=2,fragments=['عادي',' عادي'],duplex_session=Mock(),spawn=Mock())
    voice_worker.RestaurantVoice.on_delegation(voice,SimpleNamespace(id=None))
    pending.cancel.assert_not_called()
    voice.spawn.assert_not_called()


def test_end_command_closes_durable_call_and_transport(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    interrupt=Mock();monkeypatch.setattr(voice_worker.tx,'interrupt',interrupt)
    monkeypatch.setattr(voice_worker.tx,'load',Mock(return_value={'state':{'basket':[],'order_id':None,'handoff':None}}))
    voice=SimpleNamespace(sid='s',ending=False,pending=None,audit=Mock(),send=AsyncMock(),play_closing=AsyncMock(),session=SimpleNamespace(aclose=AsyncMock()),room=SimpleNamespace(disconnect=AsyncMock()))
    asyncio.run(voice_worker.RestaurantVoice.end_requested(voice))
    assert [call.args for call in interrupt.call_args_list]==[('s',),('s',)]
    assert interrupt.call_args.kwargs=={'close':True}
    assert [call.args for call in voice.send.await_args_list]==[('ending',),('ended',)]
    voice.play_closing.assert_awaited_once_with('يعطيك العافية، مع السلامة.')
    voice.session.aclose.assert_awaited_once()
    voice.room.disconnect.assert_awaited_once()


def test_hangup_split_across_transcript_segments_is_joined_before_routing(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    delegate=AsyncMock();monkeypatch.setattr(voice_worker,'delegate',delegate)
    monkeypatch.setattr(voice_worker.tx,'load',Mock(return_value={'epoch':1}))
    voice=SimpleNamespace(sid='s',last_input=0,fragments=[' أنهي',' المكالمة يلا'],consumed=0,current_item='second',processed='',checkout_context=False,end_requested=AsyncMock(),verify_transcript=AsyncMock(return_value='أنهي المكالمة يلا'))
    asyncio.run(voice_worker.RestaurantVoice.work(voice,None))
    voice.end_requested.assert_awaited_once()
    delegate.assert_not_awaited()
    assert voice.consumed==2


def test_wait_controls_are_exact_not_negations_orders_or_quoted_notes():
    from sawt.voice_routing import route_transcript
    for text in ['لحظة', 'اسكت شوي', 'يا حبيبي ترك، ما قاعد أتكلم', 'أنا ساكت', 'انتظر لو سمحت', 'خلني أكمل']:
        assert route_transcript(text, checkout=True) == 'wait'
    for text in ['لا تنتظر', 'لا تسكت', 'اكتب بالملاحظات انتظر', 'انتظر أبي شاورما', 'لا أنا ما قاعد أتكلم عن الدجاج']:
        assert route_transcript(text) == 'backend'


def test_wait_caption_is_verified_before_it_can_silence_the_bot(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(voice_worker.tx,'event',Mock())
    voice=SimpleNamespace(sid='s',checkout_context=False,audit=Mock(),on_delegation=Mock(),output_held=False,
        session=Mock(),fragments=['ما قاعد أتكلم'],wait_requested=AsyncMock(),spawn=lambda coro:coro.close())
    voice_worker.RestaurantVoice.on_transcript(voice,SimpleNamespace(transcript='ما قاعد أتكلم',item_id='i',is_final=True))
    voice.on_delegation.assert_called_once()
    voice.wait_requested.assert_not_called()
    voice.session.output.set_audio_enabled.assert_called_once_with(False)


def test_wait_cancels_work_and_keeps_call_open_without_speaking(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    interrupt=Mock(return_value=4);monkeypatch.setattr(voice_worker.tx,'interrupt',interrupt)
    pending=Mock();pending.done.return_value=False
    voice=SimpleNamespace(sid='s',pending=pending,consumed=0,fragments=['لحظة'],session=Mock(),
        audit=Mock(),send=AsyncMock(),duplex_session=Mock())
    asyncio.run(voice_worker.RestaurantVoice.wait_requested(voice,1))
    pending.cancel.assert_called_once()
    interrupt.assert_called_once_with('s')  # no close or basket write
    assert voice.waiting and voice.output_held and voice.consumed==1 and not voice.checkout_context
    voice.send.assert_awaited_once_with('waiting',epoch=4)
    voice.duplex_session.append_commentary.assert_not_called()


def test_delayed_wait_consumes_only_its_own_words_and_preserves_fresh_work():
    import asyncio
    from unittest.mock import AsyncMock
    voice=SimpleNamespace(consumed=0,fragments=['لحظة','أبي شاورما'],pending=Mock(),send=AsyncMock())
    asyncio.run(voice_worker.RestaurantVoice.wait_requested(voice,1))
    assert voice.consumed==1
    voice.pending.cancel.assert_not_called()
    voice.send.assert_not_awaited()


def test_model_delegation_cannot_break_wait_without_fresh_speech():
    voice=SimpleNamespace(waiting=True,fragments=['لحظة'],consumed=1,spawn=Mock())
    voice_worker.RestaurantVoice.on_delegation(voice,SimpleNamespace(id='late-model-event'))
    voice.spawn.assert_not_called()


def test_new_backend_turn_after_wait_resumes_delegation(monkeypatch):
    monkeypatch.setattr(voice_worker.tx,'event',Mock())
    voice=SimpleNamespace(sid='s',waiting=True,checkout_context=False,output_held=True,audit=Mock(),
        session=Mock(),on_delegation=Mock())
    voice_worker.RestaurantVoice.on_transcript(voice,SimpleNamespace(transcript='بكم الشاورما؟',item_id='next',is_final=True))
    assert voice.waiting  # released only after checking the new audio
    voice.on_delegation.assert_called_once()


def test_microphone_check_bypasses_restaurant_planner_without_swallowing_order():
    from sawt.voice_routing import route_transcript
    for text in ['هلا والله تسمعني؟', 'تسمعني', 'ألو تسمعني؟']:
        assert route_transcript(text) == 'recover'
    assert route_transcript('تسمعني أبي شاورما') == 'backend'
