"""Probe the real production/preview URLs; never confuse CI with a completed call.

Uses only an existing demo password/access code from the runner environment.
No authentication bypass, guessed password, provider key disclosure or deployment.
Optional worker check creates at most one isolated new-order call, publishes
silence to initialize the microphone, records the worker identity and received
speech, and closes that call. It does not submit an order or move money.
"""
from __future__ import annotations
import asyncio
import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
from urllib.parse import urlsplit
import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'runtime' / 'deployment-verification'
PREVIEW = 'https://sawt-demo-git-feat-v3-hospitality-voice-clechzs-projects.vercel.app'
PRODUCTION = 'https://sawt-demo.vercel.app'


def safe_response(response):
    text = response.text
    title = re.search(r'<title[^>]*>(.*?)</title>', text, re.I | re.S)
    known = next((s for s in ('Invalid host', 'Invalid origin', 'Private demo is not configured.',
        'Authentication Required', 'Private demo login required') if s in text), None)
    location = urlsplit(response.headers.get('location', ''))
    result = {'status': response.status_code, 'content_type': response.headers.get('content-type'),
        'location': (location.scheme + '://' + location.netloc if location.netloc else '') + location.path,
        'body_sha256': hashlib.sha256(response.content).hexdigest(), 'known_error': known}
    if title:
        result['title'] = title[1][:100]
    if response.headers.get('content-type', '').startswith('application/json'):
        try:
            data = response.json()
            result['health'] = {k: data[k] for k in ('candidate', 'configured', 'transport', 'voice', 'live_verified') if k in data}
        except (ValueError, TypeError):
            pass
    return result


async def worker_probe(client, report):
    # Client is already authenticated to this exact origin. No cookie/token is logged.
    from livekit import rtc
    response = await client.post('/api/calls', json={'recording_consent': True,
        'voice': 'cedar', 'scenario': 'new_order', 'experience_version': 'v3', 'conversation_mode': 'model_led'})
    report['call_creation_status'] = response.status_code
    if response.status_code != 200:
        report['blocked_at'] = 'call_creation'
        return
    call = response.json()
    sys.path.insert(0, str(ROOT))
    from sawt.release_contract import worker_contract, check_worker_contract
    from sawt.experience import validate_experience
    expected = worker_contract(validate_experience('cedar', conversation_mode='model_led'))
    try:
        check_worker_contract(expected, call.get('required_worker'))
    except ValueError:
        report['blocked_at'] = 'production_api_source_mismatch'
        await client.post('/api/calls/' + call['id'] + '/end', headers={'Authorization': 'Bearer ' + call['token']})
        return
    report['api_experience_version'] = call.get('experience_version')
    report['api_voice'] = call.get('voice')
    auth = {'Authorization': 'Bearer ' + call['token']}
    room = rtc.Room()
    source = None
    tasks = []
    events = []
    audio = {'frames': 0, 'nonzero_samples': 0}
    stop = asyncio.Event()
    async def listen(track):
        stream = rtc.AudioStream(track)
        try:
            async for item in stream:
                audio['frames'] += 1
                audio['nonzero_samples'] += sum(abs(sample[0]) > 100 for sample in struct.iter_unpack('<h', bytes(item.frame.data)))
        finally:
            await stream.aclose()
    @room.on('track_subscribed')
    def subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            tasks.append(asyncio.create_task(listen(track)))
    @room.on('data_received')
    def received(packet):
        if packet.topic == 'sawt':
            try:
                event = json.loads(packet.data)
                events.append({k: event.get(k) for k in ('type', 'code', 'fatal', 'release', 'voice') if k in event})
            except (ValueError, TypeError):
                pass
    async def pump():
        while not stop.is_set():
            await source.capture_frame(rtc.AudioFrame(b'\0' * 4800, 24000, 1, 2400))
    try:
        if call.get('experience_version') != 'v3':
            report['blocked_at'] = 'api_did_not_select_v3'
            return
        async with asyncio.timeout(60):
            await room.connect(call['url'], call['room_token'])
            source = rtc.AudioSource(24000, 1, queue_size_ms=100)
            track = rtc.LocalAudioTrack.create_audio_track('verification-silence', source)
            await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
            tasks.append(asyncio.create_task(pump()))
            while not any(e.get('type') in ('ready', 'error') for e in events):
                await asyncio.sleep(.2)
            await asyncio.sleep(5)
            state_response = await client.get('/api/calls/' + call['id'], headers=auth)
            state_response.raise_for_status()
            saved = state_response.json()
            connected = [e['payload'] for e in saved.get('events', []) if e.get('kind') == 'voice.connected']
            report['worker'] = [{k: event.get(k) for k in ('release', 'model', 'voice', 'scenario', 'conversation_mode', 'worker_contract')} for event in connected]
            report['audio_received'] = audio
            report['events'] = events
            matched = False
            if connected:
                try:
                    check_worker_contract(expected, connected[-1].get('worker_contract'))
                    matched = True
                except ValueError:
                    report['blocked_at'] = 'production_worker_source_mismatch'
            report['worker_v3_startup_verified'] = bool(matched
                and connected[-1].get('conversation_mode') == 'model_led'
                and connected[-1].get('voice') == 'cedar' and audio['nonzero_samples'] > 0
                and not any(e.get('fatal') for e in events))
    except Exception as exc:
        report['worker_error_type'] = type(exc).__name__
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            ended = await client.post('/api/calls/' + call['id'] + '/end', headers=auth)
            report['test_call_closed'] = ended.status_code == 200
        except Exception as exc:
            report['cleanup_error_type'] = type(exc).__name__
        await room.disconnect()
        if source:
            await source.aclose()


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'checked_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'source_commit': os.getenv('SAWT_VERIFY_COMMIT') or os.getenv('GITHUB_SHA'), 'scope': 'Real HTTP probes and optional authenticated startup; not a completed ordering/support call or human accent rating',
        'complete_call_verified': False, 'surfaces': {}}
    # Exercise the current gateway allowlist, not a reimplementation of it.
    tree = ast.parse((ROOT / 'private_demo.py').read_text(encoding='utf8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'allowed')
    ns = {'re': re}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'gateway-under-test', 'exec'), ns)
    report['source_gateway_checks'] = {'experience_route_allowed': ns['allowed']('/api/experience', 'GET'),
        'call_creation_allowed': ns['allowed']('/api/calls', 'POST'),
        'admin_blocked': not ns['allowed']('/recordings', 'GET')}
    password = os.getenv('SAWT_DEMO_PASSWORD', '')
    report['demo_password_available_to_job'] = bool(password)
    for label, url in (('production', PRODUCTION),):
        surface = report['surfaces'][label] = {'url': url, 'authenticated': False}
        headers = {'Origin': url}
        access = os.getenv('SAWT_ACCESS_CODE', '')
        if access:
            headers['X-Access-Code'] = access
        async with httpx.AsyncClient(base_url=url, headers=headers, timeout=15, follow_redirects=False) as client:
            for path in ('/', '/login', '/api/health'):
                try:
                    surface[path] = safe_response(await client.get(path))
                except Exception as exc:
                    surface[path] = {'error_type': type(exc).__name__}
            if password:
                try:
                    login = await client.post('/login', data={'password': password})
                    surface['login_status'] = login.status_code
                    surface['authenticated'] = login.status_code == 303 and bool(client.cookies.get('__Host-sawt-demo'))
                except Exception as exc:
                    surface['login_error_type'] = type(exc).__name__
            else:
                surface['authenticated_checks_blocked'] = 'SAWT_DEMO_PASSWORD is unavailable to this Actions job; no password attempted'
            if surface['authenticated']:
                for path in ('/', '/api/health', '/api/experience', '/assets/experience-ui.js'):
                    surface['authenticated ' + path] = safe_response(await client.get(path))
                if label == 'production':
                    await worker_probe(client, surface)
    report['status'] = 'STARTUP_VERIFIED_ONLY' if report['surfaces']['production'].get('worker_v3_startup_verified') else 'BLOCKED_OR_FAILED'
    (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # An unavailable/failed check must never make the release indicator green.
    return 0 if report['status'] == 'STARTUP_VERIFIED_ONLY' and report['source_gateway_checks']['call_creation_allowed'] and report['source_gateway_checks']['admin_blocked'] else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
