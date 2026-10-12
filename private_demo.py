"""Private demo entry point. Never tunnel app_v2 directly: its admin is host-only.

Run behind HTTPS on a loopback port with --no-proxy-headers. This entry point
allows only the caller surface, even for authenticated visitors. Local Wi-Fi
continues using app_v2 with its existing configuration.
"""
import hashlib
import base64
import hmac
import json
import re
import secrets
import time
from collections import deque
from urllib.parse import urlsplit, parse_qs
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from app_v2 import app as caller_app, ROOT

CONFIG = ROOT/'runtime/private-demo.json'
COOKIE = '__Host-sawt-demo'
attempts = deque(maxlen=100)
LOGIN = '''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>صوت — تجربة خاصة</title><style>body{background:#101014;color:#f4f4f6;font:18px system-ui;display:grid;place-items:center;min-height:95vh;margin:0}main{width:min(320px,85vw)}h1{font-size:25px;font-weight:500}input,button{box-sizing:border-box;width:100%;padding:14px;border-radius:12px;border:1px solid #41414a;font:inherit}input{background:#18181e;color:white;margin:12px 0}button{background:white;color:#141419;cursor:pointer}p{color:#aaa;font-size:14px;line-height:1.7}</style><main><h1>تجربة صوت الخاصة</h1><form method="post" action="/login"><label for="password">رمز التجربة</label><input id="password" name="password" type="password" required autocomplete="current-password" maxlength="128"><button>دخول</button></form><p>مساعد تجريبي بالذكاء الاصطناعي. تُسجّل المكالمات لتحسين التجربة؛ الطلبات لا تُرسل لمطعم.</p></main></html>'''
LOGIN_SCRIPT = """document.querySelector('form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;const button=form.querySelector('button');button.disabled=true;let status=document.getElementById('login-status');if(!status){status=document.createElement('p');status.id='login-status';status.setAttribute('role','alert');form.append(status);}status.textContent='جاري الدخول';try{const response=await fetch('/login',{method:'POST',body:new URLSearchParams(new FormData(form)),credentials:'same-origin'});if(response.ok){location.replace('/');return;}status.textContent=response.status===401?'الرمز غير صحيح.':response.status===429?'محاولات كثيرة، جرّب بعد دقيقة.':'تعذر الدخول، حاول مرة ثانية.';}catch{status.textContent='تعذر الاتصال، حاول مرة ثانية.';}button.disabled=false;});"""
LOGIN = LOGIN.replace('</html>','<script>'+LOGIN_SCRIPT+'</script></html>')
SCRIPT_HASH = base64.b64encode(hashlib.sha256(LOGIN_SCRIPT.encode()).digest()).decode()


def settings():
    try:
        data=json.loads(CONFIG.read_text(encoding='utf8'))
        if len(data['password']) < 8 or len(data['secret']) < 32:
            return None
        url=urlsplit(data['url'])
        return data if url.scheme=='https' and url.hostname and url.path in ('','/') else None
    except (OSError,ValueError,KeyError,TypeError):
        return None


def signature(secret, value):
    return hmac.new(secret.encode(),value.encode(),hashlib.sha256).hexdigest()


def token_valid(value, secret):
    try:
        expiry,nonce,sig=value.split('.')
        return time.time() < int(expiry) <= time.time()+43201 and hmac.compare_digest(sig,signature(secret,expiry+'.'+nonce))
    except (ValueError,TypeError,AttributeError):
        return False


def allowed(path, method):
    if method=='GET' and (path=='/' or path=='/api/health'):
        return True
    if method=='GET' and path.startswith('/assets/'):
        return not any(x in path for x in ('..','\\','%')) and not path.endswith(('.html','.map'))
    if method=='POST' and path=='/api/calls':
        return True
    if method=='GET':
        return bool(re.fullmatch(r'/api/calls/[a-f0-9]{32}(?:/readback/[a-f0-9]{32})?',path))
    return method=='POST' and bool(re.fullmatch(r'/api/calls/[a-f0-9]{32}/(?:end|readback|playback)',path))


async def app(scope, receive, send):
    if scope['type']=='lifespan':
        return await caller_app(scope,receive,send)
    if scope['type']!='http':
        return await Response(status_code=404)(scope,receive,send)
    request=Request(scope,receive)
    config=settings()
    response=None
    if not config:
        response=Response('Private demo is not configured.',status_code=503)
    elif request.headers.get('host') != urlsplit(config['url']).netloc:
        response=Response('Invalid host',status_code=400)
    elif request.method not in ('GET','HEAD') and request.headers.get('origin') != config['url'].rstrip('/'):
        response=Response('Invalid origin',status_code=403)
    elif request.url.path=='/login' and request.method=='GET':
        response=HTMLResponse(LOGIN)
    elif request.url.path=='/login' and request.method=='POST':
        now=time.time()
        while attempts and now-attempts[0]>60:attempts.popleft()
        body=b''
        async for chunk in request.stream():
            body+=chunk
            if len(body)>1024:break
        if len(body)>1024:
            response=Response('Too large',status_code=413)
        elif len(attempts)>=20:
            response=Response('Try again in a minute.',status_code=429)
        else:
            attempts.append(now)
            password=parse_qs(body.decode('utf8',errors='replace')).get('password',[''])[0]
            if not hmac.compare_digest(password.encode(),config['password'].encode()):
                response=HTMLResponse(LOGIN.replace('<h1>','<p role="alert">الرمز غير صحيح.</p><h1>'),status_code=401)
            else:
                value=str(int(now)+43200)+'.'+secrets.token_hex(16)
                response=RedirectResponse('/',status_code=303)
                response.set_cookie(COOKIE,value+'.'+signature(config['secret'],value),max_age=43200,secure=True,httponly=True,samesite='strict',path='/')
    elif not token_valid(request.cookies.get(COOKIE),config['secret']):
        response=JSONResponse({'detail':'Private demo login required'},status_code=401) if request.url.path.startswith('/api/') else RedirectResponse('/login',status_code=303)
    elif not allowed(request.url.path,request.method):
        response=Response(status_code=404)
    if response is not None:
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-"+SCRIPT_HASH+"'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        return await response(scope,receive,send)
    # Authentication and the route allowlist above precede this local app call.
    # Caller tokens still enforce per-call isolation in app_v2. No admin route
    # reaches this point; forwarded headers cannot change that fact.
    trusted=dict(scope,scheme='https',client=('127.0.0.1',0))
    trusted['headers']=[(k,v) for k,v in scope['headers'] if not k.lower().startswith(b'x-forwarded-')]
    await caller_app(trusted,receive,send)
