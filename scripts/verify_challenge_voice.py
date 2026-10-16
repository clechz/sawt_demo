"""Paid V3/Cedar call: actual PCM, saved state and timed exact readbacks. No Chrome."""
import argparse,asyncio,hashlib,io,json,os,ssl,sys,time,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from scripts.v2_cloud_journeys import VoiceCall
from scripts.v2_recognition_replay import decode
from sawt.v2_provider import V2Provider
from sawt.release_contract import worker_contract,check_worker_contract
from sawt.experience import validate_experience
from app_v2 import audio_duration
ROOT=Path(__file__).resolve().parents[1]
TEXTS=[
 'أبي اثنين شاورما دجاج ساندوتش صاج بدون حار، وواحد شاورما لحم ساندوتش صاج حار. استلام من فرع النرجس بالرياض. اقرأ ملخص الطلب.',
 'احذف شاورما اللحم وخلي الدجاج ثلاثة بدل اثنين. اقرأ ملخص الطلب.',
 'غير الاستلام إلى فرع الروضة بجدة وخلي الدجاج حار. اقرأ ملخص الطلب من جديد.',
 'نعم اعتمد الطلب.',
]
async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local', action='store_true', help='Use isolated loopback API on port 8773, without hosted login')
    parser.add_argument('--local-url', default='http://127.0.0.1:8773', help='Local API URL; used only with --local')
    parser.add_argument('--ca-file', type=Path, help='Trusted local CA PEM for HTTPS verification')
    args=parser.parse_args()
    base=args.local_url.rstrip('/') if args.local else 'https://sawt-demo.vercel.app'
    report={'target':base,'scope':'synthetic caller, real LiveKit audio and persisted API state; timed simulated readback receipts; no human accent score','passed':False,'turns':[]}
    p=V2Provider(voice='cedar');call=None
    try:
        audio=[]
        for text in TEXTS:
            path=ROOT/'runtime'/('challenge-'+hashlib.sha256(text.encode()).hexdigest()[:16]+'.mp3')
            if not path.exists():path.write_bytes(await p.speak(text))
            audio.append(decode(path))
        name_text='الطلب باسم عبدالله، اقرأ ملخص الطلب.'
        name_path=ROOT/'runtime/challenge-customer-name.mp3'
        if not name_path.exists():name_path.write_bytes(await p.speak(name_text))
        name_audio=decode(name_path)
        password=None if args.local else (os.getenv('SAWT_DEMO_PASSWORD') or json.loads((ROOT/'runtime/private-demo.json').read_text(encoding='utf8'))['password'])
        async with httpx.AsyncClient(base_url=base,headers={'Origin':base,'X-Access-Code':os.getenv('SAWT_ACCESS_CODE','')},timeout=60,verify=ssl.create_default_context(cafile=str(args.ca_file)) if args.ca_file else True) as client:
            if not args.local:assert (await client.post('/login',data={'password':password})).status_code==303
            call=VoiceCall(client,{'experience_version':'v3','conversation_mode':'model_led','voice':'cedar','scenario':'new_order'})
            received=[]
            call.on_received_audio=lambda at,pcm: received.append((at,pcm))
            try:
                await call.start(120)
                saved=await call.state()
                binding=next(e['payload']['worker_contract'] for e in saved['events'] if e['kind']=='voice.connected')
                check_worker_contract(worker_contract(validate_experience('cedar',conversation_mode='model_led')),binding)
                report['worker_contract']=binding;report['call_id']=call.call['id']
                for index,text in enumerate(TEXTS):
                    floor=call.cursor
                    for i in range(0,len(audio[index]),4800):await call.queue.put(audio[index][i:i+4800].ljust(4800,b'\0'))
                    while not call.queue.empty():await asyncio.sleep(.1)
                    await asyncio.sleep(.25);started=time.monotonic()
                    async with asyncio.timeout(40):
                        while True:
                            saved=await call.state();events=[e for e in saved['events'] if e['sequence']>floor]
                            assert not any(e['kind'] in ('delegation.failed','transcript.unverified') for e in events),'Voice request failed or needed clarification'
                            if any(e['kind']=='delegation.completed' for e in events):break
                            await asyncio.sleep(.2)
                    if index==0 and not saved['state'].get('customer_name'):
                        assert not saved['state']['quote'], 'Checkout bypassed required customer name'
                        question=next(e['payload']['reply'] for e in reversed(events) if e['kind']=='delegation.completed')
                        assert 'اسم' in question, 'Did not ask whose name the order is under'
                        report['name_question']=question
                        # Let the complete question reach the receiver before answering.
                        async with asyncio.timeout(25):
                            while True:
                                snapshot=await call.state()
                                if any(e['sequence']>floor and e['kind']=='voice.result_playout' and e['payload'].get('completed') for e in snapshot['events']):break
                                # Live questions have no exact-TTS completion event.
                                # Wait for received speech and its silence boundary.
                                mode = next((e['payload'].get('speech_mode') for e in reversed(events) if e['kind']=='delegation.completed'), None)
                                audible = [at for at, rms in call.output if at > started and rms > .01]
                                if mode == 'live' and len(audible) >= 5 and time.monotonic()-audible[-1] > .8:
                                    break
                                await asyncio.sleep(.2)
                        floor=call.cursor
                        for i in range(0,len(name_audio),4800):await call.queue.put(name_audio[i:i+4800].ljust(4800,b'\0'))
                        while not call.queue.empty():await asyncio.sleep(.1)
                        await asyncio.sleep(.25);started=time.monotonic()
                        async with asyncio.timeout(40):
                            while True:
                                saved=await call.state();events=[e for e in saved['events'] if e['sequence']>floor]
                                if any(e['kind']=='delegation.completed' for e in events):break
                                await asyncio.sleep(.2)
                        assert ''.join(saved['state']['customer_name'].split())=='عبدالله', 'Customer name was not saved correctly'
                    state=saved['state'];elapsed=round(time.monotonic()-started,2)
                    row={'input':text,'state_seconds':elapsed,'reply':[e['payload']['reply'] for e in events if e['kind']=='delegation.completed'][-1]};report['turns'].append(row)
                    basket=state['basket']
                    if index==0:assert len(basket)==2 and basket[0]['quantity']==2 and state['total']==5800
                    if index in (1,2):assert len(basket)==1 and basket[0]['item_id']=='sandwiches_07' and basket[0]['quantity']==3 and state['total']==5400 and not state['order_id']
                    if index==2:assert state['branch_id']=='jed_rawdah' and basket[0]['options']['spice_level']==['hot']
                    if index<3:
                        assert state['quote'] and not state['quote']['presented'],'Missing fresh quote'
                        endpoint='/api/calls/'+call.call['id']
                        r=await client.post(endpoint+'/readback',headers=call.auth);r.raise_for_status();receipt=r.json()
                        t=time.monotonic();r=await client.get(receipt['url']);r.raise_for_status();duration=audio_duration(r.content)
                        row['readback_download_seconds']=round(time.monotonic()-t,2);row['readback_duration']=round(duration,2)
                        snapshot=await call.state()
                        row['tts_first_byte_ms']=next((e['payload'].get('tts_first_byte_ms') for e in reversed(snapshot['events']) if e['kind']=='readback.first_byte'),None)
                        path=ROOT/'runtime'/f'challenge-readback-{index}.mp3';path.write_bytes(r.content)
                        pcm=decode(path);buf=io.BytesIO()
                        with wave.open(buf,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(pcm)
                        row['received_readback']=await p.recognize(buf.getvalue())
                        assert 'دجاج' in row['received_readback'] and ('صاج' in row['received_readback'] or 'الصاج' in row['received_readback'])
                        if index>0:assert 'لحم' not in row['received_readback'],'Removed item still spoken'
                        body={'receipt_id':receipt['receipt_id'],'phase':'started','position':0}
                        (await client.post(endpoint+'/playback',headers=call.auth,json=body)).raise_for_status()
                        await asyncio.sleep(duration+.2)
                        (await client.post(endpoint+'/playback',headers=call.auth,json={**body,'phase':'completed','position':duration})).raise_for_status()
                    else:
                        assert state['order_id'] and state['total']==5400
                        report['order_id']=state['order_id'];report['final_state']=state
                        # The worker must finish audible success before closing the call.
                        async with asyncio.timeout(35):
                            while True:
                                snapshot=await call.state()
                                if snapshot.get('closed'):break
                                await asyncio.sleep(.2)
                        report['automatic_close_verified']=True
                        assert any(e['sequence']>floor and e['kind']=='call.confirmed_completed' for e in snapshot['events'])
                        audible=next((at-started for at,rms in call.output if at>started and rms>.01),None)
                        assert audible is not None,'No audible confirmation'
                        row['first_received_audio_seconds']=round(audible,2)
                        final_pcm=b''.join(pcm for at,pcm in received if at>started)
                        final_wav=io.BytesIO()
                        with wave.open(final_wav,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(final_pcm)
                        (ROOT/'runtime/received-success.wav').write_bytes(final_wav.getvalue())
                        row['received_success_transcript']=await p.recognize(final_wav.getvalue())
                        from sawt.domain import normalize
                        assert 'تاكد طلبك' in normalize(row['received_success_transcript'])
                        assert 'يعطيك العافيه' in normalize(row['received_success_transcript'])
                        assert 'استلام' in normalize(row['received_success_transcript'])
                        assert state['hospitality']['orders'][state['order_id']]['eta_minutes'] > 0
                        snapshot=await call.state()
                        playout=next(e for e in snapshot['events'] if e['sequence']>floor and e['kind']=='voice.result_playout' and e['payload'].get('completed'))
                        closure=next(e for e in snapshot['events'] if e['sequence']>floor and e['kind']=='call.confirmed_completed')
                        assert playout['sequence'] < closure['sequence'], 'Call closed before complete success playout'
                        assert not any(e['sequence']>floor and e['kind'] in ('voice.task_failed','delegation.failed','playback.failed','readback.failed') for e in snapshot['events']), 'Ending produced a runtime error'
                        assert ''.join(state['customer_name'].split())=='عبدالله'
                        assert state['hospitality']['orders'][state['order_id']]['customer_name']==state['customer_name']
                    row['passed']=True;print(json.dumps(row,ensure_ascii=False),flush=True)
                report['passed']=True
            finally:await call.close()
    except Exception as e:
        report['error']=type(e).__name__+': '+str(e)[:300];print(json.dumps({'error':report['error']},ensure_ascii=False),flush=True)
    finally:
        await p.aclose();(ROOT/'runtime/challenge-voice.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    assert report['passed'],'Cloud voice gate failed; inspect runtime/challenge-voice.json'
if __name__=='__main__':asyncio.run(main())
