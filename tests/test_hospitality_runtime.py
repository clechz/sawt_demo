"""Offline integration: real domain and durable transactions, scripted planner only."""
import copy
import json
from pathlib import Path
import pytest
from sawt.domain import Engine, Menu, new_state, RuleError
from sawt.experience import validate_experience
from sawt.hospitality import HospitalityEngine, new_hospitality
from sawt.hospitality_runtime import (prepare_turn, commit_turn, mark_proposal_presented,
    requires_audio_verification, verified_utterance, result_mode, PreparedTurn)
from sawt.hospitality_voice import delegated_start
from sawt.recognition import AudioWindowError
from sawt.transactions import Transactions, Conflict

ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture
def engine(): return Engine(Menu(ROOT/'data/restaurant-menu-complex.csv'))

class Scripted:
    def __init__(self,*steps): self.steps=list(steps);self.calls=0
    async def chat(self,messages,tools):
        assert self.steps,'Unexpected additional planner round'
        self.calls+=1
        step=self.steps.pop(0)
        return step(messages) if callable(step) else step

def tool(name,**args):
    return {'id':name,'function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}}
def calls(*items): return {'content':None,'tool_calls':list(items)}

@pytest.mark.asyncio
async def test_compound_draft_changes_and_next_question_in_one_round(engine):
    state=new_state()
    planner=Scripted(calls(tool('set_service',service='pickup'),
        tool('set_branch',branch_id='ruh_narjis'),
        tool('add_item',item_id='breakfast_01',quantity=2,options={},notes=''),
        tool('finish_draft')))
    p=await prepare_turn(engine,planner,{'state':state,'epoch':0},'أبي شكشوكة عدد اثنين واستلام من فرع النرجس')
    assert planner.calls==1 and p.state['basket'][0]['quantity']==2
    assert p.state['branch']=='ruh_narjis' and p.state['pending_choice']
    assert p.requires_verification and not state['basket']

@pytest.mark.asyncio
async def test_full_support_journey_commits_refund_once_and_preserves_order(engine,tmp_path):
    tx=Transactions(tmp_path/'calls.db',engine)
    sid,_=tx.create(experience=validate_experience('ash','missing_item'))
    def offer(messages):
        result=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
        return calls(tool('offer_resolution',case_id=result['case']['id'],resolution='refund_item'))
    planner=Scripted(calls(tool('open_support_case',category='missing_item',details='الشكشوكة ناقصة',
        order_id='S-DEMO7001',line_id='seed-line-1')),offer)
    row=tx.load(sid)
    p=await prepare_turn(engine,planner,row,'الشكشوكة ناقصة، أبي استرجاع قيمتها')
    assert p.state['hospitality']['ledger']==[] and p.speech_mode=='exact'
    await commit_turn(tx,sid,'offer',p)
    proposal=p.state['hospitality']['pending_resolution']
    # Test-only simulation of completed app playback, not a human listening check.
    mark_proposal_presented(tx,sid,proposal['id'],row['epoch'])
    p=await prepare_turn(engine,Scripted(),tx.load(sid),'نعم')
    assert p.requires_verification
    assert verified_utterance('نعم','ايه',p)=='ايه'
    result=await commit_turn(tx,sid,'accept',p)
    h=tx.load(sid)['state']['hospitality']
    assert len(h['ledger'])==1 and h['ledger'][0]['amount_halalas']==3000
    assert h['orders']['S-DEMO7001']['total_halalas']==4500
    assert tx.replay_bundle(sid,'accept','نعم')==result
    with pytest.raises(Exception): await commit_turn(tx,sid,'accept',p)
    assert len(tx.load(sid)['state']['hospitality']['ledger'])==1

@pytest.mark.asyncio
async def test_unheard_support_yes_replays_offer_without_financial_action(engine,tmp_path):
    tx=Transactions(tmp_path/'calls.db',engine)
    sid,_=tx.create(experience=validate_experience('cedar','missing_item'))
    row=tx.load(sid);s=copy.deepcopy(row['state']);a=HospitalityEngine(engine,s)
    case=a.act(s,'open_support_case',{'category':'missing_item','details':'ناقص','order_id':'S-DEMO7001','line_id':'seed-line-1'})['case']
    a.act(s,'offer_resolution',{'case_id':case['id'],'resolution':'refund_item'})
    tx.commit_bundle(sid,'offer',row['epoch'],row['state']['revision'],s,a.operations,'refund',{})
    p=await prepare_turn(engine,Scripted(),tx.load(sid),'نعم')
    assert p.speech_mode=='exact' and not p.requires_verification
    assert p.state['hospitality']['ledger']==[]

@pytest.mark.parametrize('heard',['امم','لا','نعم بس غيرها','', 'whatever'])
def test_critical_confirmation_must_survive_actual_transcript(heard):
    p=PreparedTurn({},'', [{'tool':'accept_resolution'}],0,0,'نعم',True,'exact')
    with pytest.raises(AudioWindowError): verified_utterance('نعم',heard,p)

@pytest.mark.parametrize('action,text,expected',[
    ('restaurant_info','متى تقفلون',False),('open_support_case','عندي شكوى',False),
    ('remove_item','شيل الشاورما',True),('replace_item','بدلها لحم',True),
    ('set_delivery_details','شارع الملك فهد',True),('confirm','نعم',True),
    ('update_item','بدون شطة',True),('update_item','اثنين',True),('update_item','كبير',False)])
def test_verification_is_risk_specific(action,text,expected):
    assert requires_audio_verification([{'tool':action,'args':{}}],text)==expected

def test_native_open_turn_discards_old_social_caption_context():
    fragments=['هلا والله',' كيفك',' أبي شكشوكة',' كبير تميس']
    assert delegated_start(fragments,0,'أبي شكشوكة كبير تميس')==2
    assert delegated_start(fragments,0,'unmatched')==0
    assert delegated_start(fragments,3,'كبير تميس')==3

@pytest.mark.asyncio
async def test_failed_plan_does_not_mutate_original(engine):
    state=new_state()
    planner=Scripted(calls(tool('add_item',item_id='invalid',quantity=1,options={},notes='')),{'content':'وش الصنف اللي تقصده؟'})
    p=await prepare_turn(engine,planner,{'state':state,'epoch':0},'أبغى صحن')
    assert p.state['basket']==[] and state['basket']==[]

@pytest.mark.asyncio
async def test_question_cannot_silently_select_delivery(engine):
    state=new_state()
    planner=Scripted(calls(tool('set_service',service='delivery')),{'content':'تبيه توصيل ولا تستلمه؟'})
    p=await prepare_turn(engine,planner,{'state':state,'epoch':0},'كيف أطلب؟')
    assert p.state['service'] is None

@pytest.mark.asyncio
async def test_other_topic_expires_old_support_acceptance(engine):
    state=new_state();state['hospitality']=new_hospitality(engine,'missing_item')
    a=HospitalityEngine(engine,state)
    c=a.act(state,'open_support_case',{'category':'missing_item','details':'ناقص','order_id':'S-DEMO7001','line_id':'seed-line-1'})['case']
    a.act(state,'offer_resolution',{'case_id':c['id'],'resolution':'refund_item'})
    state['hospitality']['pending_resolution']['presented']=True
    p=await prepare_turn(engine,Scripted(calls(tool('restaurant_info',topic='hours')),{'content':'نقفل الساعة اثنا عشر بالليل.'}),{'state':state,'epoch':0},'متى تقفلون؟')
    assert p.state['hospitality']['pending_resolution'] is None
    assert not p.state['hospitality']['ledger']

def test_unknown_policy_does_not_invent_allergens(engine):
    state=new_state();state['hospitality']=new_hospitality(engine)
    value=HospitalityEngine(engine,state).act(state,'restaurant_info',{'topic':'allergens'})
    assert value['source']=='menu_has_no_allergen_data' and 'ما أقدر أضمن' in value['answer']
