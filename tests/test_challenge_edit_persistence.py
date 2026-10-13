"""Real state, menu and durable transactions. Scripted tools isolate invariants."""
import copy
import json
from pathlib import Path
import pytest
from sawt.domain import Engine, Menu, RuleError
from sawt.transactions import Transactions, Conflict
from sawt.experience import validate_experience
from sawt.hospitality_runtime import prepare_turn, commit_turn, verified_utterance, PreparedTurn
from sawt.hospitality_voice import delegated_start, make_voice_class
from sawt.recognition import AudioWindowError
from types import SimpleNamespace

class Planner:
    def __init__(self, *steps): self.steps=list(steps)
    async def chat(self, messages, tools):
        assert self.steps, 'Unexpected repair round'
        step=self.steps.pop(0)
        return step(messages) if callable(step) else step

def tools(*steps):
    return {'tool_calls':[{'id':str(i),'function':{'name':name,'arguments':json.dumps(args)}} for i,(name,args) in enumerate(steps)]}

@pytest.fixture
def saved(tmp_path):
    engine=Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv'))
    tx=Transactions(tmp_path/'orders.db',engine)
    sid,_=tx.create(experience=validate_experience('ash',version='v3',conversation_mode='model_led'))
    row=tx.load(sid);s=copy.deepcopy(row['state'])
    engine.act(s,'set_location',{'city':'الرياض','zone':'النرجس','address':'شارع الملك خالد، مبنى 15'})
    for item in ('sandwiches_07','sandwiches_08'):
        engine.act(s,'add_item',{'item_id':item,'quantity':2,'options':{'bread':['saj'],'meal':['sandwich'],'spice_level':['hot']},'notes':'بدون ثوم'})
    tx.commit_bundle(sid,'seed',row['epoch'],row['state']['revision'],s,[],'test fixture',{})
    return engine,tx,sid

async def act(saved, steps, text='عدل طلبي', replies=None):
    engine,tx,sid=saved
    planner=Planner(tools(*steps),*(replies or [{'content':'باقي شي تحتاجه؟'}]))
    p=await prepare_turn(engine,planner,tx.load(sid),text,conversation_mode='model_led')
    await commit_turn(tx,sid,'turn-'+str(tx.load(sid)['state']['revision']),p)
    return tx.load(sid)['state'],p

@pytest.mark.asyncio
@pytest.mark.parametrize('quoted',[False,True])
@pytest.mark.parametrize('edit',['remove','quantity','options','pickup','zone','unsupported','replace'])
async def test_edits_persist_and_invalidate_old_quote(saved,quoted,edit):
    engine,tx,sid=saved
    if quoted:
        row=tx.load(sid);s=copy.deepcopy(row['state']);engine.act(s,'checkout',{});s['quote']['presented']=True
        tx.commit_bundle(sid,'quote',row['epoch'],row['state']['revision'],s,[],'test-only played quote',{})
    before=tx.load(sid)['state'];line=before['basket'][0]['line_id'];other=copy.deepcopy(before['basket'][1])
    changes={
      'remove':[('remove_item',{'line_id':line})],
      'quantity':[('update_item',{'line_id':line,'quantity':3})],
      'options':[('update_item',{'line_id':line,'options':{'spice_level':['not_spicy']},'notes':'بدون صوص'})],
      'pickup':[('set_service',{'service':'pickup'}),('set_branch',{'branch_id':'jed_rawdah'})],
      'zone':[('set_location',{'city':'الرياض','zone':'الملقا','address':'شارع أنس، مبنى 4'})],
      'unsupported':[('set_location',{'city':'الدمام','zone':'الفيصلية','address':'شارع 4'})],
      'replace':[('replace_item',{'line_id':line,'item_id':'sandwiches_08'})],
    }
    state,p=await act(saved,changes[edit])
    assert state['quote'] is None and state['order_id'] is None
    assert state['revision']>before['revision'] and state['basket'][-1]==other
    view=engine.view(state)
    if edit=='remove': assert len(state['basket'])==1 and view['total']==5900
    if edit=='quantity': assert state['basket'][0]['quantity']==3 and view['total']==11300
    if edit=='options': assert state['basket'][0]['options']['bread']==['saj'] and state['basket'][0]['notes']=='بدون صوص'
    if edit=='pickup': assert state['location'] is None and state['delivery_details']=={} and view['delivery_fee']==0 and state['branch']=='jed_rawdah'
    if edit=='zone': assert state['branch']=='ruh_malqa' and view['delivery_fee']==1000 and view['eta_minutes']==30
    if edit=='unsupported': assert state['branch'] is None and state['location'] is None and view['issues']
    if edit=='replace': assert state['basket'][0]['line_id']==line and state['basket'][0]['item_id']=='sandwiches_08' and state['basket'][0]['options']==before['basket'][0]['options']
    with pytest.raises(RuleError): engine.act(state,'confirm',{},can_confirm=True)

@pytest.mark.asyncio
async def test_false_removed_claim_is_repaired_by_a_real_tool_then_committed(saved):
    engine,tx,sid=saved;line=tx.load(sid)['state']['basket'][0]['line_id']
    planner=Planner({'content':'تم استبعاده من الطلب.'},tools(('remove_item',{'line_id':line})),{'content':'شلت شاورما الدجاج.'})
    p=await prepare_turn(engine,planner,tx.load(sid),'احذف شاورما الدجاج',conversation_mode='model_led')
    assert p.requires_verification and p.speech_mode=='exact'
    await commit_turn(tx,sid,'delete',p)
    assert [x['item_id'] for x in tx.load(sid)['state']['basket']]==['sandwiches_08']
    assert len(p.operations)==1 and p.operations[0]['tool']=='remove_item'

@pytest.mark.asyncio
async def test_failed_removal_cannot_commit_a_success_claim(saved):
    engine,tx,sid=saved;before=tx.load(sid)['state']
    planner=Planner(tools(('remove_item',{'line_id':'missing'})),{'content':'حذفت الصنف.'},{'content':'أي صنف تقصد؟'})
    p=await prepare_turn(engine,planner,tx.load(sid),'احذفه',conversation_mode='model_led')
    await commit_turn(tx,sid,'clarify',p)
    assert tx.load(sid)['state']['basket']==before['basket'] and p.reply=='أي صنف تقصد؟'

@pytest.mark.parametrize('caption,verified',[('احذف','الطلب'),('شطب','الطلب'),('شيل الشاورما','الشاورما'),('remove the tea','the tea')])
def test_removal_cannot_disappear_during_secondary_transcription(caption,verified):
    with pytest.raises(AudioWindowError):
        verified_utterance(caption,verified,PreparedTurn({},'', [{'tool':'remove_item'}],0,0,caption,True,'exact'))

def test_missing_native_hint_keeps_all_unconsumed_caption_fragments():
    class Base:
        def __init__(self,*a,**k): self.pending=None;self.fragments=['أبغى شاورما دجاج',' بصاج',' حارة'];self.consumed=0
        def on_delegation(self,event): pass
    voice=make_voice_class(Base)('test',None,{'voice':'ash'})
    voice.latest_final_transcript='حارة';voice.on_delegation(SimpleNamespace())
    assert voice.delegation_start==0
    assert delegated_start(voice.fragments,0,'أبغى شاورما دجاج بصاج حارة')==0

@pytest.mark.asyncio
@pytest.mark.parametrize('claim',['تم تعديل الطلب.','غيرت الكمية.','أأكد لك الطلب؟','اضغط تأكيد'])
async def test_unexecuted_edit_or_free_confirmation_cannot_escape(saved,claim):
    engine,tx,sid=saved
    p=await prepare_turn(engine,Planner({'content':claim},{'content':'أي تعديل تبيه؟'}),tx.load(sid),'وش صار؟',conversation_mode='model_led')
    assert p.reply=='أي تعديل تبيه؟' and not p.state['quote']

@pytest.mark.asyncio
async def test_explicit_staff_request_requires_persisted_case_without_losing_draft(saved):
    engine,tx,sid=saved;before=copy.deepcopy(tx.load(sid)['state']['basket'])
    def offer(messages):
        result=json.loads(next(m['content'] for m in reversed(messages) if m['role']=='tool'))
        return tools(('offer_resolution',{'case_id':result['case']['id'],'resolution':'staff_review'}))
    p=await prepare_turn(engine,Planner({'content':'وش المشكلة؟'},tools(('open_support_case',{'category':'general','details':'أبي أكلم مسؤول'})),offer),tx.load(sid),'عندي شكوى أبي أكلم مسؤول',conversation_mode='model_led')
    await commit_turn(tx,sid,'support',p)
    state=tx.load(sid)['state']
    assert state['basket']==before and len(state['hospitality']['cases'])==1
    assert state['hospitality']['pending_resolution']['kind']=='staff_review'


def test_native_suffix_does_not_discard_uncommitted_order():
    fragments=['أبي اثنين شاورما دجاج', ' صاج بدون حار', ' وواحد شاورما لحم', ' صاج حار', ' اقرأ ملخص الطلب']
    assert delegated_start(fragments,0,'اقرأ ملخص الطلب')==0
    assert delegated_start(fragments,0,'صاج حار اقرأ ملخص الطلب')==0
    assert delegated_start(fragments,2,'اقرأ ملخص الطلب')==2


def test_claim_guards_require_saved_selection_and_resolved_support():
    from sawt.reply_evidence import unsupported_claim
    before={'basket':[]}
    assert unsupported_claim(before,before,'تم اختيار بيتزا دجاج كبير')
    pending={'basket':[],'hospitality':{'pending_resolution':{'id':'pending'},'ledger':[]}}
    assert unsupported_claim(pending,pending,'تم تسجيل موافقتك على استرجاع قيمة الصنف')
    from sawt.hospitality import resolution_confirmation
    assert not resolution_confirmation('نعم أوافق على الاسترجاع','staff_review')
    assert resolution_confirmation('نعم أوافق على التحويل','staff_review')
