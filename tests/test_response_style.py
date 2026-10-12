import copy
from pathlib import Path
import pytest
from sawt.domain import Engine, Menu, new_state
from sawt.clarification import next_question
from sawt.response_style import changes, finished_order, combine

@pytest.fixture
def setup():
    engine=Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv'))
    state=new_state()
    engine.act(state,'add_item',{'item_id':'breakfast_01','quantity':1,'options':{'portion':['regular'],'bread':['saj']},'notes':''})
    return engine,state

def test_incremental_address_asks_only_missing_fields(setup):
    engine,state=setup
    for fields,question in [({'city':'الرياض'},'بأي حي؟'),({'zone':'النرجس'},'واسم الشارع ورقم المبنى؟'),({'street':'شارع الملك'},'ورقم المبنى؟')]:
        engine.act(state,'set_delivery_details',fields)
        assert next_question(engine.menu,state)==question
        assert state['location'] is None and engine.view(state)['issues']
    engine.act(state,'set_delivery_details',{'building':'12'})
    assert next_question(engine.menu,state) is None
    assert state['location']['address']=='شارع الملك، مبنى 12'
    assert not engine.view(state)['issues']

@pytest.mark.parametrize('fields,kept', [({'city':'جدة'},{'city':'جدة'}),({'zone':'الياسمين'},{'city':'الرياض','zone':'الياسمين'}),({'street':'شارع جديد'},{'city':'الرياض','zone':'النرجس','street':'شارع جديد'})])
def test_address_correction_discards_stale_dependent_details(setup,fields,kept):
    engine,state=setup
    engine.act(state,'set_delivery_details',{'city':'الرياض','zone':'النرجس','street':'شارع الملك','building':'12'})
    engine.act(state,'set_delivery_details',fields)
    assert state['delivery_details']==kept and state['location'] is None
    assert len(state['basket'])==1

def test_unsupported_address_and_pickup_reset(setup):
    engine,state=setup
    engine.act(state,'set_delivery_details',{'city':'الرياض','zone':'النرجس','street':'شارع الملك','building':'12'})
    result=engine.act(state,'set_delivery_details',{'zone':'غير موجود'})
    assert result['error'] and state['location'] is None and state['branch'] is None
    engine.act(state,'set_service',{'service':'pickup'})
    assert state['delivery_details']=={}

def test_address_accepts_fields_in_any_order(setup):
    engine,state=setup
    for fields in ({'building':'12'},{'street':'شارع الملك'},{'zone':'النرجس'},{'city':'الرياض'}):
        engine.act(state,'set_delivery_details',fields)
    assert state['location']['address']=='شارع الملك، مبنى 12'
    assert not engine.view(state)['issues']

def test_acknowledgment_only_actual_changes(setup):
    engine,state=setup;before=copy.deepcopy(state)
    assert changes(engine.menu,before,state)==''
    engine.act(state,'update_item',{'line_id':state['basket'][0]['line_id'],'quantity':2})
    assert changes(engine.menu,before,state)=='خليت الكمية اثنين.'
    before=copy.deepcopy(state)
    engine.act(state,'update_item',{'line_id':state['basket'][0]['line_id'],'quantity':2})
    assert changes(engine.menu,before,state)==''

@pytest.mark.parametrize('text',['لا تقرأ الطلب','خلاص لا تأكد','كم المجموع؟','خلاص شيل الكرك','اذا كان جاهز غيره واقرأ الطلب','اكتب في الملاحظة واقرأ الطلب'])
def test_mixed_or_negated_completion_is_not_forced(text):
    assert not finished_order(text)

def test_summary_preserves_delivery_details_and_omits_pickup_fee(setup):
    engine,state=setup
    engine.act(state,'set_delivery_details',{'city':'الرياض','zone':'النرجس','street':'شارع الملك','building':'12'})
    summary=engine.summary(state)
    assert all(x in summary for x in ['الرياض','النرجس','شارع الملك','12','15.00','نأكد الطلب'])
    engine.act(state,'set_service',{'service':'pickup'})
    engine.act(state,'set_branch',{'branch_id':'ruh_narjis'})
    summary=engine.summary(state)
    assert 'رسوم' not in summary and 'النرجس' in summary and 'المجموع' in summary

def test_same_item_prefix_is_not_repeated():
    assert combine('بالنسبة لـشاي كرك، خليته بدون ثلج.','بالنسبة لـشاي كرك، الحجم صغير ولا كبير؟')=='بالنسبة لـشاي كرك، خليته بدون ثلج. الحجم صغير ولا كبير؟'

@pytest.mark.parametrize('utterance',['خلاص','اقرأ لي ملخص الطلب من جديد.','طيب رجعها استلام من فرع النرجس بالرياض واقرأ ملخص الطلب'])
@pytest.mark.parametrize('invalid_confirmation',[False,True])
def test_finished_order_gets_readback_without_another_sales_question(setup,monkeypatch,tmp_path,utterance,invalid_confirmation):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from sawt import v2_runtime as runtime
    from sawt.transactions import Transactions
    engine,state=setup
    engine.act(state,'set_service',{'service':'pickup'})
    engine.act(state,'set_branch',{'branch_id':'ruh_narjis'})
    tx=Transactions(tmp_path/'test.db',engine);sid,_=tx.create()
    tx.commit_bundle(sid,'seed',0,0,state,[],response={})
    monkeypatch.setattr(runtime,'tx',tx)
    from tests.test_tool_batches import call
    outputs=[]
    if 'رجعها' in utterance:
        outputs.extend([{'tool_calls':[call('set_service',{'service':'pickup'},'service')]},
                        {'tool_calls':[call('set_branch',{'branch_id':'ruh_narjis'},'branch')]}])
    outputs+=([{'tool_calls':[call('confirm',{},'invalid')]}] if invalid_confirmation else [])+[{'content':'باقي شي تضيفه؟'}]
    provider=SimpleNamespace(chat=AsyncMock(side_effect=outputs))
    result=asyncio.run(runtime.delegate(sid,utterance,'finished',0,voice_provider=provider))
    assert result['state']['quote'] and not result['state']['order_id']
    assert result['reply']==engine.summary(tx.load(sid)['state'])
    assert 'باقي شي' not in result['reply']

@pytest.mark.parametrize('reply',['طلبك شكشوكة عادي صاج. ممكن تعطيني المدينة والحي؟','طلبك الآن شكشوكة عادي صاج. باقي فقط عنوان التوصيل: في أي مدينة وأي حي؟'])
def test_repeated_saved_choices_do_not_repeat_basket_before_address(setup,monkeypatch,tmp_path,reply):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from sawt import v2_runtime as runtime
    from sawt.transactions import Transactions
    engine,state=setup
    engine.act(state,'set_service',{'service':'delivery'})
    tx=Transactions(tmp_path/'test.db',engine);sid,_=tx.create()
    tx.commit_bundle(sid,'seed',0,0,state,[],response={})
    monkeypatch.setattr(runtime,'tx',tx)
    provider=SimpleNamespace(chat=AsyncMock(return_value={'content':reply}))
    result=asyncio.run(runtime.delegate(sid,'قلت لك عادي صاج كمل','repeat',0,voice_provider=provider))
    assert result['reply']=='بأي مدينة وحي؟'
    assert result['state']['basket'][0]['options']==state['basket'][0]['options']


async def test_requested_readback_cannot_hide_a_failed_edit(setup,monkeypatch,tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from sawt import v2_runtime as runtime
    from sawt.transactions import Transactions
    from tests.test_tool_batches import call
    engine,state=setup
    engine.act(state,'set_service',{'service':'pickup'})
    engine.act(state,'set_branch',{'branch_id':'ruh_narjis'})
    tx=Transactions(tmp_path/'failed-edit.db',engine);sid,_=tx.create()
    tx.commit_bundle(sid,'seed',0,0,state,[],response={})
    monkeypatch.setattr(runtime,'tx',tx)
    provider=SimpleNamespace(supports_tool_batches=True,chat=AsyncMock(side_effect=[
        {'tool_calls':[call('update_item',{'line_id':'missing','quantity':2},'bad'),call('finish_draft',{},'finish')]},
        {'content':'ما قدرت أعدل الكمية.'}]))
    result=await runtime.delegate(sid,'خلها اثنين واقرأ الطلب','failed',0,voice_provider=provider)
    assert not result['state']['quote'] and not result['state']['order_id']
    assert result['state']['basket'][0]['quantity']==1
