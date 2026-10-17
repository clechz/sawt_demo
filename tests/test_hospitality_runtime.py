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

def tool(tool_name,**args):
    return {'id':tool_name,'function':{'name':tool_name,'arguments':json.dumps(args,ensure_ascii=False)}}
def calls(*items): return {'content':None,'tool_calls':list(items)}

@pytest.mark.asyncio
async def test_name_claim_repairs_with_persisted_name_then_checkout(engine, tmp_path):
    tx=Transactions(tmp_path/'names.db',engine)
    sid,_=tx.create(require_customer_name=True)
    row=tx.load(sid)
    state=row['state']
    engine.act(state,'set_service',{'service':'pickup'})
    engine.act(state,'set_branch',{'branch_id':'ruh_narjis'})
    item=engine.menu.get('breakfast_01')
    options={gid:list(g['options'])[:g['min']] for gid,g in item['groups'].items() if g['min']}
    engine.act(state,'add_item',{'item_id':item['id'],'quantity':1,'options':options,'notes':''})
    planner=Scripted({'content':'الطلب باسم: عبدالله. تبيني أقول لك السعر؟'},
        calls(tool('set_customer_name',name='عبدالله'),tool('checkout')))
    prepared=await prepare_turn(engine,planner,row,'الطلب باسم عبدالله، اقرأ ملخص الطلب.',conversation_mode='model_led')
    assert planner.calls==2
    assert prepared.state['customer_name']=='عبدالله'
    assert prepared.state['quote'] and not prepared.state['quote']['presented']
    assert not prepared.state['order_id']
    assert 'عبدالله' in prepared.reply

def test_missing_name_question_is_not_a_saved_name_claim():
    from sawt.reply_evidence import unsupported_claim
    state=new_state()
    assert unsupported_claim(state,state,'الطلب باسم مين؟') is None
    assert unsupported_claim(state,state,'الطلب باسم: عبدالله')

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

def test_native_hint_cannot_discard_unconsumed_caption_context():
    fragments=['هلا والله',' كيفك',' أبي شكشوكة',' كبير تميس']
    assert delegated_start(fragments,0,'أبي شكشوكة كبير تميس')==0
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


@pytest.mark.asyncio
async def test_spoken_refund_approval_changes_ledger(engine):
    from sawt.hospitality import resolution_confirmation
    from sawt.domain import explicit_confirmation
    state=new_state();state['hospitality']=new_hospitality(engine,'missing_item')
    adapter=HospitalityEngine(engine,state)
    case=adapter.act(state,'open_support_case',{'category':'missing_item','details':'ناقص','order_id':'S-DEMO7001','line_id':'seed-line-1'})['case']
    adapter.act(state,'offer_resolution',{'case_id':case['id'],'resolution':'refund_item'})
    state['hospitality']['pending_resolution']['presented']=True
    text='نعم أوافق على الاسترجاع'
    assert resolution_confirmation(text) and not explicit_confirmation(text)
    assert not resolution_confirmation(text+' بس غير المبلغ')
    prepared=await prepare_turn(engine,Scripted(),{'state':state,'epoch':0},text,conversation_mode='model_led')
    assert len(prepared.state['hospitality']['ledger'])==1
    assert prepared.state['hospitality']['ledger'][0]['amount_halalas']==3000
    assert prepared.requires_verification


@pytest.mark.parametrize('text',['خل الخبز برمو صاج','غير الخبز للأسمر','أقصد خبز أسمر بدل الصاج'])
def test_missed_correction_still_requires_audio_check(text):
    assert requires_audio_verification([],text)


def test_spacing_only_negation_reconciles_without_inventing_words():
    from sawt.recognition import reconcile_transcripts,check_recognition
    caption='خل الخبز برمو صاج'
    heard='خل الخبز بر مو صاج'
    assert reconcile_transcripts(caption,heard)==heard
    check_recognition(caption,heard)
    check_recognition(heard,caption)
    p=PreparedTurn({},'',[],0,0,caption,True,'live')
    assert verified_utterance(caption,heard,p)==heard
    with pytest.raises(AudioWindowError):
        verified_utterance('خل الخبز بر صاج',heard,p)


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['نعم ارفع','نعم ارفع التفاصيل للمسؤول','ارفع التفاصيل للمسؤول','نعم ارفعها'])
async def test_staff_review_approval_persists_only_after_heard_offer(engine,text):
    from sawt.hospitality import resolution_confirmation
    state=new_state();state['hospitality']=new_hospitality(engine)
    adapter=HospitalityEngine(engine,state)
    case=adapter.act(state,'open_support_case',{'category':'general','details':'أبي موظف عندي شكوى'})['case']
    adapter.act(state,'offer_resolution',{'case_id':case['id'],'resolution':'staff_review'})
    assert not resolution_confirmation(text,'refund_item')
    assert not resolution_confirmation(text+' بس غير التفاصيل','staff_review')
    unheard=await prepare_turn(engine,Scripted(),{'state':state,'epoch':0},text,conversation_mode='model_led')
    assert not unheard.state['hospitality']['cases'][0]['resolution']
    state['hospitality']['pending_resolution']['presented']=True
    prepared=await prepare_turn(engine,Scripted(),{'state':state,'epoch':0},text,conversation_mode='model_led')
    assert prepared.state['hospitality']['cases'][0]['status']=='review_requested'
    assert prepared.state['hospitality']['cases'][0]['resolution']['simulated']
    assert prepared.state['hospitality']['pending_resolution'] is None
    assert prepared.requires_verification


def test_false_staff_review_claim_is_rejected(engine):
    from sawt.reply_evidence import unsupported_claim
    state=new_state();state['hospitality']=new_hospitality(engine)
    assert unsupported_claim(state,state,'تم رفع الشكوى للمسؤول لمراجعتها.')


@pytest.mark.asyncio
@pytest.mark.parametrize('acceptance',['إي أكد','إي، أكد الطلب','أيوه أكد','إيي أكد','إيييه أكد الطلب'])
async def test_saudi_acceptance_after_readback_persists_one_order(engine,tmp_path,acceptance):
    tx=Transactions(tmp_path/'acceptance.db',engine)
    sid,_=tx.create(require_customer_name=True)
    row=tx.load(sid);s=row['state']
    for action,args in [('set_service',{'service':'pickup'}),('set_branch',{'branch_id':'ruh_narjis'}),('set_customer_name',{'name':'عبدالله'}),('add_item',{'item_id':'sandwiches_07','quantity':1,'options':{'bread':['saj'],'meal':['sandwich'],'spice_level':['not_spicy']},'notes':'بدون ثوم'})]:
        engine.act(s,action,args)
    engine.act(s,'checkout',{})
    s['quote']['presented']=True
    with tx.connect() as db:db.execute('UPDATE calls SET state=? WHERE id=?',(json.dumps(s),sid))
    revision=s['revision'];planner=Scripted()
    prepared=await prepare_turn(engine,planner,tx.load(sid),acceptance,conversation_mode='model_led')
    assert planner.calls==0
    assert [op['tool'] for op in prepared.operations]==['confirm']
    assert prepared.requires_verification
    assert verified_utterance(acceptance,'إيه أكد',prepared)=='إيه أكد'
    await commit_turn(tx,sid,'accept',prepared)
    saved=tx.load(sid)['state']
    assert saved['order_id'] and saved['revision']==revision
    assert saved['basket'][0]['notes']=='بدون ثوم'
    assert saved['customer_name']=='عبدالله'
    assert saved['hospitality']['orders'][saved['order_id']]['total_halalas']==1800
    with tx.connect() as db:assert db.execute('SELECT COUNT(*) FROM placed_orders WHERE session_id=?',(sid,)).fetchone()[0]==1


@pytest.mark.asyncio
async def test_truncated_garlic_verification_cannot_commit_note_deletion(engine,tmp_path):
    tx=Transactions(tmp_path/'garlic.db',engine);sid,_=tx.create()
    row=tx.load(sid);s=row['state']
    engine.act(s,'add_item',{'item_id':'sandwiches_07','quantity':1,'options':{},'notes':'بدون ثوم'})
    with tx.connect() as db:db.execute('UPDATE calls SET state=? WHERE id=?',(json.dumps(s),sid))
    before=copy.deepcopy(tx.load(sid)['state'])
    p=PreparedTurn({},'', [{'tool':'update_item','args':{'notes':''}}],0,s['revision'],'',True,'live')
    with pytest.raises(AudioWindowError,match='Incomplete exclusion'):
        verified_utterance('لا أبغى أحط ملاحظة بدون ثوم','لا بروح حط ملاحظة بدون',p)
    assert tx.load(sid)['state']==before


@pytest.mark.parametrize('action,reply',[
 ('remove_item','شلت شاورما اللحم.')])
def test_saved_simple_corrections_keep_live_voice(action,reply):
    assert result_mode(new_state(),[{'tool':action}],reply,model_led=True)=='live'

@pytest.mark.parametrize('action,reply',[
 ('confirm','تأكد طلبك.'),('replace_item','بدلت اللحم بالدجاج.'),('remove_item','المجموع 54 ريال.'),
 ('ask_choice','كيف تبي درجة الحرارة؟'),('accept_resolution','رجعت المبلغ.')])
def test_natural_voice_never_relaxes_exact_commitments(action,reply):
    assert result_mode(new_state(),[{'tool':action}],reply,model_led=True)=='exact'

def test_conversational_summary_preserves_all_order_facts(engine):
    s=new_state()
    for action,args in [('set_service',{'service':'pickup'}),('set_branch',{'branch_id':'ruh_narjis'}),('set_customer_name',{'name':'عبدالله'}),('add_item',{'item_id':'sandwiches_07','quantity':2,'options':{'bread':['saj'],'meal':['sandwich'],'spice_level':['not_spicy']},'notes':'بدون ثوم'})]:
        engine.act(s,action,args)
    before=copy.deepcopy(s);summary=engine.summary(s)
    assert s==before
    for detail in ['عبدالله','2 شاورما دجاج','صاج','بدون شطة','بدون ثوم','36.00','النرجس','20','نأكد الطلب؟']:
        assert detail in summary
    assert 'ملاحظات:' not in summary and '2 من' not in summary
