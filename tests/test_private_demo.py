import pytest
from fastapi.testclient import TestClient
import private_demo as demo

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(demo,'settings',lambda:{'url':'https://private.example','password':'only-test-password','secret':'test-signing-secret'*3})
    demo.attempts.clear()
    return TestClient(demo.app,base_url='https://private.example',follow_redirects=False)

def login(client):
    return client.post('/login',data={'password':'only-test-password'},headers={'Origin':'https://private.example'})

def test_private_login_cookie_and_origin(client):
    assert client.get('/').status_code==303
    assert client.get('/api/health').status_code==401
    assert client.post('/login',data={'password':'only-test-password'}).status_code==403
    assert client.post('/login',data={'password':'wrong'},headers={'Origin':'https://private.example'}).status_code==401
    response=login(client)
    assert response.status_code==303
    cookie=response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
    assert client.get('/').status_code==200 and client.get('/api/health').status_code==200

@pytest.mark.parametrize('path',['/api/recordings','/api/recordings/'+'a'*32,'/api/recordings/'+'a'*32+'/caller.wav','/lab','/debug','/recordings','/openapi.json','/docs','/.env','/runtime/private-demo.json','/assets/recordings.html','/assets/../runtime/v2.sqlite3'])
def test_admin_and_files_never_exposed_even_after_login(client,path):
    login(client)
    assert client.get(path,headers={'X-Forwarded-For':'127.0.0.1'}).status_code==404

def test_tampered_cookie_host_origin_and_call_token(client):
    login(client)
    assert client.get('/',headers={'Host':'evil.example'}).status_code==400
    assert client.post('/api/calls',json={'recording_consent':True},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/calls/'+'a'*32).status_code==404
    assert client.get('/',headers={'Cookie':demo.COOKIE+'=forged'}).status_code==303

def test_login_rate_and_body_limit(client):
    headers={'Origin':'https://private.example'}
    assert client.post('/login',content=b'a'*1025,headers=headers).status_code==413
    for _ in range(20):
        assert client.post('/login',data={'password':'wrong'},headers=headers).status_code==401
    assert login(client).status_code==429

def test_missing_configuration_fails_closed(client,monkeypatch):
    monkeypatch.setattr(demo,'settings',lambda:None)
    assert client.get('/').status_code==503
