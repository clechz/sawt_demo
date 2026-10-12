import asyncio
import copy
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import app
from sawt.agent import Agent
from sawt.agent import validate_args
from sawt.domain import Engine, Menu, new_state
from sawt.provider import ProviderError
from sawt.store import Store
from test_domain import ready

class Scripted:
    def __init__(self,*responses):self.responses=list(responses);self.messages=[]
    async def chat(self,messages,tools):
        self.messages.append(copy.deepcopy(messages))
        value=self.responses.pop(0)
        if isinstance(value,Exception):raise value
        return value

def call(name,args):return {'tool_calls':[{'id':'call-'+name,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}

@pytest.fixture
def engine():return Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv'))

async def test_duplicate_tool_calls_do_not_duplicate_items(engine):
    action=call('add_item',{'item_id':'chicken_01','quantity':2,'options':{},'notes':''})
    a=Agent(engine,Scripted(action,action,{'content':'وش الحجم؟'}))
    s,r=await a.turn(new_state(),'أبي وجبتين')
    assert len(s['basket'])==1 and s['basket'][0]['quantity']==2

async def test_provider_failure_rolls_back_partial_turn(engine):
    original=new_state();before=copy.deepcopy(original)
    a=Agent(engine,Scripted(call('set_service',{'service':'pickup'}),ProviderError('timeout')))
    with pytest.raises(ProviderError):await a.turn(original,'استلام')
    assert original==before

async def test_invalid_json_recoverable(engine):
    malformed=call('set_service',{});malformed['tool_calls'][0]['function']['arguments']='{oops'
    a=Agent(engine,Scripted(malformed,{'content':'تبي توصيل أو استلام؟'}))
    s,r=await a.turn(new_state(),'هلا')
    assert s['service'] is None and r['events'][0]['result']['error']

async def test_model_cannot_self_authorize_order(engine):
    s=ready(engine);engine.act(s,'checkout',{});s['quote']['presented']=True
    a=Agent(engine,Scripted(call('confirm',{}),{'content':'هل تبي ملخصاً جديداً؟'}))
    updated,r=await a.turn(s,'نعم بس احذف وجبة')
    assert updated['order_id'] is None and updated['quote'] is None

async def test_handoff_without_provider(engine):
    a=Agent(engine,Scripted())
    s,r=await a.turn(new_state(),'أبي موظف عندي شكوى')
    assert s['handoff'] and not s['order_id']

async def test_confirm_deterministic_no_provider(engine):
    s=ready(engine);engine.act(s,'checkout',{});s['quote']['presented']=True
    a=Agent(engine,Scripted())
    updated,r=await a.turn(s,'نعم')
    assert updated['order_id'] and updated['basket']==s['basket']

async def test_context_bounded_and_full_menu_absent(engine):
    fake=Scripted(*[{'content':'حياك'} for _ in range(15)]);a=Agent(engine,fake);s=new_state()
    for _ in range(15):s,_=await a.turn(s,'هلا')
    assert len(s['history'])==12 and len(fake.messages[-1])<=14
    assert 'breakfast_12' not in fake.messages[0][0]['content']

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(app,'store',Store(tmp_path/'test.sqlite3'))
    monkeypatch.setattr(app,'locks',{});monkeypatch.setattr(app,'epochs',{})
    return TestClient(app.app)

def test_http_idempotent_turn_and_conflicting_reuse(client,monkeypatch,engine):
    monkeypatch.setattr(app,'agent',Agent(engine,Scripted(call('set_service',{'service':'pickup'}),{'content':'أي فرع؟'})))
    sid=client.post('/api/session',json={}).json()['session_id']
    body={'session_id':sid,'request_id':'same','text':'استلام','epoch':0}
    a=client.post('/api/turn',json=body);b=client.post('/api/turn',json=body)
    assert a.status_code==b.status_code==200 and a.json()==b.json()
    body['text']='توصيل';assert client.post('/api/turn',json=body).status_code==409

def test_persistent_single_order(client,monkeypatch,engine):
    monkeypatch.setattr(app,'agent',Agent(engine,Scripted()))
    sid=client.post('/api/session',json={}).json()['session_id'];s=ready(engine);engine.act(s,'checkout',{});s['quote']['presented']=True;app.store.save(sid,s)
    a=client.post('/api/turn',json={'session_id':sid,'request_id':'one','text':'نعم'}).json()
    b=client.post('/api/turn',json={'session_id':sid,'request_id':'two','text':'نعم'}).json()
    assert a['state']['order_id']==b['state']['order_id']
    reopened=Store(app.store.path)
    with reopened.connect() as db:assert db.execute('SELECT count(*) FROM orders').fetchone()[0]==1

def test_interrupt_invalidates_ack_and_rejects_old_epoch(client,engine):
    sid=client.post('/api/session',json={}).json()['session_id'];s=ready(engine);engine.act(s,'checkout',{});q=copy.deepcopy(s['quote']);app.store.save(sid,s)
    result=client.post('/api/interrupt',json={'session_id':sid}).json();assert result['epoch']==1
    assert client.post('/api/readback-played',json={'session_id':sid,'token':q['token'],'revision':q['revision']}).status_code==409
    assert client.post('/api/turn',json={'session_id':sid,'request_id':'a','epoch':0,'text':'نعم'}).status_code==409

def test_audio_pipeline_with_stubbed_provider(client,monkeypatch,engine):
    class AudioFake(Scripted):
        async def transcribe(self,data,filename):return 'أبي موظف'
        async def speak(self,text):return b'ID3mock-audio'
    fake=AudioFake();monkeypatch.setattr(app,'provider',fake);monkeypatch.setattr(app,'agent',Agent(engine,fake))
    sid=client.post('/api/session',json={}).json()['session_id']
    response=client.post('/api/audio',data={'session_id':sid,'request_id':'audio','epoch':0},files={'audio':('test.wav',b'x'*200,'audio/wav')})
    assert response.status_code==200 and response.json()['state']['handoff']
    speech=client.post('/api/speech',json={'session_id':sid,'text':response.json()['reply']})
    assert speech.status_code==200 and speech.headers['content-type']=='audio/mpeg'

def test_audio_rejects_empty_and_unknown_session(client):
    sid=client.post('/api/session',json={}).json()['session_id']
    assert client.post('/api/audio',data={'session_id':sid,'request_id':'audio'},files={'audio':('a.wav',b'')}).status_code==400
    assert client.get('/api/session/missing').status_code==404

def test_no_secrets_in_health(client):
    payload=client.get('/api/health').json()
    assert 'key' not in payload and 'OPENAI_API_KEY' not in json.dumps(payload)
    assert payload['menu']['items']==144

@pytest.mark.parametrize('name,args',[
    ('not_a_tool',{}),('add_item',{}),('set_service',{'service':'delivery','price':0}),
    ('set_service',{'service':'free'}),('search_menu',{'query':'a','offset':-1}),
    ('update_item',{'line_id':'a','quantity':True}),('set_location',{'city':2,'zone':'a','address':'b'}),
])
def test_strict_argument_contract(name,args):
    from sawt.domain import RuleError
    with pytest.raises(RuleError):validate_args(name,args)

async def test_interrupt_during_provider_work_discards_mutations(tmp_path,monkeypatch,engine):
    started=asyncio.Event();release=asyncio.Event()
    class Delayed:
        def __init__(self):self.step=0
        async def chat(self,messages,tools):
            self.step+=1
            if self.step==1:return call('set_service',{'service':'pickup'})
            started.set();await release.wait();return {'content':'أي فرع؟'}
    monkeypatch.setattr(app,'store',Store(tmp_path/'parallel.sqlite3'))
    monkeypatch.setattr(app,'locks',{});monkeypatch.setattr(app,'epochs',{})
    monkeypatch.setattr(app,'agent',Agent(engine,Delayed()))
    sid=app.create_session()['session_id']
    task=asyncio.create_task(app.run_turn(app.Turn(session_id=sid,request_id='slow',text='استلام')))
    await started.wait();await app.interrupt(app.SessionRequest(session_id=sid));release.set()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as err:await task
    assert err.value.status_code==409 and app.store.load(sid)['service'] is None

async def test_simultaneous_confirmation_requests_create_one_order(tmp_path,monkeypatch,engine):
    monkeypatch.setattr(app,'store',Store(tmp_path/'concurrent.sqlite3'))
    monkeypatch.setattr(app,'locks',{});monkeypatch.setattr(app,'epochs',{})
    monkeypatch.setattr(app,'agent',Agent(engine,Scripted()))
    sid=app.create_session()['session_id'];s=ready(engine);engine.act(s,'checkout',{});s['quote']['presented']=True;app.store.save(sid,s)
    results=await asyncio.gather(*[app.run_turn(app.Turn(session_id=sid,request_id=str(i),text='نعم')) for i in range(5)])
    assert len({r['state']['order_id'] for r in results})==1
    with app.store.connect() as db:assert db.execute('SELECT count(*) FROM orders').fetchone()[0]==1

def test_ack_of_current_summary_enables_confirmation(client,engine):
    sid=client.post('/api/session',json={}).json()['session_id'];s=ready(engine);engine.act(s,'checkout',{});q=s['quote'];app.store.save(sid,s)
    response=client.post('/api/readback-played',json={'session_id':sid,'token':q['token'],'revision':q['revision']})
    assert response.status_code==200 and response.json()['state']['quote']['presented']

def test_failed_turn_clears_prior_confirmation(client,monkeypatch,engine):
    monkeypatch.setattr(app,'agent',Agent(engine,Scripted(ProviderError('timeout'))))
    sid=client.post('/api/session',json={}).json()['session_id'];s=ready(engine);engine.act(s,'checkout',{});s['quote']['presented']=True;app.store.save(sid,s)
    response=client.post('/api/turn',json={'session_id':sid,'request_id':'fail','text':'غير العنوان'})
    assert response.status_code==503
    stored=app.store.load(sid);assert stored['basket']==s['basket'] and stored['quote'] is None

@pytest.mark.parametrize('malformed',[None,[],{'tool_calls':[{}]},{'tool_calls':'bad'}])
async def test_malformed_provider_envelope(engine,malformed):
    with pytest.raises(ProviderError):await Agent(engine,Scripted(malformed)).turn(new_state(),'هلا')


async def test_unavailable_request_does_not_force_an_extra_add_item_round(engine):
    provider=Scripted(call('search_menu',{'query':'شاي عدني'}),{'content':'الشاي العدني مو موجود، عندنا شاي أحمر وكرك. وش تفضّل؟'})
    state,result=await Agent(engine,provider).turn(new_state(),'أبي ثلاثة شاي عدني')
    assert not state['basket']
    assert len(provider.messages)==2
    assert 'مو موجود' in result['reply']


def test_search_distinguishes_partial_from_full_matches(engine):
    assert engine.menu.search('شاي عدني')['partial_matches_only']
    assert not engine.menu.search('شاي كرك')['partial_matches_only']
    assert not engine.menu.search('شكشوكة')['partial_matches_only']
