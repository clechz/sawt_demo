"""Paid HTTPS/LiveKit smoke using a synthetic caller; no browser microphone.

Reads credentials only from ignored runtime/private-demo.json. Requires the
pre-generated runtime/release-order.mp3 fixture. Never outputs credentials.
"""
import asyncio
import argparse
import array
import math
import json
import sys
import time
from pathlib import Path
import av
import httpx
from livekit import rtc

ROOT=Path(__file__).resolve().parents[1]

async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url')
    parser.add_argument('--output',type=Path,default=ROOT/'evidence/v2/private-demo-smoke.json')
    args=parser.parse_args()
    config=json.loads((ROOT/'runtime/private-demo.json').read_text(encoding='utf8'))
    base=args.url or config['url']; checks={}; frames=0; events=[]; tasks=[]; call=None; source=None; publication=None
    room=rtc.Room(); audible=[]
    async def listen(track):
        nonlocal frames
        stream=rtc.AudioStream(track)
        try:
            async for packet in stream:
                frames+=1
                samples=array.array('h',packet.frame.data.tobytes())
                rms=math.sqrt(sum(x*x for x in samples)/max(1,len(samples)))/32768
                if rms>.01:audible.append(time.monotonic())
        finally:
            await stream.aclose()
    @room.on('track_subscribed')
    def subscribed(track,publication,participant):
        if track.kind==rtc.TrackKind.KIND_AUDIO:tasks.append(asyncio.create_task(listen(track)))
    @room.on('data_received')
    def data(packet):
        if packet.topic=='sawt':events.append(json.loads(packet.data))
    async with httpx.AsyncClient(base_url=base,timeout=45,headers={'Origin':base}) as client:
        try:
            checks['anonymous_blocked']=(await client.get('/api/health')).status_code==401
            login=await client.post('/login',data={'password':config['password']})
            checks['login']=login.status_code==303
            checks['root']=(await client.get('/')).status_code==200
            checks['archives_blocked']=(await client.get('/api/recordings')).status_code==404
            checks['lab_blocked']=(await client.get('/lab')).status_code==404
            assert all(checks.values()),checks
            response=await client.post('/api/calls',json={'recording_consent':True})
            response.raise_for_status();call=response.json()
            auth={'Authorization':'Bearer '+call['token']}
            checks['call_token_required']=(await client.get('/api/calls/'+call['id'])).status_code==404
            await room.connect(call['url'],call['room_token'])
            source=rtc.AudioSource(24000,1)
            track=rtc.LocalAudioTrack.create_audio_track('synthetic-caller',source)
            publication=await room.local_participant.publish_track(track,rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
            async with asyncio.timeout(40):
                while not any(e.get('type')=='ready' for e in events):await asyncio.sleep(.2)
            checks['voice_ready']=True
            await asyncio.sleep(7)
            with av.open(str(ROOT/'runtime/release-order.mp3')) as container:
                resampler=av.AudioResampler(format='s16',layout='mono',rate=24000)
                for decoded in container.decode(audio=0):
                    for pcm in resampler.resample(decoded):
                        await source.capture_frame(rtc.AudioFrame(bytes(pcm.planes[0])[:pcm.samples*2],24000,1,pcm.samples))
            await source.wait_for_playout()
            started=time.monotonic()
            async with asyncio.timeout(50):
                while True:
                    response=await client.get('/api/calls/'+call['id'],headers=auth)
                    response.raise_for_status();saved=response.json()
                    if any(e['kind']=='delegation.completed' for e in saved['events']):break
                    await asyncio.sleep(.5)
            completed=time.monotonic()
            async with asyncio.timeout(20):
                while not any(t>completed for t in audible):await asyncio.sleep(.05)
            state=saved['state']
            checks['heard_synthetic_caller']=any(e['kind']=='transcript.user' for e in saved['events'])
            checks['two_expected_dishes']={x['item_id'] for x in state['basket']}=={'breakfast_06','beverages_09'}
            checks['no_unconfirmed_order']=not state['order_id']
            checks['received_voice_audio']=frames>0
            checks['response_audio_after_saved_order']=any(t>completed for t in audible)
            checks['quantities_correct']={x['item_id']:x['quantity'] for x in state['basket']}=={'breakfast_06':3,'beverages_09':1}
            report={'url':base,'kind':'real_https_and_livekit_synthetic_voice','call_id':call['id'],
                    'checks':checks,'received_audio_frames':frames,'seconds_after_input':round(completed-started,2),
                    'first_audio_after_completed_seconds':round(next(t for t in audible if t>completed)-started,2),
                    'timing_note':'Completion is HTTP-poll observed. Audio is received RMS after completion, not semantic verification or exact first response onset.',
                    'basket':state['basket'],'passed':all(checks.values())}
        finally:
            if call:
                response=await client.post('/api/calls/'+call['id']+'/end',headers={'Authorization':'Bearer '+call['token']})
                checks['closed']=response.status_code==200 and response.json().get('closed') is True
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            if publication:await room.local_participant.unpublish_track(publication.sid)
            if source:await source.aclose()
            await room.disconnect()
        report['passed']=all(checks.values())
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({k:v for k,v in report.items() if k!='basket'},indent=2))
        assert report['passed'],checks

if __name__=='__main__':asyncio.run(main())
