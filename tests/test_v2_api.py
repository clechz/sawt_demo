from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import app_v2
from sawt.transactions import Transactions

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_v2,'tx',Transactions(tmp_path/'v2.db',app_v2.engine))
    monkeypatch.setattr(app_v2,'load_dotenv',lambda *a,**kw:None)
    monkeypatch.setenv('SAWT_ACCESS_CODE','test-code')
    monkeypatch.setenv('SAWT_CODE_FREE_NETWORKS','')
    monkeypatch.setenv('LIVEKIT_URL','wss://example.livekit.cloud')
    monkeypatch.setenv('LIVEKIT_API_KEY','test-key')
    monkeypatch.setenv('LIVEKIT_API_SECRET','test-secret-not-real-32-characters')
    monkeypatch.setenv('OPENAI_API_KEY','test-not-real')
    app_v2.create_times.clear()
    return TestClient(app_v2.app)

def start(client):
    return client.post('/api/calls',headers={'X-Access-Code':'test-code'},json={'recording_consent':True})

def test_start_requires_code_and_recording_consent(client):
    assert client.post('/api/calls',json={'recording_consent':True}).status_code==401
    assert client.post('/api/calls',headers={'X-Access-Code':'test-code'},json={'recording_consent':False}).status_code==400
    assert client.post('/api/calls',headers={'X-Access-Code':'test-code'},json={'recording_consent':'true'}).status_code==422
    assert start(client).status_code==200

def test_origin_and_call_scoping(client):
    assert client.post('/api/calls',headers={'Origin':'https://other.example'},json={'recording_consent':True}).status_code==403
    a,b=start(client).json(),start(client).json()
    assert client.get('/api/calls/'+a['id']).status_code==404
    assert client.get('/api/calls/'+a['id'],headers={'Authorization':'Bearer '+b['token']}).status_code==404
    r=client.get('/api/calls/'+a['id'],headers={'Authorization':'Bearer '+a['token']})
    assert r.status_code==200 and r.headers['cache-control']=='no-store'


def test_configured_lan_starts_without_access_code(client, monkeypatch):
    monkeypatch.setenv('SAWT_ACCESS_CODE', '')
    monkeypatch.setenv('SAWT_CODE_FREE_NETWORKS', '10.207.0.0/17')
    remote = TestClient(app_v2.app, client=('10.207.119.80', 1234))
    response = remote.post('/api/calls', json={'recording_consent': True})
    assert response.status_code == 200
    assert remote.get('/api/calls/'+response.json()['id']).status_code == 404
    assert remote.get('/api/recordings').status_code == 403


@pytest.mark.parametrize('host', ['10.207.128.1', '192.168.1.8', '8.8.8.8'])
def test_code_free_access_is_limited_to_configured_lan(client, monkeypatch, host):
    monkeypatch.setenv('SAWT_ACCESS_CODE', '')
    monkeypatch.setenv('SAWT_CODE_FREE_NETWORKS', '10.207.0.0/17')
    remote = TestClient(app_v2.app, client=(host, 1234))
    assert remote.post('/api/calls', headers={'X-Forwarded-For': '10.207.119.80'},
                       json={'recording_consent': True}).status_code == 403


def test_invalid_code_free_network_does_not_grant_access(client, monkeypatch):
    monkeypatch.setenv('SAWT_ACCESS_CODE', '')
    monkeypatch.setenv('SAWT_CODE_FREE_NETWORKS', 'invalid')
    remote = TestClient(app_v2.app, client=('10.207.119.80', 1234))
    assert remote.post('/api/calls', json={'recording_consent': True}).status_code == 403

def test_hangup_invalidates_confirmation_and_forged_receipt(client):
    call=start(client).json();headers={'Authorization':'Bearer '+call['token']}
    r=client.post('/api/calls/'+call['id']+'/playback',headers=headers,json={'receipt_id':'forged','phase':'completed','position':100})
    assert r.status_code==409
    assert client.post('/api/calls/'+call['id']+'/end',headers=headers).status_code==200
    assert client.get('/api/calls/'+call['id'],headers=headers).json()['closed']

def test_no_client_control_over_readback_text(client):
    call=start(client).json();headers={'Authorization':'Bearer '+call['token']}
    r=client.post('/api/calls/'+call['id']+'/readback',headers=headers,json={'text':'Fake order'})
    assert r.status_code==409

def test_recording_filename_traversal(client):
    assert client.get('/api/recordings/'+'a'*32+'/.env').status_code==404


def test_recording_review_paginates_without_losing_late_errors(client):
    call = start(client).json()
    for index in range(505):
        app_v2.tx.event(call['id'], 'diagnostic.test', {'index': index})
    app_v2.tx.event(call['id'], 'delegation.failed', {'error_type': 'TimeoutError'})
    first = client.get('/api/recordings/'+call['id']).json()
    assert len(first['events']) == 500
    second = client.get('/api/recordings/'+call['id'], params={'after': first['next_after']}).json()
    assert second['next_after'] is None
    assert second['events'][-1]['kind'] == 'delegation.failed'
    assert len(first['events'] + second['events']) == 507
    assert client.get('/api/recordings/'+'a'*32).status_code == 404


def test_recording_library_is_host_only(client):
    remote = TestClient(app_v2.app, client=('192.168.1.8', 1234))
    assert remote.get('/api/recordings').status_code == 403
    assert remote.get('/api/recordings/'+'a'*32).status_code == 403

def test_caller_page_has_no_diagnostics_or_chat(client):
    page=client.get('/').text
    assert 'id="voice-orb"' in page and 'ابدأ مكالمتك' in page
    assert 'textarea' not in page and '/api/recordings' not in page
    assert client.get('/debug').status_code==200
    assert client.get('/recordings').status_code==200


def test_stream_preparation_binds_server_text_and_rejects_stale_capability(client, monkeypatch, tmp_path):
    call=start(client).json();sid=call['id'];headers={'Authorization':'Bearer '+call['token']}
    for index,(name,args) in enumerate([
        ('set_service',{'service':'pickup'}),('set_branch',{'branch_id':'ruh_narjis'}),
        ('add_item',{'item_id':'breakfast_01','quantity':1,'options':{'portion':['large'],'bread':['tamees']},'notes':''}),
        ('checkout',{})]):
        row=app_v2.tx.load(sid)
        app_v2.tx.execute(sid,str(index),row['state']['revision'],row['epoch'],name,args)
    texts=[]
    async def speech(text):
        texts.append(text)
        yield b'first-'
        yield b'second'
    monkeypatch.setattr(app_v2.provider,'stream_speech',speech)
    monkeypatch.setattr(app_v2,'audio_duration',lambda audio:8.0)
    monkeypatch.setattr(app_v2,'ROOT',tmp_path)
    prepared=client.post(f'/api/calls/{sid}/readback',headers=headers,json={'text':'injected'}).json()
    assert texts==[]
    assert client.get(prepared['url']).content==b'first-second'
    assert texts==[app_v2.tx.load(sid)['state']['quote']['text']]
    assert client.get(prepared['url']).content==b'first-second'  # Cached reload, not a second paid generation.
    assert len(texts)==1
    assert client.post(f'/api/calls/{sid}/playback',headers=headers,json={'receipt_id':prepared['receipt_id'],'phase':'completed','position':8}).status_code==409
    app_v2.tx.interrupt(sid)
    assert client.get(prepared['url']).status_code==404


def test_invalid_playback_phase_is_validation_error(client):
    call=start(client).json()
    assert client.post('/api/calls/'+call['id']+'/playback',headers={'Authorization':'Bearer '+call['token']},
        json={'receipt_id':'invalid','phase':'anything','position':0}).status_code==422
