"""V2 authenticated browser API. V1 stays runnable with app:app."""
import io
import os
import time
import asyncio
import logging
from typing import Literal
from ipaddress import ip_address, ip_network
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
import av
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field
from livekit import api
from sawt.v2_runtime import tx, engine, provider, ROOT, RUNTIME
from sawt import cloud_storage
from sawt.transactions import Conflict
from sawt.recording import prune
from sawt.experience import available_experiences, validate_experience, call_experience
from sawt.hospitality import hospitality_view
from sawt.v2_provider import V2Provider

load_dotenv(ROOT / '.env')
@asynccontextmanager
async def lifespan(app):
    async def retention():
        while True:
            try:
                await asyncio.to_thread(prune, RUNTIME / 'recordings')
            except Exception:
                logging.getLogger('sawt').exception('Recording retention failed')
            await asyncio.sleep(3600)
    task = asyncio.create_task(retention())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await provider.aclose()

app = FastAPI(title='SAWT V2', version='2.0.0', lifespan=lifespan)
app.mount('/assets', StaticFiles(directory=ROOT / 'static/v2'), name='v2')
MAX_SECONDS = 600

class StartCall(BaseModel):
    recording_consent: bool = Field(strict=True)
    voice: Literal['cedar', 'ash', 'marin'] | None = None
    scenario: Literal['new_order', 'late_delivery', 'missing_item', 'wrong_item'] = 'new_order'
    experience_version: Literal['v2', 'v3'] = 'v2'
    conversation_mode: Literal['legacy', 'model_led'] | None = None


@app.middleware('http')
async def protections(request, call_next):
    origin = request.headers.get('origin')
    if request.method != 'GET' and origin and origin != str(request.base_url).rstrip('/'):
        return Response('Unexpected origin', status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Permissions-Policy'] = 'microphone=(self), camera=()'
    return response


@app.exception_handler(Conflict)
async def conflict_handler(request, exc):
    from fastapi.responses import JSONResponse
    code = 'readback_incomplete' if str(exc) == 'Readback has not finished playing' else 'conflict'
    return JSONResponse({'detail': str(exc), 'code': code}, status_code=409)


def authorized(sid, request):
    token = request.headers.get('Authorization', '').removeprefix('Bearer ')
    try:
        return tx.authorize(sid, token)
    except (KeyError, PermissionError):
        raise HTTPException(404, 'المكالمة غير موجودة أو انتهت صلاحية الدخول.')


@app.get('/')
def index():
    return FileResponse(ROOT / 'static/v2/index.html')


@app.get('/debug')
def debug():
    return FileResponse(ROOT / 'static/v2/debug.html')


@app.get('/recordings')
def recording_page():
    return FileResponse(ROOT / 'static/v2/recordings.html')


@app.get('/lab')
def lab(request: Request):
    if request.client.host not in ('127.0.0.1', '::1', 'testclient'):
        raise HTTPException(403, 'Local test lab only')
    return FileResponse(ROOT / 'static/v2/index.html')


@app.get('/api/experience')
def experience_catalog():
    return available_experiences()


@app.get('/api/health')
def health():
    return {'transport': 'livekit', 'voice': 'gpt-live-1', 'mock_restaurant': True,
            'candidate': 'hospitality-v3', 'live_verified': False,
            'configured': all(os.getenv(k) for k in ['OPENAI_API_KEY','LIVEKIT_URL','LIVEKIT_API_KEY','LIVEKIT_API_SECRET'])}


def code_free_caller(host):
    if host in ('127.0.0.1', '::1', 'testclient'):
        return True
    try:
        address = ip_address(host)
        networks = [ip_network(value.strip(), strict=False)
                    for value in os.getenv('SAWT_CODE_FREE_NETWORKS', '').split(',') if value.strip()]
        return any(address in network for network in networks)
    except ValueError:
        return False


@app.post('/api/calls')
def create(request: Request, body: StartCall):
    # No code is needed on explicitly configured LAN networks when access is unset.
    load_dotenv(ROOT / '.env', override=True)
    access = os.getenv('SAWT_ACCESS_CODE', '')
    if access:
        import secrets
        if not secrets.compare_digest(request.headers.get('X-Access-Code', ''), access):
            raise HTTPException(401, 'رمز الدخول غير صحيح.')
    elif not code_free_caller(request.client.host):
        raise HTTPException(403, 'Public calling is disabled.')
    if not health()['configured']:
        raise HTTPException(503, 'خدمة المكالمات تحتاج إعداد الاتصال.')
    if body.recording_consent is not True:
        raise HTTPException(400, 'يلزم الموافقة على تسجيل المكالمة قبل البدء.')
    try:
        settings = validate_experience(body.voice, body.scenario, body.experience_version, conversation_mode=body.conversation_mode)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    sid, token = tx.create(enforce_limits=True, experience=settings)
    required_worker = tx.load(sid)['state']['experience'].get('worker_contract')
    tx.event(sid, 'recording.consent', {'notice_version': '2026-10-11', 'retention_days': 7, 'storage': 'private_cloud' if cloud_storage.enabled() else 'local'})
    jwt = (api.AccessToken(os.environ['LIVEKIT_API_KEY'], os.environ['LIVEKIT_API_SECRET'])
           .with_identity('caller-' + sid).with_ttl(timedelta(minutes=11))
           .with_grants(api.VideoGrants(room_join=True, room='sawt-' + sid, can_publish=True, can_subscribe=True, can_publish_data=True))
           .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=os.getenv('SAWT_AGENT_NAME','sawt-v2'), metadata=sid)]))
           .to_jwt())
    return {'id': sid, 'token': token, 'room_token': jwt, 'url': os.environ['LIVEKIT_URL'], 'max_seconds': MAX_SECONDS,
            'voice': settings['voice'], 'experience_version': settings['version'], 'scenario': settings['scenario'], 'conversation_mode': settings['conversation_mode'],
            'required_worker': required_worker}


@app.get('/api/calls/{sid}')
def state(sid: str, request: Request, after: int = 0):
    row = authorized(sid, request)
    return {'state': hospitality_view(row['state'], engine), 'epoch': row['epoch'], 'closed': bool(row['closed']), 'events': tx.events(sid, after)}


@app.post('/api/calls/{sid}/end')
def end(sid: str, request: Request):
    authorized(sid, request)
    tx.interrupt(sid, close=True)
    return {'closed': True}


@app.post('/api/calls/{sid}/readback')
def readback(sid: str, request: Request):
    row = authorized(sid, request)
    quote = row['state']['quote']
    if row['closed'] or not quote:
        raise Conflict('No current quote')
    receipt = tx.prepare_audio(sid, quote['token'])
    # The opaque receipt is a short-lived capability for this audio only. It
    # contains no user credential and cannot authorize any order operation.
    return {'receipt_id': receipt, 'url': f'/api/calls/{sid}/readback/{receipt}', 'quote_token': quote['token']}


def audio_duration(audio):
    with av.open(io.BytesIO(audio)) as media:
        return sum(frame.samples / frame.sample_rate for frame in media.decode(audio=0))


@app.get('/api/calls/{sid}/readback/{receipt_id}')
async def readback_stream(sid: str, receipt_id: str):
    try:
        receipt, quote = await asyncio.to_thread(tx.claim_audio, sid, receipt_id)
    except (KeyError, Conflict):
        raise HTTPException(404, 'Readback is no longer available')
    capture = RUNTIME / 'recordings' / sid
    capture.mkdir(parents=True, exist_ok=True)
    file = capture / (receipt_id + '.mp3')
    if receipt['duration'] > 0:
        if file.is_file():
            return FileResponse(file, media_type='audio/mpeg')
        if cloud_storage.enabled():
            try:
                content = await asyncio.to_thread(cloud_storage.download, sid, file.name)
            except Exception:
                raise HTTPException(503, 'Readback archive unavailable; request a new readback')
            if content is None:
                raise HTTPException(404, 'Readback file unavailable')
            return Response(content, media_type='audio/mpeg')
        if not file.is_file():
            raise HTTPException(404, 'Readback file unavailable')
        return FileResponse(file, media_type='audio/mpeg')

    async def chunks():
        started = time.perf_counter()
        audio = bytearray()
        first = True
        checked = 0
        call_row = await asyncio.to_thread(tx.load, sid)
        selected = call_experience(call_row['state'])['voice']
        scoped_provider = provider if selected == provider.voice else V2Provider(voice=selected)
        try:
            async for chunk in scoped_provider.stream_speech(quote['text']):
                elapsed = time.perf_counter() - started
                if elapsed - checked > .5 or first:
                    await asyncio.to_thread(tx.current_receipt, sid, receipt_id)
                    checked = elapsed
                if first:
                    await asyncio.to_thread(tx.event, sid, 'readback.first_byte', {'receipt_id': receipt_id, 'tts_first_byte_ms': round(elapsed*1000)})
                    first = False
                audio.extend(chunk)
                yield chunk
            duration = await asyncio.to_thread(audio_duration, bytes(audio))
            await asyncio.to_thread(file.write_bytes, bytes(audio))
            await asyncio.to_thread(tx.finish_audio, sid, receipt_id, duration)
            await asyncio.to_thread(tx.event, sid, 'readback.generated', {'receipt_id': receipt_id, 'duration': duration,
                      'tts_ms': round((time.perf_counter()-started)*1000), 'text_hash': quote['text_hash']})
        except BaseException as exc:
            await asyncio.to_thread(tx.fail_audio, sid, receipt_id)
            await asyncio.to_thread(tx.event, sid, 'readback.failed', {'receipt_id': receipt_id, 'error_type': type(exc).__name__,
                'cause_type': type(exc.__cause__).__name__ if exc.__cause__ else None,
                'elapsed_ms': round((time.perf_counter()-started)*1000), 'bytes_generated': len(audio)})
            raise
        finally:
            if scoped_provider is not provider:
                await scoped_provider.aclose()
    async def archive():
        # Archive storage is not evidence of playback. A suspension must not
        # invalidate fully generated audio or delay its delivery to the caller.
        if not file.is_file():
            return
        try:
            await asyncio.wait_for(asyncio.to_thread(cloud_storage.upload, file, sid), 5)
        except Exception as exc:
            await asyncio.to_thread(tx.event, sid, 'recording.archive_failed',
                                   {'kind': 'readback', 'error_type': type(exc).__name__})
    return StreamingResponse(chunks(), media_type='audio/mpeg', headers={'X-Accel-Buffering': 'no'}, background=BackgroundTask(archive))


class Playback(BaseModel):
    receipt_id: str = Field(max_length=64)
    phase: Literal['started', 'completed']
    position: float = Field(default=0, ge=0, le=600)


@app.post('/api/calls/{sid}/playback')
def playback(sid: str, body: Playback, request: Request):
    authorized(sid, request)
    tx.playback(sid, body.receipt_id, body.phase, body.position)
    return {'acknowledged': True}


@app.get('/api/recordings')
def recordings(request: Request):
    if request.client.host not in ('127.0.0.1', '::1', 'testclient'):
        raise HTTPException(403, 'Recording library is available only on the host computer.')
    with tx.connect() as db:
        rows = db.execute('SELECT id,created,closed,state FROM calls ORDER BY created DESC LIMIT 100').fetchall()
    import json
    return [{'id': row['id'], 'created': row['created'], 'closed': bool(row['closed']),
             'order_id': json.loads(row['state'])['order_id']} for row in rows]


@app.get('/api/recordings/{sid}')
def recording_details(sid: str, request: Request, after: int = 0):
    if request.client.host not in ('127.0.0.1', '::1', 'testclient'):
        raise HTTPException(403, 'Local operator only')
    try:
        row = tx.load(sid)
    except KeyError:
        raise HTTPException(404, 'Unknown call')
    folder = RUNTIME / 'recordings' / sid
    files = [f.name for f in folder.glob('*') if f.suffix in ('.wav','.mp3','.json')] if folder.exists() else []
    events = tx.events(sid, after)
    return {'state': engine.view(row['state']), 'events': events, 'files': files,
            'next_after': events[-1]['sequence'] if len(events) == 500 else None}


@app.get('/api/recordings/{sid}/{filename}')
def recording_file(sid: str, filename: str, request: Request):
    if request.client.host not in ('127.0.0.1', '::1', 'testclient'):
        raise HTTPException(403, 'Local operator only')
    import re
    if not re.fullmatch('[a-f0-9]{32}', sid) or not re.fullmatch(r'(caller|generated-assistant|[a-f0-9]{32})\.(wav|mp3)|capture\.json', filename):
        raise HTTPException(404)
    file = RUNTIME / 'recordings' / sid / filename
    if not file.is_file():
        raise HTTPException(404)
    return FileResponse(file)
