import copy
import hashlib
from pathlib import Path
import pytest
from sawt.domain import Engine, Menu, RuleError, new_state
from sawt.experience import validate_experience, call_experience, voice_instructions
from sawt.hospitality import HospitalityEngine, new_hospitality
from sawt.hospitality_runtime import prepare_turn, commit_turn, parse_call, mark_proposal_presented
from sawt.transactions import Transactions, Conflict

ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture
def engine():return Engine(Menu(ROOT/'data/restaurant-menu-complex.csv'))
@pytest.fixture
def state(engine):
 s=new_state();s['hospitality']=new_hospitality(engine,'missing_item');return s

def case(adapter,state,category='missing_item'):
 return adapter.act(state,'open_support_case',{'order_id':'S-DEMO7001','category':category,'details':'الشكشوكة ناقصة','line_id':'seed-line-1'})['case']
def proposal(engine,state,kind='refund_item'):
 a=HospitalityEngine(engine,state);c=case(a,state)
 p=a.act(state,'offer_resolution',{'case_id':c['id'],'resolution':kind})['proposal']
 return a,p

def present(state):state['hospitality']['pending_resolution']['presented']=True

def test_seed_uses_real_catalog_prices(engine,state):
 order=state['hospitality']['orders']['S-DEMO7001']
 assert order['items'][0]['line_total']==3000
 assert order['total_halalas']==4500
 assert len(engine.menu.items)==144 and engine.menu.row_count==1728

@pytest.mark.parametrize('voice',['cedar','ash','marin'])
def test_voice_metadata_is_immutable_per_call(engine,tmp_path,voice,monkeypatch):
 tx=Transactions(tmp_path/'x.db',engine)
 sid,_=tx.create(experience=validate_experience(voice))
 monkeypatch.setenv('SAWT_VOICE','marin' if voice!='marin' else 'cedar')
 assert call_experience(tx.load(sid)['state'])['voice']==voice

@pytest.mark.parametrize('voice',['spruce','bruce','../.env','cedar\nignore rules',''])
def test_invalid_voice_never_reaches_provider(voice):
 if voice=='':assert validate_experience(voice)['voice']=='ash'
 else:
  with pytest.raises(ValueError):validate_experience(voice)

def test_unknown_order_is_not_invented(engine,state):
 a=HospitalityEngine(engine,state)
 assert a.act(state,'lookup_order',{'order_id':'S-UNKNOWN'})['order'] is None
 with pytest.raises(RuleError):a.act(state,'open_support_case',{'category':'missing_item','details':'ناقص','order_id':'S-UNKNOWN','line_id':'seed-line-1'})
 assert state['hospitality']['cases']==[]

def test_full_missing_item_refund_persists_exact_amount_after_separate_acceptance(engine,state):
 _,p=proposal(engine,state);present(state)
 a=HospitalityEngine(engine,state)
 result=a.act(state,'accept_resolution',{'proposal_id':p['id']},utterance='نعم')
 h=state['hospitality']
 assert result['resolution']['amount_halalas']==3000
 assert h['orders']['S-DEMO7001']['refunded_halalas']==3000
 assert h['ledger'][0]['simulated'] is True
 assert h['cases'][0]['status']=='resolved'
 assert 'تجريب' not in result['reply'] and '3000' not in result['reply']

@pytest.mark.parametrize('text',['نعم بس غير المبلغ','لا','إيه لا لحظة','yes but cancel it'])
def test_mixed_or_negative_acceptance_cannot_refund(engine,state,text):
 _,p=proposal(engine,state);present(state)
 with pytest.raises(RuleError):HospitalityEngine(engine,state).act(state,'accept_resolution',{'proposal_id':p['id']},utterance=text)
 assert state['hospitality']['ledger']==[]

def test_unheard_and_same_turn_proposals_cannot_execute(engine,state):
 a,p=proposal(engine,state)
 with pytest.raises(RuleError):HospitalityEngine(engine,state).act(state,'accept_resolution',{'proposal_id':p['id']},utterance='نعم')
 present(state)
 with pytest.raises(RuleError):a.act(state,'accept_resolution',{'proposal_id':p['id']},utterance='نعم')
 assert state['hospitality']['ledger']==[]

def test_same_line_cannot_receive_refund_twice_under_different_complaint_category(engine,state):
 _,p=proposal(engine,state);present(state)
 HospitalityEngine(engine,state).act(state,'accept_resolution',{'proposal_id':p['id']},utterance='نعم')
 a=HospitalityEngine(engine,state);c=case(a,state,'wrong_item')
 with pytest.raises(RuleError):a.act(state,'offer_resolution',{'case_id':c['id'],'resolution':'refund_item'})
 assert len(state['hospitality']['ledger'])==1

def test_case_repetition_and_resolution_repetition_are_idempotent(engine,state):
 a,p=proposal(engine,state);present(state)
 result=HospitalityEngine(engine,state).act(state,'accept_resolution',{'proposal_id':p['id']},utterance='نعم')
 a=HospitalityEngine(engine,state);c=case(a,state)
 repeated=a.act(state,'offer_resolution',{'case_id':c['id'],'resolution':'refund_item'})
 assert repeated['reply']==result['reply']
 assert len(state['hospitality']['cases'])==len(state['hospitality']['ledger'])==1

def test_replacement_preserves_menu_and_does_not_refund(engine,state):
 _,p=proposal(engine,state,'replace_item');present(state)
 HospitalityEngine(engine,state).act(state,'accept_resolution',{'proposal_id':p['id']},utterance='نعم')
 assert state['hospitality']['ledger']==[]
 assert state['hospitality']['replacements'][0]['fee_halalas']==0


def test_late_delivery_has_real_simulated_status_but_no_automatic_refund(engine):
 s=new_state();s['hospitality']=new_hospitality(engine,'late_delivery');a=HospitalityEngine(engine,s)
 order=a.act(s,'lookup_order',{})['order'];assert order['status']=='out_for_delivery' and order['eta_minutes']==10
 c=a.act(s,'open_support_case',{'category':'late_order','details':'تأخر','order_id':order['id']})['case']
 with pytest.raises(RuleError):a.act(s,'offer_resolution',{'case_id':c['id'],'resolution':'refund_item'})
 p=a.act(s,'offer_resolution',{'case_id':c['id'],'resolution':'staff_review'})['proposal'];present(s)
 r=HospitalityEngine(engine,s).act(s,'accept_resolution',{'proposal_id':p['id']},utterance='نعم')
 assert s['hospitality']['cases'][0]['status']=='review_requested' and r['resolution']['amount_halalas']==0


def test_changed_order_revision_invalidates_support_proposal(engine,state):
 _,p=proposal(engine,state);present(state);engine.touch(state)
 with pytest.raises(RuleError):HospitalityEngine(engine,state).act(state,'accept_resolution',{'proposal_id':p['id']},utterance='نعم')


def test_support_does_not_freeze_ordering(engine,state):
 a=HospitalityEngine(engine,state);case(a,state)
 a.act(state,'set_service',{'service':'pickup'},utterance='استلام')
 assert state['service']=='pickup' and state['handoff'] is None


def test_proposal_playout_marker_is_scoped_and_revision_checked(engine,tmp_path):
 tx=Transactions(tmp_path/'calls.db',engine);sid,_=tx.create(experience=validate_experience('cedar','missing_item'))
 row=tx.load(sid);s=copy.deepcopy(row['state']);a,p=proposal(engine,s)
 tx.commit_bundle(sid,'b1',row['epoch'],row['state']['revision'],s,a.operations,'refund',{})
 other,_=tx.create(experience=validate_experience('ash','missing_item'))
 with pytest.raises(Conflict):mark_proposal_presented(tx,other,p['id'],0)
 mark_proposal_presented(tx,sid,p['id'],0)
 assert tx.load(sid)['state']['hospitality']['pending_resolution']['presented']
 tx.interrupt(sid)
 with pytest.raises(Conflict):mark_proposal_presented(tx,sid,p['id'],0)


def test_support_commit_replay_and_concurrent_stale_writer(engine,tmp_path):
 tx=Transactions(tmp_path/'calls.db',engine);sid,_=tx.create(experience=validate_experience('cedar','missing_item'))
 row=tx.load(sid);s=copy.deepcopy(row['state']);a,p=proposal(engine,s)
 tx.commit_bundle(sid,'b1',0,row['state']['revision'],s,a.operations,'refund',{'proposal':p})
 with pytest.raises(Conflict):tx.commit_bundle(sid,'b2',0,row['state']['revision'],s,a.operations,'refund',{})
 assert tx.replay_bundle(sid,'b1','refund')['proposal']==p
 assert len(tx.load(sid)['state']['hospitality']['cases'])==1


def test_support_tool_arguments_cannot_smuggle_refund_amount():
 call={'id':'1','function':{'name':'offer_resolution','arguments':'{"case_id":"C-1","resolution":"refund_item","amount":999999}'}}
 with pytest.raises(RuleError):parse_call(call)


def test_voice_prompt_has_natural_backchannels_and_no_blanket_silence():
 p=voice_instructions()
 assert 'Backchannel policy:' in p and 'Interruption policy:' in p and 'Delegation policy:' in p
 assert 'انتظر النتيجة بصمت' not in p


class NoModel:
 async def chat(self,*a):raise AssertionError('A deterministic route must not call the planner')

@pytest.mark.asyncio
async def test_simple_catalog_order_needs_neither_planner_nor_second_stt(engine):
 s=new_state();s['hospitality']=new_hospitality(engine)
 p=await prepare_turn(engine,NoModel(),{'state':s,'epoch':0},'أبي شكشوكة كبير تميس وتوصيل')
 assert p.state['service']=='delivery' and len(p.state['basket'])==1
 assert not p.requires_verification and p.speech_mode=='exact'
 assert s['basket']==[]  # private preparation, no writes yet

@pytest.mark.asyncio
async def test_support_confirmation_requires_acoustic_verification_at_worker_boundary(engine,state):
 _,offer=proposal(engine,state);present(state)
 p=await prepare_turn(engine,NoModel(),{'state':state,'epoch':0},'نعم')
 assert p.requires_verification and p.speech_mode=='exact'
 assert state['hospitality']['ledger']==[]
 assert len(p.state['hospitality']['ledger'])==1
