"""Paid cloud V3/Ash call: actual PCM, saved state and timed exact readbacks. No Chrome."""
import asyncio,hashlib,io,json,sys,time,wave
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
    report={'scope':'synthetic caller, real LiveKit audio and cloud state; timed simulated readback receipts; no human accent score','passed':False,'turns':[]}
    p=V2Provider(voice='ash');call=None
    try:
        audio=[]
        for text in TEXTS:
            path=ROOT/'runtime'/('challenge-'+hashlib.sha256(text.encode()).hexdigest()[:16]+'.mp3')
            if not path.exists():path.write_bytes(await p.speak(text))
            audio.append(decode(path))
        password=json.loads((ROOT/'runtime/private-demo.json').read_text())['password']
        async with httpx.AsyncClient(base_url='https://sawt-demo.vercel.app',headers={'Origin':'https://sawt-demo.vercel.app'},timeout=60) as client:
            assert (await client.post('/login',data={'password':password})).status_code==303
            call=VoiceCall(client,{'experience_version':'v3','conversation_mode':'model_led','voice':'ash','scenario':'new_order'})
            try:
                await call.start(120)
                saved=await call.state()
                binding=next(e['payload']['worker_contract'] for e in saved['events'] if e['kind']=='voice.connected')
                check_worker_contract(worker_contract(validate_experience('ash',conversation_mode='model_led')),binding)
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
                        await asyncio.sleep(5)
                        audible=next((at-started for at,rms in call.output if at>started and rms>.01),None)
                        assert audible is not None,'No audible confirmation'
                        row['first_received_audio_seconds']=round(audible,2)
                    row['passed']=True;print(json.dumps(row,ensure_ascii=False),flush=True)
                report['passed']=True
            finally:await call.close()
    except Exception as e:
        report['error']=str(e)[:300];print(json.dumps({'error':report['error']},ensure_ascii=False),flush=True)
    finally:
        await p.aclose();(ROOT/'runtime/challenge-voice.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    assert report['passed'],'Cloud voice gate failed; inspect runtime/challenge-voice.json'
if __name__=='__main__':asyncio.run(main())
