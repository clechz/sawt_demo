"""Regressions from a real pickup call, plus scheduling and consent invariants."""
import asyncio
import copy
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
import voice_worker
from sawt import v2_runtime as runtime
from sawt.domain import new_state
from sawt.transactions import Transactions
from sawt.choices import caption_draft_answer, service_answer
from sawt.clarification import ask
from sawt.conversation import say
from sawt.recognition import check_recognition, AudioWindowError


@pytest.fixture
def store(tmp_path, monkeypatch):
    tx=Transactions(tmp_path/'regression.db',runtime.engine)
    monkeypatch.setattr(runtime,'tx',tx)
    return tx


@pytest.mark.parametrize('sugar',[None,['half']])
async def test_ambiguous_sugar_gets_one_bound_proposal_after_other_edits(store,sugar):
    from tests.test_tool_batches import call
    sid,_=store.create();state=new_state()
    runtime.engine.act(state,'add_item',{'item_id':'beverages_09','quantity':2,'options':{'ice':['none'],'size':['small']},'notes':''})
    line=state['basket'][0]['line_id']
    store.commit_bundle(sid,'seed',0,0,state,[],response={})
    options={'size':['large'],'ice':['none']}
    if sugar is not None:options['sweetness']=sugar
    provider=SimpleNamespace(supports_tool_batches=True,chat=AsyncMock(side_effect=[
        {'tool_calls':[call('update_item',{'line_id':line,'options':options},'edit')]},
        {'content':'السكر بدون سكر ولا نصف سكر ولا سكر عادي؟'},
        {'content':'السكر بدون سكر ولا نصف سكر ولا سكر عادي؟'}]))
    result=await runtime.delegate(sid,'بدون ثلج، الحجم كبير وخلي سكر وسط.','medium',0,voice_provider=provider)
    assert result['state']['basket'][0]['options']['size']==['large']
    assert not result['state']['basket'][0]['options'].get('sweetness')
    assert result['state']['pending_choice']['option_id']=='half'
    assert 'نصف سكر' in result['reply'] and not result['state']['order_id']
    result=await runtime.delegate(sid,'ايوه','accept',store.load(sid)['epoch'],voice_provider=provider)
    assert result['state']['basket'][0]['options']['sweetness']==['half']
    assert not result['state']['order_id'] and provider.chat.await_count==3


@pytest.mark.parametrize('text',['بستلم','استلام','استلام الفرع','باستلم'])
async def test_pickup_saves_once_without_planner_or_repeating_service_question(store,text):
    sid,_=store.create()
    provider=SimpleNamespace(chat=AsyncMock(side_effect=AssertionError('Unnecessary model call')))
    result=await runtime.delegate(sid,text,'pickup',0,voice_provider=provider)
    assert result['state']['service']=='pickup'
    assert 'توصيل' not in result['reply'] and 'فرع' in result['reply']
    assert not result['state']['quote'] and not result['state']['order_id']


async def test_city_and_zone_answers_are_saved_once_without_another_model_round_trip(store):
    sid,_=store.create();state=new_state()
    runtime.engine.act(state,'set_service',{'service':'delivery'})
    state['history']=[{'role':'assistant','content':say('address_question')}]
    store.commit_bundle(sid,'seed',0,0,state,[],response={})
    provider=SimpleNamespace(chat=AsyncMock(side_effect=AssertionError('Unnecessary model call')))
    result=await runtime.delegate(sid,'الرياض','city',0,voice_provider=provider)
    assert result['state']['delivery_details']=={'city':'الرياض'}
    assert result['reply']=='بأي حي؟'
    result=await runtime.delegate(sid,'حي النرجس','zone',0,voice_provider=provider)
    assert result['state']['delivery_details']=={'city':'الرياض','zone':'النرجس'}
    assert not result['state']['location'] and not result['state']['quote']


@pytest.mark.parametrize('text',['هل توصلون الرياض؟','مو الرياض','الرياض إذا تقدر','الرياض وغير الكمية اثنين','جدة'])
def test_delivery_shortcut_cannot_reinterpret_question_negation_mixed_or_wrong_city_zone(text):
    from sawt.choices import delivery_answer
    state=new_state();state['service']='delivery';state['delivery_details']={'city':'الرياض'}
    state['history']=[{'role':'assistant','content':'بأي حي؟'}]
    assert delivery_answer(state,text) is None
    state['service']='pickup';state['history']=[{'role':'assistant','content':say('address_question')}]
    assert delivery_answer(state,'الرياض') is None


@pytest.mark.parametrize('text',['لا استلام','استلام ولا توصيل؟','نعم','بستلم بس أبي أغير الطلب','بستلم إذا فيه فرع قريب'])
def test_service_parser_never_guesses_mixed_or_conditional_requests(text):
    assert service_answer(new_state(),text) is None


def test_live_caption_can_only_resolve_current_explicit_draft_question():
    state=new_state();state['history']=[{'role':'assistant','content':say('service_question')}]
    for text in ['بستلم','استلام','استلام الفرع']:
        assert caption_draft_answer(runtime.engine.menu,state,text)
    state['history'][0]['content']='ضفت شاورما دجاج. '+say('service_question')
    assert caption_draft_answer(runtime.engine.menu,state,'بستلم')
    for text in ['نعم','لا','توصيل للرياض','استلام ولا توصيل؟','أبي اثنين شاورما']:
        assert not caption_draft_answer(runtime.engine.menu,state,text)
    state['history']=[{'role':'assistant','content':'السلام عليكم'}]
    assert not caption_draft_answer(runtime.engine.menu,state,'استلام')


def test_yes_and_unheard_checkout_cannot_take_caption_fast_path():
    state=new_state()
    runtime.engine.act(state,'add_item',{'item_id':'breakfast_01','quantity':1,'options':{},'notes':''})
    question=ask(runtime.engine.menu,state,state['basket'][0]['line_id'],'portion','large')['reply']
    state['history']=[{'role':'assistant','content':question}]
    assert not caption_draft_answer(runtime.engine.menu,state,'نعم')
    assert caption_draft_answer(runtime.engine.menu,state,'كبير')
    state['quote']={'presented':False}
    assert not caption_draft_answer(runtime.engine.menu,state,'كبير')


@pytest.mark.parametrize('caption,other',[('بستلم','بس'),('استلام','السلام'),('استلام الفرع','السلام الفرع'),('توصيل','استلام')])
def test_fulfillment_disagreement_outside_known_question_is_not_silently_replaced(caption,other):
    with pytest.raises(AudioWindowError,match='Fulfillment'):check_recognition(caption,other)


async def test_dish_identity_question_survives_failed_guess_instead_of_service_question(store):
    sid,_=store.create()
    provider=SimpleNamespace(supports_tool_batches=True,chat=AsyncMock(side_effect=[
        {'tool_calls':[{'id':'guess','type':'function','function':{'name':'add_item','arguments':json.dumps({'item_id':'sandwiches_07','quantity':1,'options':{},'notes':''})}}]},
        {'content':'الشاورما دجاج ولا لحم؟'}]))
    result=await runtime.delegate(sid,'طال عمرك أبغى شاورما','ambiguous',0,voice_provider=provider)
    assert result['reply']=='الشاورما دجاج ولا لحم؟'
    assert result['state']['basket']==[] and not result['state']['service']


@pytest.mark.parametrize('utterance,item,expected',[
    ('أبي شاورما وكرك','beverages_09','الشاورما دجاج ولا لحم؟'),
    ('أبي شاورما لحم','sandwiches_08','الوجبة')])
async def test_unrelated_saved_dish_cannot_hide_ambiguity_but_correct_variant_resolves_it(store,utterance,item,expected):
    from tests.test_tool_batches import call
    sid,_=store.create()
    provider=SimpleNamespace(supports_tool_batches=True,chat=AsyncMock(side_effect=[
        {'tool_calls':[
            call('add_item',{'item_id':'sandwiches_07','quantity':1,'options':{},'notes':''},'wrong'),
            call('add_item',{'item_id':item,'quantity':1,'options':{},'notes':''},'clear')]},
        {'content':'تبيه توصيل ولا تستلمه؟'}]))
    result=await runtime.delegate(sid,utterance,'mixed',0,voice_provider=provider)
    assert [line['item_id'] for line in result['state']['basket']]==[item]
    if item=='beverages_09':assert expected in result['reply']
    else:assert 'دجاج ولا لحم' not in result['reply']
    assert not result['state']['order_id']


async def test_answer_to_dish_question_saves_draft_even_if_planner_first_replies_as_information(store):
    sid,_=store.create();state=new_state()
    state['history']=[{'role':'user','content':'أبغى شاورما'},{'role':'assistant','content':'الشاورما دجاج ولا لحم؟'}]
    store.commit_bundle(sid,'seed',0,0,state,[],response={})
    provider=SimpleNamespace(supports_tool_batches=True,chat=AsyncMock(side_effect=[
        {'content':'شاورما الدجاج متوفرة، تبيها توصيل أو استلام؟'},
        {'tool_calls':[{'id':'add','type':'function','function':{'name':'add_item','arguments':json.dumps({'item_id':'sandwiches_07','quantity':1,'options':{'meal':['sandwich'],'bread':['saj'],'spice_level':['not_spicy']},'notes':''})}}]},
        {'content':'تبيه توصيل ولا تستلمه؟'}]))
    result=await runtime.delegate(sid,'دجاج ساندويتش بصاج بدون حار','followup',0,voice_provider=provider)
    assert len(result['state']['basket'])==1
    assert result['state']['basket'][0]['options']=={'meal':['sandwich'],'bread':['saj'],'spice_level':['not_spicy']}
    assert result['reply'].endswith(say('service_question'))


async def test_database_wait_does_not_block_media_event_loop(store,monkeypatch):
    sid,_=store.create();started=threading.Event();release=threading.Event()
    original=store.replay_bundle
    def slow(*args):
        started.set()
        assert release.wait(2)
        return original(*args)
    monkeypatch.setattr(store,'replay_bundle',slow)
    task=asyncio.create_task(runtime.delegate(sid,'استلام','slow',0))
    try:
        await asyncio.wait_for(asyncio.to_thread(started.wait),1)
        # An audio callback can execute while the DB operation is still blocked.
        tick=asyncio.Event();asyncio.get_running_loop().call_soon(tick.set)
        await asyncio.wait_for(tick.wait(),.2)
        assert not task.done()
    finally:
        release.set()
    result=await task
    assert result['state']['service']=='pickup'


async def test_slow_invalidation_cannot_block_caption_callbacks_or_reorder_epochs(monkeypatch):
    started=threading.Event();release=threading.Event();epochs=[]
    def interrupt(*args,**kwargs):
        started.set();assert release.wait(2);epochs.append(len(epochs)+1);return epochs[-1]
    monkeypatch.setattr(voice_worker.tx,'interrupt',interrupt)
    monkeypatch.setattr(voice_worker.tx,'load',lambda sid:{'state':{'quote':None}})
    voice=SimpleNamespace(sid='s',provider_failed=False,ending=False,last_input=0,
        fragments=[],fragment_spans=[],input_audio=SimpleNamespace(duration_ms=1000),
        audit=Mock(),input_invalidated=False,send=AsyncMock(),reading=False,spawn=asyncio.create_task)
    event={'type':'session.input_transcript.delta','delta':'أبي','start_ms':100,'end_ms':300}
    try:
        voice_worker.RestaurantVoice.on_provider_event(voice,event)
        await asyncio.wait_for(asyncio.to_thread(started.wait),1)
        voice.input_invalidated=False
        voice_worker.RestaurantVoice.on_provider_event(voice,event)
        assert len(voice.fragments)==2 and not epochs
    finally:release.set()
    await voice.input_boundary
    assert epochs==[1,2]


@pytest.mark.parametrize('recovered,passes',[
    ('أبي ثلاثة تميس بالعسل استلام',True),
    ('أبي اثنين تميس بالعسل استلام',False),
    ('أبي تميس بالعسل استلام',False),
    ('أبي ثلاثة تميس بالعسل توصيل',False)])
async def test_recognition_disagreement_rechecks_audio_but_never_guesses_quantity(monkeypatch,recovered,passes):
    monkeypatch.setattr(voice_worker.tx,'load',lambda sid:{'closed':False,'epoch':1,'state':new_state()})
    caption='أبي ثلاثة تميس بالعسل استلام'
    voice=SimpleNamespace(sid='s',send=AsyncMock(),audit=Mock(),fragments=[caption],
        fragment_spans=[{'start_ms':0,'end_ms':1}],
        input_audio=SimpleNamespace(wav=Mock(return_value=(b'exact-pcm',{}))),
        provider=SimpleNamespace(recognize=AsyncMock(side_effect=['أبي فلافل تميس بالعسل استلام',recovered])))
    if passes:
        assert await voice_worker.RestaurantVoice.verify_transcript(voice,0,1,caption,1)==recovered
    else:
        with pytest.raises(AudioWindowError):await voice_worker.RestaurantVoice.verify_transcript(voice,0,1,caption,1)
    assert voice.provider.recognize.await_count==2
    assert voice.provider.recognize.call_args.kwargs['recovery'] is True
    assert caption not in voice.provider.recognize.call_args.kwargs['context']


@pytest.mark.parametrize('text,spoken',[
    ('المجموع 18.00 ريال. نأكد الطلب؟','المجموع ثمانية عشر ريال. نأكد الطلب؟'),
    ('المجموع 18.50 ريال.','المجموع ثمانية عشر ريال وخمسين هللة.'),
    ('0.05 ريال و12.01 ريال','خمس هللات واثنا عشر ريال وهللة'),
    ('الطلب 0018 وشارع 12.00','الطلب 0018 وشارع 12.00')])
def test_speech_amount_normalization_preserves_value_and_confirmation(text,spoken):
    from sawt.v2_provider import spoken_amounts
    assert spoken_amounts(text)==spoken


async def test_recovery_cannot_discard_cancellation_found_by_second_transcription(monkeypatch):
    monkeypatch.setattr(voice_worker.tx,'load',lambda sid:{'closed':False,'epoch':1,'state':new_state()})
    # An ordinary-looking live caption is not permission to ignore the other
    # recognizer's cancellation/negation/question when recovery drops it.
    caption='الذي الطلب كله'
    voice=SimpleNamespace(sid='s',send=AsyncMock(),audit=Mock(),fragments=[caption],
        fragment_spans=[{'start_ms':0,'end_ms':1}],
        input_audio=SimpleNamespace(wav=Mock(return_value=(b'exact-pcm',{}))),
        provider=SimpleNamespace(recognize=AsyncMock(side_effect=['ألغي الطلب كله.','الذي ابطلب كله'])))
    with pytest.raises(AudioWindowError):
        await voice_worker.RestaurantVoice.verify_transcript(voice,0,1,caption,1)


async def test_more_caller_words_during_recovery_supersede_incomplete_disagreement(monkeypatch):
    monkeypatch.setattr(voice_worker.tx,'load',lambda sid:{'closed':False,'epoch':1,'state':new_state()})
    caption='أبي ثلاثة تميس بالعسل'
    voice=SimpleNamespace(sid='s',send=AsyncMock(),audit=Mock(),fragments=[caption],
        fragment_spans=[{'start_ms':0,'end_ms':1}],
        input_audio=SimpleNamespace(wav=Mock(return_value=(b'exact-pcm',{}))))
    async def recognize(wav,**kwargs):
        if kwargs.get('recovery'):
            voice.fragments.append(' استلام من فرع النرجس')
        return 'أبي فلافل تميس بالعسل استلام'
    voice.provider=SimpleNamespace(recognize=recognize)
    with pytest.raises(voice_worker.Conflict):
        await voice_worker.RestaurantVoice.verify_transcript(voice,0,1,caption,1)


async def test_obsolete_recognition_error_does_not_publish_clarification(monkeypatch):
    from tests.test_recognition import work_voice
    monkeypatch.setattr(voice_worker.tx,'load',lambda sid:{'closed':False,'epoch':1})
    voice=work_voice('')
    async def recognize(*args):
        voice.fragments.append(' وباقي طلبي')
        raise AudioWindowError('Incomplete earlier fragment')
    voice.verify_transcript=recognize
    await voice_worker.RestaurantVoice.work(voice,None)
    voice.clarify_recognition.assert_not_awaited()
    assert all(c.args[0]!='transcript.unverified' for c in voice.audit.call_args_list)


async def test_ready_waits_for_both_provider_and_microphone(monkeypatch):
    monkeypatch.setattr(voice_worker.tx,'event',Mock())
    voice=SimpleNamespace(sid='s',provider_ready=asyncio.Event(),input_ready=asyncio.Event(),
        provider_failed=False,ending=False,send=AsyncMock(),duplex_session=Mock(),
        close_failed_voice=AsyncMock(),audit=Mock())
    task=asyncio.create_task(voice_worker.RestaurantVoice.announce_ready(voice))
    await asyncio.sleep(0)
    voice.provider_ready.set()
    await asyncio.sleep(0)
    assert not task.done()
    voice.send.assert_not_awaited()
    voice.duplex_session.append_commentary.assert_not_called()
    voice.input_ready.set()
    await asyncio.wait_for(task,1)
    voice.send.assert_awaited_once_with('ready')


async def test_failed_connection_never_announces_ready(monkeypatch):
    voice=SimpleNamespace(provider_ready=asyncio.Event(),input_ready=asyncio.Event(),
        provider_failed=True,ending=False,send=AsyncMock(),duplex_session=Mock())
    voice.provider_ready.set();voice.input_ready.set()
    await voice_worker.RestaurantVoice.announce_ready(voice)
    voice.send.assert_not_awaited()
    voice.duplex_session.append_commentary.assert_not_called()


@pytest.mark.parametrize('new_input_during_injection',[False,True])
async def test_reply_epoch_tracks_valid_quote_invalidation_not_old_input_epoch(monkeypatch,new_input_during_injection):
    from tests.test_recognition import work_voice
    epoch=1
    monkeypatch.setattr(voice_worker.tx,'load',lambda sid:{'closed':False,'epoch':epoch})
    async def delegate(*args,**kwargs):
        nonlocal epoch
        epoch=2  # A legitimate correction invalidates the prior quote.
        return {'reply':'تم التعديل.','state':{'quote':None,'order_id':None}}
    monkeypatch.setattr(voice_worker,'delegate',delegate)
    voice=work_voice('خل الكمية اثنين')
    voice.provider=SimpleNamespace()
    def inject(*args,**kwargs):
        nonlocal epoch
        if new_input_during_injection:epoch=3
    voice.duplex_session.append_thinking.side_effect=inject
    voice.speak_verified_reply=AsyncMock()
    await voice_worker.RestaurantVoice.work(voice,None)
    assert voice.speak_verified_reply.await_count==(0 if new_input_during_injection else 1)
    if not new_input_during_injection:voice.speak_verified_reply.assert_awaited_once_with('تم التعديل.',1,2)
    assert voice.output_held is new_input_during_injection


async def test_exhausted_credit_closes_call_instead_of_retrying_speech(monkeypatch):
    from tests.test_recognition import work_voice
    from sawt.v2_provider import ProviderQuotaError, CALLS_UNAVAILABLE
    monkeypatch.setattr(voice_worker.tx,'load',lambda sid:{'epoch':1})
    voice=work_voice('');voice.verify_transcript.side_effect=ProviderQuotaError(CALLS_UNAVAILABLE)
    voice.close_failed_voice=AsyncMock()
    await voice_worker.RestaurantVoice.work(voice,None)
    voice.close_failed_voice.assert_awaited_once_with(CALLS_UNAVAILABLE)
    voice.clarify_recognition.assert_not_awaited()
    voice.duplex_session.append_commentary.assert_not_called()


async def test_billing_failure_in_background_speech_closes_call():
    from sawt.v2_provider import ProviderQuotaError, CALLS_UNAVAILABLE
    async def failed_speech():raise ProviderQuotaError(CALLS_UNAVAILABLE)
    task=asyncio.create_task(failed_speech())
    await asyncio.gather(task,return_exceptions=True)
    pending=[]
    def spawn(coro):pending.append(asyncio.create_task(coro))
    voice=SimpleNamespace(tasks={task},audit=Mock(),provider_failed=False,spawn=spawn,close_failed_voice=AsyncMock())
    voice_worker.RestaurantVoice.task_finished(voice,task)
    await asyncio.gather(*pending)
    voice.close_failed_voice.assert_awaited_once_with(CALLS_UNAVAILABLE)
    assert voice.provider_failed and not voice.tasks
