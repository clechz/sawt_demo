import asyncio
import copy
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from sawt.domain import Engine, Menu, new_state, RuleError
from sawt.transactions import StagedEngine, Transactions
from sawt.choices import short_choice
from sawt.agent import Agent

@pytest.fixture
def setup():
    engine=Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv'))
    return StagedEngine(engine,check_choices=True),new_state()

def add(engine,state,item,text,options=None):
    return engine.act(state,'add_item',{'item_id':item,'quantity':1,'options':options or {},'notes':''},utterance=text)

def test_categories_cover_entire_menu_without_mutation(setup):
    engine,state=setup
    categories=engine.act(state,'list_categories',{})['categories']
    assert len(categories)==12
    assert sum(x['count'] for x in categories)==len(engine.menu.items)
    assert state['revision']==0 and not state['basket']


@pytest.mark.parametrize('item',['sandwiches_07','sandwiches_08'])
def test_ambiguous_shawarma_cannot_silently_choose_a_protein(setup,item):
    engine,state=setup
    with pytest.raises(RuleError):add(engine,state,item,'سندويش شاورما')
    assert not state['basket'] and state['revision']==0


def test_explicit_shawarma_protein_is_saved_before_other_choices(setup):
    engine,state=setup
    add(engine,state,'sandwiches_07','أبي شاورما دجاج')
    assert state['basket'][0]['item_id']=='sandwiches_07'

@pytest.mark.parametrize('text',['أبغى فول وتميس وقلابة','تميس عادي','تميس بدون جبن'])
def test_generic_tamees_never_becomes_cheese(setup,text):
    engine,state=setup
    with pytest.raises(RuleError):add(engine,state,'breakfast_04',text)
    assert not state['basket'] and state['revision']==0

def test_honey_replacement_keeps_line_quantity_notes_size_and_other_items(setup):
    engine,state=setup
    add(engine,state,'breakfast_02','فول حجازي حجم عادي وخبز صاج',{'portion':['regular'],'bread':['saj']})
    add(engine,state,'breakfast_03','قلابة حجم عادي وخبز صاج',{'portion':['regular'],'bread':['saj']})
    add(engine,state,'breakfast_04','تميس بالجبن عادي صاج',{'portion':['regular'],'bread':['saj']})
    line=state['basket'][-1];line['quantity']=2;line['notes']='تغليف منفصل'
    untouched=copy.deepcopy(state['basket'][:2]);line_id=line['line_id']
    engine.act(state,'replace_item',{'line_id':line_id,'item_id':'breakfast_05','options':{'bread':['brown']}},utterance='تميس بالعسل خبز اسمري')
    assert state['basket'][:2]==untouched
    assert line['line_id']==line_id and line['item_id']=='breakfast_05'
    assert line['quantity']==2 and line['notes']=='تغليف منفصل'
    assert line['options']=={'portion':['regular'],'bread':['brown']}

def test_invalid_replacement_is_atomic(setup):
    engine,state=setup
    add(engine,state,'breakfast_04','تميس بالجبن عادي صاج',{'portion':['regular'],'bread':['saj']})
    original=copy.deepcopy(state)
    with pytest.raises(RuleError):engine.act(state,'replace_item',{'line_id':state['basket'][0]['line_id'],'item_id':'breakfast_05','quantity':0},utterance='بدلها تميس بالعسل')
    assert state==original

def test_repeated_short_answer_targets_only_missing_size(setup):
    engine,state=setup
    add(engine,state,'breakfast_02','فول حجازي عادي صاج',{'portion':['regular'],'bread':['saj']})
    add(engine,state,'breakfast_05','تميس بالعسل أسمر',{'bread':['brown']})
    choice=short_choice(engine.menu,state,'حجم عادي عادي')
    assert choice=={'line_id':state['basket'][1]['line_id'],'options':{'portion':['regular']}}
    engine.act(state,'update_item',choice,utterance='حجم عادي عادي')
    assert not engine.view(state)['basket'][1]['missing']

def test_unconfirmed_registration_claim_is_replaced_with_missing_fields(setup):
    engine,state=setup
    agent=Agent(engine,None)
    _,reply=agent.finish(state,'تمام صح','طلبك مسجل وتستلمه متى ما وصلت',[])
    assert 'طلبك باقي ما تأكد' in reply['reply']
    assert state['order_id'] is None

@pytest.mark.parametrize('invitation',['هل ترغب بالتأكيد؟','ودك تأكد؟','تبي تأكد؟'])
def test_free_confirmation_invitation_requires_exact_readback(setup,invitation):
    engine,state=setup
    add(engine,state,'breakfast_01','شكشوكة عادي صاج',{'portion':['regular'],'bread':['saj']})
    engine.act(state,'set_service',{'service':'pickup'},utterance='استلام')
    engine.act(state,'set_branch',{'branch_id':'ruh_narjis'})
    _,reply=Agent(engine,None).finish(state,'خلاص',invitation,[])
    assert state['quote'] and not state['quote']['presented']
    assert state['order_id'] is None and reply['reply']==engine.engine.summary(state)
    assert reply['events'][-1]['source']=='readback_guard'

def test_readback_correction_reports_current_epoch_and_commits(monkeypatch,tmp_path,setup):
    from sawt import v2_runtime as runtime
    staged,state=setup;engine=staged.engine
    tx=Transactions(tmp_path/'calls.sqlite3',engine)
    sid,_=tx.create()
    engine.act(state,'set_service',{'service':'pickup'})
    engine.act(state,'set_branch',{'branch_id':'ruh_narjis'})
    add(staged,state,'breakfast_01','شكشوكة عادي صاج',{'portion':['regular'],'bread':['saj']})
    engine.act(state,'checkout',{})
    assert state['quote'], 'fixture must be ready for a real readback'
    tx.commit_bundle(sid,'seed',0,0,state,[],response={})
    monkeypatch.setattr(runtime,'tx',tx)
    progress=AsyncMock()
    result=asyncio.run(runtime.delegate(sid,'كبير','change',0,progress=progress))
    assert result['state']['basket'][0]['options']['portion']==['large']
    assert result['state']['order_id'] is None
    assert [call.args for call in progress.await_args_list]==[('understanding',1),('update_item',1),('saving',1)]
