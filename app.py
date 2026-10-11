from __future__ import annotations
import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sawt.agent import Agent
from sawt.domain import Engine, Menu
from sawt.provider import OpenAIProvider, ProviderError, config
from sawt.store import Store

ROOT = Path(__file__).resolve().parent
menu = Menu(ROOT / 'data/restaurant-menu-complex.csv')
engine = Engine(menu)
provider = OpenAIProvider()
agent = Agent(engine, provider)
store = Store(ROOT / 'runtime/orders.sqlite3')
locks = {}
epochs = {}
app = FastAPI(title='Sawt Arabic Restaurant Agent', version='1.0.0')
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

class Turn(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=1200)
    epoch: int = 0

class SessionRequest(BaseModel):
    session_id: str

class Ack(SessionRequest):
    token: str
    revision: int

class Speech(SessionRequest):
    text: str = Field(min_length=1, max_length=5000)
    epoch: int = 0

def require_session(session):
    state = store.load(session)
    if state is None: raise HTTPException(404, 'المحادثة غير موجودة. ابدأ محادثة جديدة.')
    return state

@app.get('/')
def index(): return FileResponse(ROOT / 'static/index.html')

@app.get('/api/health')
def health():
    cfg = config()
    return {'ready': bool(cfg['key']), 'models': {k: cfg[k] for k in ['llm', 'stt', 'tts', 'voice']},
            'menu': {'items': len(menu.items), 'rows': menu.row_count, 'categories': len({x['category_id'] for x in menu.items.values()}), 'columns': len(menu.columns)}, 'mock_restaurant': True}

@app.post('/api/session')
def create_session():
    sid = uuid.uuid4().hex
    state = store.create(sid)
    epochs[sid] = 0
    return {'session_id': sid, 'epoch': 0, 'state': engine.view(state), 'reply': 'يا هلا! أنا مساعد صوت بالذكاء الاصطناعي. تبي توصيل، استلام، استفسار، أو تتواصل مع موظف؟'}

@app.get('/api/session/{session_id}')
def get_session(session_id: str):
    state = require_session(session_id)
    return {'state': engine.view(state), 'events': state['events'], 'history': state['history'], 'epoch': epochs.get(session_id, 0)}

@app.post('/api/interrupt')
async def interrupt(body: SessionRequest):
    state = require_session(body.session_id)
    epochs[body.session_id] = epochs.get(body.session_id, 0) + 1
    # In-flight agent work is speculative and checks epoch before committing.
    state['quote'] = None
    store.save(body.session_id, state)
    return {'epoch': epochs[body.session_id], 'state': engine.view(state)}

@app.post('/api/readback-played')
async def ack(body: Ack):
    async with locks.setdefault(body.session_id, asyncio.Lock()):
        state = require_session(body.session_id)
        quote = state['quote']
        if not quote or quote['token'] != body.token or body.revision != state['revision']:
            raise HTTPException(409, 'ملخص قديم. اطلب ملخصاً جديداً.')
        quote['presented'] = True
        store.save(body.session_id, state)
        return {'state': engine.view(state)}

async def run_turn(body: Turn):
    async with locks.setdefault(body.session_id, asyncio.Lock()):
        state = require_session(body.session_id)
        digest = hashlib.sha256(body.text.encode()).hexdigest()
        try: cached = store.replay(body.session_id, body.request_id, digest)
        except ValueError as exc: raise HTTPException(409, 'رقم المحاولة مستخدم لرسالة مختلفة.') from exc
        if cached: return cached
        if body.epoch != epochs.get(body.session_id, 0): raise HTTPException(409, 'تم إلغاء هذه المحاولة بالمقاطعة.')
        started = time.perf_counter()
        try:
            new, result = await asyncio.wait_for(agent.turn(state, body.text), timeout=90)
        except asyncio.TimeoutError as exc:
            state['quote'] = None
            store.save(body.session_id, state)
            raise HTTPException(504, 'انتهت المهلة. لم يتم حفظ تغييرات جديدة.') from exc
        except ProviderError as exc:
            state['quote'] = None
            store.save(body.session_id, state)
            raise HTTPException(503, str(exc)) from exc
        if body.epoch != epochs.get(body.session_id, 0): raise HTTPException(409, 'تم إلغاء هذه المحاولة بالمقاطعة.')
        result['timing_ms'] = {'agent': round((time.perf_counter() - started) * 1000)}
        store.save(body.session_id, new, body.request_id, digest, result)
        return result

@app.post('/api/turn')
async def turn(body: Turn): return await run_turn(body)

@app.post('/api/audio')
async def audio(session_id: str = Form(...), request_id: str = Form(...), epoch: int = Form(0), audio: UploadFile = File(...)):
    require_session(session_id)
    if epoch != epochs.get(session_id, 0): raise HTTPException(409, 'التسجيل ملغى.')
    data = await audio.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024: raise HTTPException(413, 'التسجيل أكبر من ٢٠ ميغابايت.')
    if len(data) < 100: raise HTTPException(400, 'التسجيل فارغ أو قصير جداً.')
    extension = Path(audio.filename or 'voice.webm').suffix.lower()
    if extension not in {'.webm', '.wav', '.mp3', '.m4a', '.mp4', '.ogg', '.flac'}: raise HTTPException(400, 'صيغة الصوت غير مدعومة.')
    started = time.perf_counter()
    try: text = await provider.transcribe(data, 'voice' + extension)
    except ProviderError as exc: raise HTTPException(503, str(exc)) from exc
    if not text or len(text) > 1200: raise HTTPException(400, 'لم أفهم التسجيل. حاول بجملة أقصر.')
    stt_ms = round((time.perf_counter() - started) * 1000)
    result = await run_turn(Turn(session_id=session_id, request_id=request_id, epoch=epoch, text=text))
    result['timing_ms']['stt'] = stt_ms
    return result

@app.post('/api/speech')
async def speech(body: Speech):
    require_session(body.session_id)
    if body.epoch != epochs.get(body.session_id, 0): raise HTTPException(409, 'الصوت ملغى.')
    started = time.perf_counter()
    try: data = await provider.speak(body.text)
    except ProviderError as exc: raise HTTPException(503, str(exc)) from exc
    if body.epoch != epochs.get(body.session_id, 0): raise HTTPException(409, 'الصوت ملغى.')
    return Response(data, media_type='audio/mpeg', headers={'X-TTS-Milliseconds': str(round((time.perf_counter() - started) * 1000))})

@app.get('/api/menu')
def search(query: str = '', offset: int = 0): return menu.search(query, offset=max(offset, 0))

@app.get('/api/export/{session_id}')
def export(session_id: str):
    state = require_session(session_id)
    return Response(json.dumps({'state': engine.view(state), 'history': state['history'], 'events': state['events']}, ensure_ascii=False, indent=2),
                    media_type='application/json', headers={'Content-Disposition': 'attachment; filename="sawt-session.json"'})
