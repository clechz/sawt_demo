import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
import voice_worker
from sawt.agent import Agent
from sawt.conversation import farewell, requests_cancel, say
from sawt.domain import Engine, Menu, new_state, RuleError
from sawt.transactions import Transactions


@pytest.fixture
def engine():return Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv'))


@pytest.mark.parametrize('text',['الغ الطلب','كنسل طلبي','خلاص الغ طلبي لو سمحت','clear my basket'])
def test_cancel_entire_draft_keeps_session_available(engine,text):
    state=new_state()
    engine.act(state,'set_service',{'service':'pickup'})
    engine.act(state,'set_branch',{'branch_id':'ruh_narjis'})
    engine.act(state,'add_item',{'item_id':'breakfast_01','options':{},'quantity':2})
    state['quote']={'token':'old'};state['pending_choice']={'group_id':'bread'}
    revised,reply=asyncio.run(Agent(engine,None).turn(state,text))
    assert revised['basket']==[] and revised['service'] is None and revised['branch'] is None
    assert revised['quote'] is None and revised['pending_choice'] is None
    assert revised['order_id'] is None and revised['handoff'] is None
    assert reply['events'][0]['tool']=='cancel_draft'
    assert len(state['basket'])==1  # turn is staged
    engine.act(revised,'add_item',{'item_id':'breakfast_02','options':{},'quantity':1})
    assert len(revised['basket'])==1


@pytest.mark.parametrize('text',['لا تلغي الطلب','لا تكنسل طلبي','الغ الصوص','الغ الطلب إذا تأخر','اكتب بالملاحظات الغ الطلب','كيف الغ الطلب'])
def test_cancel_does_not_match_negation_item_note_question_or_condition(engine,text):
    assert not requests_cancel(text)
    state=new_state();before=copy.deepcopy(state)
    with pytest.raises(RuleError):engine.act(state,'cancel_draft',{},utterance=text)
    assert state==before


def test_confirmed_order_cannot_be_canceled_by_draft_route(engine):
    state=new_state();state['order_id']='S-EXISTING'
    updated,reply=asyncio.run(Agent(engine,None).turn(state,'الغ طلبي'))
    assert updated['order_id']=='S-EXISTING' and not reply['events']
    assert 'موظف' in reply['reply']


def test_cancel_reply_survives_runtime_without_restarting_order_questions(engine,tmp_path,monkeypatch):
    from sawt import v2_runtime as runtime
    tx=Transactions(tmp_path/'calls.db',engine);sid,_=tx.create()
    tx.execute(sid,'service',0,0,'set_service',{'service':'pickup'})
    monkeypatch.setattr(runtime,'tx',tx)
    result=asyncio.run(runtime.delegate(sid,'الغ طلبي','cancel',0))
    assert result['reply']==say('draft_canceled')
    assert not tx.load(sid)['closed'] and tx.load(sid)['state']['service'] is None


def test_farewell_reports_only_authoritative_order_state():
    state=new_state();assert farewell(state)==say('goodbye_empty')
    state['basket']=[{}];assert farewell(state)==say('goodbye_draft')
    state['handoff']={'ticket':'H-1'};assert farewell(state)==say('goodbye_handoff')
    state['order_id']='S-1';assert farewell(state)==say('goodbye_confirmed')


def test_goodbye_failure_still_closes_media_and_duplicate_close_is_ignored(monkeypatch):
    interrupt=Mock();monkeypatch.setattr(voice_worker.tx,'interrupt',interrupt)
    monkeypatch.setattr(voice_worker.tx,'load',Mock(return_value={'state':new_state()}))
    voice=SimpleNamespace(sid='s',ending=False,pending=None,audit=Mock(),send=AsyncMock(),
        play_closing=AsyncMock(side_effect=TimeoutError()),session=SimpleNamespace(aclose=AsyncMock()),room=SimpleNamespace(disconnect=AsyncMock()))
    async def run():
        await voice_worker.RestaurantVoice.end_requested(voice)
        await voice_worker.RestaurantVoice.end_requested(voice)
    asyncio.run(run())
    assert interrupt.call_args.kwargs=={'close':True}
    voice.session.aclose.assert_awaited_once();voice.room.disconnect.assert_awaited_once()
    voice.play_closing.assert_awaited_once()
    assert any(call.args[0]=='call.goodbye_failed' for call in voice.audit.call_args_list)


def test_accepting_staff_offer_cannot_confirm_order(engine):
    state=new_state();state['quote']={'presented':True,'revision':0}
    reply=engine.act(state,'offer_handoff',{'reason':'أوقات العمل','topic':'hours'})
    assert state['quote'] is None and 'أوقات الدوام' in reply['reply']
    updated,result=asyncio.run(Agent(engine,None).turn(state,'نعم'))
    assert updated['handoff'] and updated['order_id'] is None and updated['pending_handoff'] is None
    assert [e['tool'] for e in result['events']]==['handoff']


def test_declining_staff_offer_keeps_basket_and_does_not_offer_again(engine):
    state=new_state();engine.act(state,'add_item',{'item_id':'breakfast_01','quantity':1,'options':{}})
    engine.act(state,'offer_handoff',{'reason':'حساسية','topic':'allergens'})
    updated,result=asyncio.run(Agent(engine,None).turn(state,'لا شكرا'))
    assert updated['basket']==state['basket'] and not updated['pending_handoff'] and not updated['handoff']
    assert result['reply']==say('handoff_declined') and not result['events']


def test_intervening_information_expires_staff_offer(engine):
    state=new_state();engine.act(state,'offer_handoff',{'reason':'سؤال'})
    provider=SimpleNamespace(chat=AsyncMock(return_value={'content':'هلا فيك'}))
    updated,_=asyncio.run(Agent(engine,provider).turn(state,'هلا'))
    assert updated['pending_handoff'] is None and not updated['handoff']


@pytest.mark.parametrize('offer',['أحولك لموظف؟','أقدر أرفع طلب لموظف يتواصل معك. هل ترغب بذلك؟','أستطيع رفع طلب لموظف يتواصل معك. هل ترغب بذلك؟','أقدر أفتح لك تذكرة دعم. ترغب أرفع طلب متابعة للموظفين؟','إذا تحتاج مساعدة من الموظف بهذا الخصوص أقدر أرفع طلب لهم. هل ترغب بذلك؟'])
def test_known_false_transfer_offer_becomes_truthful_stateful_offer(engine,offer):
    state=new_state()
    updated,result=Agent(engine,None).finish(state,'متى تقفلون؟',offer,[])
    assert 'مو مفعّل' in result['reply'] and updated['pending_handoff']
    assert not updated['handoff'] and result['events'][-1]['source']=='handoff_offer_guard'
