"""One authorized production startup probe; not a conversation-quality test."""
import asyncio
import datetime as dt
import hashlib
import json
import logging
import os
from pathlib import Path
import struct
import sys
import wave

import httpx
from livekit import rtc
from sawt.release_contract import source_fingerprint, check_worker_contract

BASE = 'https://sawt-demo.vercel.app'
OUT = Path('/tmp/sawt-production-startup')
OUT.mkdir(parents=True, exist_ok=True)
report = {'checked_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    'source_commit': '3442e711a93b4343090b0f3b3732712a4685b9a8',
    'status': 'BLOCKED', 'checks': {}, 'complete_conversation_test': False,
    'scope': 'One synthetic-silence call: deployed source, worker binding, returned audio and closure. No order or refund submitted.'}
logging.getLogger('httpx').setLevel(logging.WARNING)

async def main():
    password = os.getenv('SAWT_DEMO_PASSWORD', '')
    if not password:
        report['blocked_at'] = 'SAWT_DEMO_PASSWORD missing from this job'
        return
    events = []
    tasks = []
    room = None
    source = None
    call = None
    wavefile = None
    frames = 0
    nonzero = 0
    fatal = []
    headers = {'Origin': BASE}
    if os.getenv('SAWT_ACCESS_CODE'):
        headers['X-Access-Code'] = os.environ['SAWT_ACCESS_CODE']
    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=20, follow_redirects=False) as client:
        try:
            report['phase'] = 'login'
            response = await client.post('/login', data={'password': password})
            report['login_http_status'] = response.status_code
            if response.status_code != 303 or not client.cookies.get('__Host-sawt-demo'):
                report['blocked_at'] = 'demo_login'
                return
            report['checks']['authenticated_login'] = True
            report['phase'] = 'production_assets'
            assets = {}
            for name in ('app.js', 'worker-binding.js', 'experience-ui.js'):
                response = await client.get('/assets/' + name)
                expected = hashlib.sha256((Path('static/v2') / name).read_bytes()).hexdigest()
                actual = hashlib.sha256(response.content).hexdigest()
                assets[name] = {'http_status': response.status_code, 'matches_source': response.status_code == 200 and expected == actual}
            report['assets'] = assets
            report['checks']['production_assets_match'] = all(x['matches_source'] for x in assets.values())
            if not report['checks']['production_assets_match']:
                report['status'] = 'FAILED'
                return
            response = await client.get('/api/health')
            report['health_http_status'] = response.status_code
            response.raise_for_status()
            report['health_configured'] = response.json().get('configured')
            response = await client.get('/api/experience')
            report['experience_catalog_http_status'] = response.status_code
            report['phase'] = 'create_call'
            requested = {'recording_consent': True, 'voice': 'cedar', 'scenario': 'new_order',
                'experience_version': 'v3', 'conversation_mode': 'model_led'}
            response = await client.post('/api/calls', json=requested)
            report['call_creation_http_status'] = response.status_code
            if response.status_code != 200:
                report['blocked_at'] = 'call_creation'
                return
            call = response.json()
            report['call_id'] = call['id']
            required = call.get('required_worker', {})
            report['required_worker'] = required
            report['checks']['api_mode_and_source_match'] = (
                call.get('conversation_mode') == 'model_led' and call.get('experience_version') == 'v3'
                and call.get('voice') == 'cedar' and required.get('source_fingerprint') == source_fingerprint())
            if not report['checks']['api_mode_and_source_match']:
                report['status'] = 'FAILED'
                return
            room = rtc.Room()
            async def listen(track):
                nonlocal frames, nonzero, wavefile
                stream = rtc.AudioStream(track, sample_rate=24000, num_channels=1)
                try:
                    async for event in stream:
                        data = bytes(event.frame.data)
                        if wavefile is None:
                            wavefile = wave.open(str(OUT / 'received-assistant.wav'), 'wb')
                            wavefile.setnchannels(1)
                            wavefile.setsampwidth(2)
                            wavefile.setframerate(24000)
                        wavefile.writeframesraw(data)
                        frames += 1
                        nonzero += sum(abs(s[0]) > 100 for s in struct.iter_unpack('<h', data))
                finally:
                    await stream.aclose()
            @room.on('track_subscribed')
            def subscribed(track, publication, participant):
                if track.kind == rtc.TrackKind.KIND_AUDIO:
                    tasks.append(asyncio.create_task(listen(track)))
            @room.on('data_received')
            def received(packet):
                if packet.topic != 'sawt':
                    return
                try:
                    value = json.loads(packet.data)
                    if value.get('type') == 'ready':
                        events.append({key: value.get(key) for key in ('type', 'call_id', 'conversation_mode', 'worker_release', 'worker_contract')})
                    elif value.get('type') == 'error':
                        fatal.append({key: value.get(key) for key in ('type', 'code', 'fatal')})
                except (ValueError, TypeError):
                    pass
            async def pump():
                while True:
                    await source.capture_frame(rtc.AudioFrame(b'\0' * 960, 24000, 1, 480))
                    await asyncio.sleep(.02)
            report['phase'] = 'worker_startup'
            async with asyncio.timeout(80):
                await room.connect(call['url'], call['room_token'])
                source = rtc.AudioSource(24000, 1, queue_size_ms=100)
                track = rtc.LocalAudioTrack.create_audio_track('authorized-startup-probe', source)
                await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
                tasks.append(asyncio.create_task(pump()))
                while not events and not fatal:
                    await asyncio.sleep(.2)
                if fatal:
                    report['status'] = 'FAILED'
                    return
                actual = events[-1]
                report['received_ready'] = actual
                check_worker_contract(required, actual.get('worker_contract'))
                if actual.get('call_id') != call['id']:
                    raise ValueError('Call identity mismatch')
                report['checks']['worker_binding_match'] = True
                await asyncio.sleep(10)
                report['checks']['nonzero_audio_received'] = nonzero > 100
            report['status'] = 'STARTUP_PASS' if all(report['checks'].values()) else 'FAILED'
        except Exception as exc:
            report['status'] = 'FAILED'
            report['error_type'] = type(exc).__name__
        finally:
            report['audio'] = {'received_frames': frames, 'nonzero_samples': nonzero, 'customer_input': 'synthetic silence only'}
            report['errors'] = fatal
            if call:
                auth = {'Authorization': 'Bearer ' + call['token']}
                try:
                    response = await client.post('/api/calls/' + call['id'] + '/end', headers=auth)
                    report['checks']['test_call_closed'] = response.status_code == 200
                except Exception as exc:
                    report['close_error_type'] = type(exc).__name__
                    report['checks']['test_call_closed'] = False
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if room is not None:
                await room.disconnect()
            if source is not None:
                await source.aclose()
            if wavefile is not None:
                wavefile.close()
            if call:
                archive = None
                for _ in range(10):
                    try:
                        response = await client.get('/api/calls/' + call['id'], headers=auth)
                        response.raise_for_status()
                        state = response.json()
                        report['final_call_closed'] = state.get('closed')
                        report['unexpected_order_created'] = bool(state.get('state', {}).get('order_id'))
                        for event in state.get('events', []):
                            if event.get('kind') in ('recording.archived', 'recording.archive_failed'):
                                archive = event['kind']
                        if archive:
                            break
                    except Exception as exc:
                        report['archive_query_error_type'] = type(exc).__name__
                        break
                    await asyncio.sleep(2)
                report['recording_archive_event'] = archive
                if not report['checks'].get('test_call_closed') or report.get('unexpected_order_created'):
                    report['status'] = 'FAILED'

try:
    asyncio.run(main())
finally:
    (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(0 if report['status'] == 'STARTUP_PASS' else 1)
