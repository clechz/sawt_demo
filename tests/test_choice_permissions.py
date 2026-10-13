"""Contract tests; scripted interpretation is not a Saudi-language evaluation."""
import copy
from pathlib import Path
import json
import pytest
from sawt.domain import Engine, Menu, new_state, RuleError
from sawt.choice_permissions import ModelLedEngine, permission_view
from sawt.hospitality_runtime import prepare_turn, commit_turn
from sawt.transactions import Transactions, Conflict

@pytest.fixture
def engine(): return Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv'))

def basket(engine):
    state = new_state()
    engine.act(state, 'add_item', {'item_id':'rice_05','quantity':1,'options':{},'notes':''})
    return state, state['basket'][0]['line_id']

def grant(adapter,state,line,groups=('rice',),decision='delegate',text='الروز أنت اختاره'):
    return adapter.act(state,'set_choice_permission',{'line_id':line,'group_ids':list(groups),
         'decision':decision,'evidence':text},utterance=text)

def select(adapter,state,line,options):
    return adapter.act(state,'select_delegated_options',{'line_id':line,'options':options})

def test_rice_permission_is_not_permission_for_other_fields(engine):
    s,line=basket(engine);a=ModelLedEngine(engine,s)
    grant(a,s,line)
    with pytest.raises(RuleError): select(a,s,line,{'portion':['large']})
    assert s['basket'][0]['options']=={}
    assert permission_view(s)[line]['rice']['status']=='active'
    select(a,s,line,{'rice':['original']})
    assert s['basket'][0]['options']=={'rice':['original']}
    assert s['basket'][0]['quantity']==1 and s['service'] is None and not s['order_id']
    with pytest.raises(RuleError): select(a,s,line,{'rice':['white']})

@pytest.mark.parametrize('group',['branch','quantity','service','address','confirm','*'])
def test_scope_cannot_include_non_menu_fields(engine,group):
    s,line=basket(engine)
    with pytest.raises(RuleError):grant(ModelLedEngine(engine,s),s,line,(group,))
    assert not s.get('choice_permissions') and not s['order_id']

def test_all_selections_validate_before_any_permission_is_spent(engine):
    s,line=basket(engine);a=ModelLedEngine(engine,s)
    grant(a,s,line,('rice','portion'))
    before=copy.deepcopy(s)
    with pytest.raises(RuleError):select(a,s,line,{'rice':['original'],'portion':['invented']})
    assert s==before
    with pytest.raises(RuleError):select(a,s,line,{'rice':['original','white']})
    assert s==before

def test_revoke_does_not_erase_existing_customer_choices(engine):
    s,line=basket(engine);a=ModelLedEngine(engine,s)
    a.act(s,'update_item',{'line_id':line,'options':{'spice_level':['mild']}})
    grant(a,s,line)
    grant(a,s,line,decision='revoke',text='لا تختار لي الرز')
    with pytest.raises(RuleError):select(a,s,line,{'rice':['original']})
    assert s['basket'][0]['options']=={'spice_level':['mild']}

@pytest.mark.parametrize('operation', ['replace_item','remove_item','cancel_draft'])
def test_dish_identity_and_lifetime_bound_permissions(engine,operation):
    s,line=basket(engine);a=ModelLedEngine(engine,s);grant(a,s,line)
    args={} if operation=='cancel_draft' else {'line_id':line}
    if operation=='replace_item':args['item_id']='rice_06'
    a.act(s,operation,args,utterance='الغي الطلب كله' if operation=='cancel_draft' else '')
    with pytest.raises(RuleError):select(a,s,line,{'rice':['original']})
    assert permission_view(s)[line]['rice']['status']=='superseded'

def test_explicit_override_wins_and_is_not_changed_later(engine):
    s,line=basket(engine);a=ModelLedEngine(engine,s);grant(a,s,line)
    select(a,s,line,{'rice':['original']})
    a.act(s,'update_item',{'line_id':line,'options':{'rice':['white']}})
    with pytest.raises(RuleError):select(a,s,line,{'rice':['original']})
    assert s['basket'][0]['options']['rice']==['white']

def test_permission_is_local_to_one_line_and_current_speech(engine):
    s,line=basket(engine);a=ModelLedEngine(engine,s)
    a.act(s,'add_item',{'item_id':'rice_06','quantity':1,'options':{},'notes':''})
    other=s['basket'][-1]['line_id'];grant(a,s,line)
    with pytest.raises(RuleError):select(a,s,other,{'rice':['original']})
    with pytest.raises(RuleError):a.act(s,'set_choice_permission',{'line_id':line,'group_ids':['portion'],
           'decision':'delegate','evidence':'you choose'},utterance='only change rice')
    assert 'portion' not in permission_view(s)[line]

def call(name,**args):return {'id':name,'function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}}
class Planner:
    def __init__(self,*steps):self.steps=list(steps);self.rounds=0
    async def chat(self,messages,tools):
        self.rounds+=1
        assert not {'finish_draft','ask_choice'}&{x['function']['name'] for x in tools}
        return self.steps.pop(0)

@pytest.mark.asyncio
async def test_messy_correction_and_scoped_choices_batch_then_natural_reply(engine,tmp_path):
    tx=Transactions(tmp_path/'calls.db',engine);sid,_=tx.create();row=tx.load(sid)
    s,line=basket(engine);row['state']=s
    with tx.connect() as db: db.execute('UPDATE calls SET state=? WHERE id=?',(json.dumps(s),sid))
    text='لا لا دجاج ما أبي، خلها لحم وثلاثة، والرز أنت اختاره'
    planner=Planner({'tool_calls':[
        call('replace_item',line_id=line,item_id='rice_06',quantity=3),
        call('set_choice_permission',line_id=line,group_ids=['rice'],decision='delegate',evidence='والرز أنت اختاره'),
        call('select_delegated_options',line_id=line,options={'rice':['original']})]},
        {'content':'خليتها ثلاثة مضغوط لحم واخترت الرز الأصلي. الحجم فردي ولا كبير ولا عائلي؟'})
    p=await prepare_turn(engine,planner,row,text,conversation_mode='model_led')
    assert planner.rounds==2 and len(p.state['basket'])==1
    assert p.state['basket'][0]['quantity']==3 and p.state['basket'][0]['item_id']=='rice_06'
    assert p.state['basket'][0]['options']=={'rice':['original']}
    assert p.reply.endswith('الحجم فردي ولا كبير ولا عائلي؟')  # No next_question rewrite.
    result=await commit_turn(tx,sid,'messy',p)
    assert result['outcome']['kind']=='order_edit'
    assert 'conversation_permissions' in result['outcome']['changed_domains']
    saved=tx.load(sid)['state'];assert saved['choice_permissions'][line]['rice']['status']=='used'
    assert tx.replay_bundle(sid,'messy',text)==result
    assert not saved['order_id'] and saved['quote'] is None and saved['service'] is None

@pytest.mark.asyncio
async def test_rejected_scope_returns_facts_to_planner_without_mutating_order(engine):
    s,line=basket(engine)
    class Inspect(Planner):
        async def chat(self,messages,tools):
            if self.rounds:
                result=json.loads(messages[-1]['content'])
                assert result['error'] and result['current_reference_data']['state']['basket'][0]['options']=={}
            return await super().chat(messages,tools)
    p=await prepare_turn(engine,Inspect({'tool_calls':[call('select_delegated_options',line_id=line,options={'rice':['original']})]},
            {'content':'وش نوع الرز اللي تفضله؟'}),{'state':s,'epoch':0},'وش عندكم؟',conversation_mode='model_led')
    assert p.state['basket']==s['basket'] and not p.operations

@pytest.mark.asyncio
async def test_superseded_preparation_cannot_publish_permission(engine,tmp_path):
    tx=Transactions(tmp_path/'calls.db',engine);sid,_=tx.create();s,line=basket(engine)
    with tx.connect() as db:db.execute('UPDATE calls SET state=? WHERE id=?',(json.dumps(s),sid))
    p=await prepare_turn(engine,Planner({'tool_calls':[call('set_choice_permission',line_id=line,group_ids=['rice'],
            decision='delegate',evidence='اختار لي الرز')]},{'content':'أقترح الرز الأصلي.'}),tx.load(sid),'اختار لي الرز',conversation_mode='model_led')
    tx.interrupt(sid)
    with pytest.raises(Conflict):await commit_turn(tx,sid,'obsolete',p)
    assert not tx.load(sid)['state'].get('choice_permissions')
