"""Headless cloud voice/order acceptance; no Chrome or local server.

Caller audio is synthetic. Readback is downloaded/decoded and its playback
receipt is simulated after the actual duration; this is not a human UX rating.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
import httpx
from livekit import rtc
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.v2_recognition_replay import decode
from sawt.v2_provider import V2Provider
from scripts.cloud_test_capacity import create_call

ROOT=Path(__file__).resolve().parents[1]
BASE='https://sawt-demo.vercel.app'


async def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--wait-for-capacity-seconds',type=float,default=0);args=parser.parse_args()
    phrases={
        'order':'أبي شكشوكة عدد اثنين، حجم كبير، خبز تميس، استلام من فرع النرجس بالرياض. هذا كل طلبي، اقرأ ملخص الطلب.',
        'yes':'نعم، اعتمد الطلب.',
        'correct':'لا، خل الشكشوكة واحدة بدل اثنين، والباقي نفسه. اقرأ ملخص الطلب.',
        'summary':'اقرأ لي ملخص الطلب من جديد.'}
    audio={};provider=V2Provider()
    try:
        for name,text in phrases.items():
            path=ROOT/'runtime'/('cloud-'+name+'.mp3')
            if not path.exists():path.write_bytes(await provider.speak(text))
            audio[name]=decode(path)
    finally:await provider.aclose()
    room=rtc.Room();events=[];tasks=[];frames=0;queue=asyncio.Queue();stop=asyncio.Event()
    call=None;source=None;pump_task=None;checks={};turns=[];audit_events=[]
    async def listen(track):
        nonlocal frames
        stream=rtc.AudioStream(track)
        try:
            async for frame in stream:frames+=1
        finally:await stream.aclose()
    @room.on('track_subscribed')
    def subscribed(track,publication,participant):
        if track.kind==rtc.TrackKind.KIND_AUDIO:tasks.append(asyncio.create_task(listen(track)))
    @room.on('data_received')
    def received(packet):
        if packet.topic=='sawt':events.append(json.loads(packet.data))
    async def pump():
        while not stop.is_set():
            try:chunk=queue.get_nowait()
            except asyncio.QueueEmpty:chunk=b'\0'*4800
            await source.capture_frame(rtc.AudioFrame(chunk,24000,1,len(chunk)//2))
    password=json.loads((ROOT/'runtime/private-demo.json').read_text())['password']
    async with httpx.AsyncClient(base_url=BASE,headers={'Origin':BASE},timeout=60) as client:
        try:
            assert (await client.post('/login',data={'password':password})).status_code==303
            call=await create_call(client,args.wait_for_capacity_seconds)
            auth={'Authorization':'Bearer '+call['token']}
            await room.connect(call['url'],call['room_token'])
            source=rtc.AudioSource(24000,1,queue_size_ms=100)
            track=rtc.LocalAudioTrack.create_audio_track('cloud-acceptance',source)
            await room.local_participant.publish_track(track,rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
            pump_task=asyncio.create_task(pump())
            async with asyncio.timeout(60):
                while not any(e.get('type')=='ready' for e in events):await asyncio.sleep(.2)
            await asyncio.sleep(7)
            cursor=0
            async def state():
                nonlocal cursor
                while True:
                    response=await client.get('/api/calls/'+call['id'],headers=auth,params={'after':cursor});response.raise_for_status();saved=response.json()
                    batch=saved['events'];audit_events.extend(batch)
                    if batch:cursor=batch[-1]['sequence']
                    if len(batch)<500:break
                return {**saved,'events':list(audit_events)}
            async def turn(name):
                prior=await state();floor=max((e['sequence'] for e in prior['events']),default=0)
                assert any(e['kind']=='voice.connected' and e['payload'].get('release')==os.getenv('SAWT_EXPECT_WORKER_RELEASE','conversation-v18') for e in prior['events']), 'Cloud worker has not rolled over to the expected release yet'
                for i in range(0,len(audio[name]),4800):await queue.put(audio[name][i:i+4800].ljust(4800,b'\0'))
                while not queue.empty():await asyncio.sleep(.1)
                await asyncio.sleep(.25);started=time.monotonic()
                async with asyncio.timeout(60):
                    while True:
                        saved=await state()
                        recent=[e for e in saved['events'] if e['sequence']>floor]
                        if any(e['kind']=='delegation.completed' for e in recent):break
                        if any(e['kind'] in ('delegation.failed','transcript.unverified') for e in recent):raise AssertionError('Voice turn failed: '+name)
                        await asyncio.sleep(.3)
                elapsed=round(time.monotonic()-started,2)
                await asyncio.sleep(4)
                saved=await state()
                turns.append({'name':name,'seconds_after_input':elapsed,'state':saved['state']})
                print('Completed cloud turn: '+name,flush=True)
                return saved['state']
            async def present_readback():
                response=await client.post('/api/calls/'+call['id']+'/readback',headers=auth);response.raise_for_status();receipt=response.json()
                response=await client.get(receipt['url']);response.raise_for_status()
                path=ROOT/'runtime/cloud-readback.mp3';path.write_bytes(response.content)
                duration=len(decode(path))/48000
                checks['readback_real_audio']=duration>2;assert checks['readback_real_audio']
                endpoint='/api/calls/'+call['id']+'/playback'
                body={'receipt_id':receipt['receipt_id'],'phase':'started'}
                (await client.post(endpoint,headers=auth,json=body)).raise_for_status()
                early=await client.post(endpoint,headers=auth,json={**body,'phase':'completed','position':duration})
                checks['premature_playback_rejected']=early.status_code==409;assert checks['premature_playback_rejected']
                await asyncio.sleep(duration+.2)
                (await client.post(endpoint,headers=auth,json={**body,'phase':'completed','position':duration})).raise_for_status()
                return {**receipt, 'decoded_duration':duration}
            s=await turn('order')
            checks['two_items_exact_total']=len(s['basket'])==1 and s['basket'][0]['quantity']==2 and s['total']==6000 and s['branch_id']=='ruh_narjis'
            assert checks['two_items_exact_total']
            s=await turn('yes')
            checks['unheard_yes_not_confirmed']=not s['order_id'];assert checks['unheard_yes_not_confirmed']
            old_receipt=await present_readback()
            checks['initial_readback_presented']=(await state())['state']['quote']['presented']
            s=await turn('correct')
            checks['correction_no_duplicate']=len(s['basket'])==1 and s['basket'][0]['quantity']==1 and s['total']==3000 and not s['order_id']
            assert checks['correction_no_duplicate']
            stale=await client.post('/api/calls/'+call['id']+'/playback',headers=auth,json={'receipt_id':old_receipt['receipt_id'],'phase':'completed','position':old_receipt['decoded_duration']})
            checks['edit_invalidates_old_playback']=stale.status_code==409
            assert checks['edit_invalidates_old_playback']
            if not s['quote']:s=await turn('summary')
            await present_readback()
            s=await turn('yes');order=s['order_id'];checks['confirmed_after_readback']=bool(order);assert order
            s=await turn('yes');checks['repeat_yes_same_order']=s['order_id']==order;assert checks['repeat_yes_same_order']
            checks['cloud_worker_audio_received']=frames>0
        finally:
            if call:
                response=await client.post('/api/calls/'+call['id']+'/end',headers={'Authorization':'Bearer '+call['token']})
                checks['closed']=response.status_code==200
            stop.set()
            if pump_task:await asyncio.wait_for(pump_task,3)
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            await room.disconnect()
            if source:await source.aclose()
            report={'base':BASE,'call_id':call and call['id'],'checks':checks,'turns':turns,
                    'worker_release':next((e['payload'].get('release') for e in audit_events if e['kind']=='voice.connected'),None),
                    'passed':len(turns)>=5 and all(checks.values()),
                    'playback':'Downloaded and decoded actual cloud speech; elapsed playback receipt simulated; no browser.'}
            (ROOT/'runtime/cloud-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    assert report['passed'],checks
    print(json.dumps({'passed':True,'call_id':call['id'],'checks':checks},indent=2))


if __name__=='__main__':
 import gc
 try:asyncio.run(main())
 finally:gc.collect()
