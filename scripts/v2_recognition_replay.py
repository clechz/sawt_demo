"""Paid recognition regression over actual LiveKit media, with continuous input.

--recording replays the explicitly approved caller recording; omitted means
synthetic fixtures only. Never assume ASR output is human-verified ground truth.
"""
import argparse,asyncio,io,json,sys,time,wave
from pathlib import Path
import av,httpx
from livekit import rtc
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sawt.v2_provider import V2Provider
from sawt.provider import config
ROOT=Path(__file__).resolve().parents[1]

def decode(path):
    chunks=[]
    with av.open(str(path)) as container:
        resampler=av.AudioResampler(format='s16',layout='mono',rate=24000)
        for frame in container.decode(audio=0):
            for pcm in resampler.resample(frame):chunks.append(bytes(pcm.planes[0])[:pcm.samples*2])
        for pcm in resampler.resample(None):chunks.append(bytes(pcm.planes[0])[:pcm.samples*2])
    return b''.join(chunks)

async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording',type=Path)
    parser.add_argument('--edges',action='store_true',help='Synthetic quantities, corrections, code switching, negation, noise and unheard confirmation')
    parser.add_argument('--only', choices=['price','farewell'], help='Short independent-call smoke check')
    parser.add_argument('--start-delay',type=float,default=0,help='Delay first speech after ready to exercise overlapping calls')
    parser.add_argument('--output',type=Path,default=ROOT/'evidence/v2/recognition-live-replay.json')
    args=parser.parse_args();config()
    fixtures={'price':'بكم سندويش الشاورما؟','complaint':'يا حبيبي، أنت ما قاعد تتكلم.',
              'wait':'انتظر شوي لو سمحت.','resume':'أبي تميس بالعسل حجم عادي وخبز أسمر، استلام من فرع النرجس بالرياض.',
              'keep_open':'لا تقفل المكالمة، خلها مفتوحة.'}
    if args.edges:
        fixtures={'quantity':'أبي ثلاثة تميس بالعسل، حجم عادي وخبز أسمر، استلام من فرع النرجس بالرياض.',
                  'correction':'لا، خل التميس اثنين، مو ثلاثة.',
                  'mixed':'And two karak, large, no ice, half sugar.',
                  'negation':'لا تضيف شاورما. هذا كل طلبي، اقرأ ملخص الطلب.',
                  'unheard_yes':'نعم.', 'noise':''}
    if args.only:fixtures={args.only:'انهي المكالمة لو سمحت.' if args.only=='farewell' else fixtures[args.only]}
    p=V2Provider();audio={}
    try:
        for name,text in fixtures.items():
            if name=='noise':
                import random,struct
                rng=random.Random(42)
                audio[name]=b''.join(struct.pack('<h',rng.randint(-120,120)) for _ in range(24000*3))
                continue
            path=ROOT/'runtime'/f'recognition-{name}.mp3'
            if not path.exists():path.write_bytes(await p.speak(text))
            audio[name]=decode(path)
    finally:await p.aclose()
    if args.recording:
        with wave.open(str(args.recording)) as w:
            assert w.getframerate()==24000 and w.getnchannels()==1 and w.getsampwidth()==2
            original=w.readframes(w.getnframes())
        audio['price']=original[24*48000:37*48000]
        audio['complaint']=original[48*48000:]
    room=rtc.Room();media_tasks=[];events=[];chunks=asyncio.Queue();source=None;pub=None;call=None;pump_task=None;stop_pump=asyncio.Event()
    output_levels=[];timeline=time.monotonic();checks={};turns=[];saved={}
    async def listen(track):
        import array,math
        stream=rtc.AudioStream(track,sample_rate=24000,num_channels=1)
        try:
            async for item in stream:
                values=array.array('h',item.frame.data.tobytes())
                rms=math.sqrt(sum(v*v for v in values)/max(1,len(values)))/32768
                output_levels.append((time.monotonic(),rms))
        finally:await stream.aclose()
    @room.on('track_subscribed')
    def subscribed(track,publication,participant):
        if track.kind==rtc.TrackKind.KIND_AUDIO:media_tasks.append(asyncio.create_task(listen(track)))
    @room.on('data_received')
    def received(packet):
        if packet.topic=='sawt':events.append({'at':time.monotonic(),**json.loads(packet.data)})
    async def pump():
        while not stop_pump.is_set():
            try:chunk=chunks.get_nowait()
            except asyncio.QueueEmpty:chunk=b'\0'*4800
            await source.capture_frame(rtc.AudioFrame(chunk,24000,1,len(chunk)//2))
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8766',timeout=45) as client:
        try:
            response=await client.post('/api/calls',json={'recording_consent':True});response.raise_for_status();call=response.json()
            auth={'Authorization':'Bearer '+call['token']}
            await room.connect(call['url'],call['room_token'])
            source=rtc.AudioSource(24000,1,queue_size_ms=100)
            track=rtc.LocalAudioTrack.create_audio_track('recognition-regression',source)
            pub=await room.local_participant.publish_track(track,rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
            pump_task=asyncio.create_task(pump())
            async with asyncio.timeout(35):
                while not any(e['type']=='ready' for e in events):await asyncio.sleep(.2)
            await asyncio.sleep(7 + max(0,args.start_delay))
            for name in fixtures:
                t=time.monotonic();floor=max([e['sequence'] for e in saved.get('events',[])],default=0)
                previous_basket=saved.get('state',{}).get('basket',[])
                for i in range(0,len(audio[name]),4800):await chunks.put(audio[name][i:i+4800].ljust(4800,b'\0'))
                while not chunks.empty():await asyncio.sleep(.1)
                # The pump keeps sending silence, so its source never empties.
                # Allow the bounded 100 ms media queue to play the final chunk.
                await asyncio.sleep(.25)
                input_end=time.monotonic()
                target='call.closed' if name=='farewell' else 'call.wait_requested' if name=='wait' else 'call.audio_check' if name=='complaint' else 'delegation.completed'
                if name=='noise':await asyncio.sleep(5)
                async with asyncio.timeout(30):
                    while True:
                        response=await client.get('/api/calls/'+call['id'],headers=auth);response.raise_for_status();saved=response.json()
                        recent=[e for e in saved['events'] if e['sequence']>floor]
                        if name=='noise' or any(e['kind']==target for e in recent) or saved['closed']:break
                        if any(e['kind']=='transcript.unverified' for e in recent):raise AssertionError('Audio verification failed: '+json.dumps(recent,ensure_ascii=False))
                        await asyncio.sleep(.3)
                row={'name':name,'seconds_after_input':round(time.monotonic()-input_end,2),
                     'events':[e for e in recent if e['kind'] in ('transcript.fragment','transcript.verified','delegation.completed','call.wait_requested','call.audio_check','call.goodbye_completed','call.goodbye_failed','call.closed','call.end_requested')],
                     'basket':saved['state']['basket']}
                turns.append(row)
                if name=='price':
                    replies=' '.join(e['payload'].get('reply','') for e in recent if e['kind']=='delegation.completed')
                    checks['price_answer']='18' in replies and '22' in replies and not saved['state']['basket']
                if name=='complaint':
                    checks['complaint_recovers_not_waits']=any(e['kind']=='call.audio_check' for e in recent) and not any(e['kind']=='call.wait_requested' for e in recent)
                    await asyncio.sleep(5)
                    checks['speech_after_recovery']=any(at>input_end and rms>.01 for at,rms in output_levels)
                if name=='wait':
                    wait_at=time.monotonic();await asyncio.sleep(4)
                    checks['quiet_after_wait']=not any(at>wait_at+1 and rms>.01 for at,rms in output_levels)
                if name=='resume':
                    state=saved['state'];checks['resume_order']=len(state['basket'])==1 and state['basket'][0]['item_id']=='breakfast_05' and state['basket'][0]['options']=={'portion':['regular'],'bread':['brown']} and state['branch_id']=='ruh_narjis'
                if name=='keep_open':checks['negated_hangup_keeps_call']=not saved['closed']
                if name=='quantity':checks['spoken_quantity_three']=len(saved['state']['basket'])==1 and saved['state']['basket'][0]['quantity']==3
                if name=='correction':checks['quantity_corrected_not_duplicated']=len(saved['state']['basket'])==1 and saved['state']['basket'][0]['quantity']==2
                if name=='mixed':
                    karak=next((x for x in saved['state']['basket'] if x['item_id']=='beverages_09'),None)
                    checks['english_quantity_and_modifiers']=bool(karak and karak['quantity']==2 and karak['options']=={'size':['large'],'ice':['none'],'sweetness':['half']})
                if name=='negation':checks['negated_item_not_added']=all(x['item_id'] not in ('sandwiches_07','sandwiches_08') for x in saved['state']['basket'])
                if name=='unheard_yes':checks['yes_cannot_confirm_unheard_readback']=not saved['state']['order_id']
                if name=='noise':checks['noise_no_basket_change']=saved['state']['basket']==previous_basket
                if name=='farewell':
                    checks['requested_hangup_closes']=saved['closed']
                    checks['closing_playout_completed']=any(e['kind']=='call.goodbye_completed' for e in recent)
                    checks['closing_audio_received']=any(at>input_end and rms>.01 for at,rms in output_levels)
                checks['no_unconfirmed_order']=not saved['state']['order_id']
                print(json.dumps({'turn':name,'checks':checks,'verified':[e['payload'].get('text') for e in recent if e['kind']=='transcript.verified']},ensure_ascii=False),flush=True)
                assert all(checks.values()),checks
                await asyncio.sleep(5)
        finally:
            if call:await client.post('/api/calls/'+call['id']+'/end',headers={'Authorization':'Bearer '+call['token']})
            stop_pump.set()
            if pump_task:
                await asyncio.wait_for(pump_task,3)
                await source.wait_for_playout()
            for task in media_tasks:task.cancel()
            await asyncio.gather(*media_tasks,return_exceptions=True)
            if pub:await room.local_participant.unpublish_track(pub.sid)
            if source:await source.aclose()
            await room.disconnect()
            report={'passed':len(turns)==len(fixtures) and all(checks.values()),'call_id':call and call['id'],'checks':checks,'turns':turns,
                    'caller':'approved original price/complaint clips plus synthetic controls/order' if args.recording else 'synthetic',
                    'limitations':'Real media transport and received output RMS; no independent human accent rating.'}
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('Recognition live replay PASS',flush=True)

if __name__=='__main__':asyncio.run(main())
