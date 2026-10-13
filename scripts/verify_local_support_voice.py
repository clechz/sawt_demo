"""Paid synthetic support calls against isolated local API/worker; no browser."""
import asyncio, hashlib, json, sys, time
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.v2_cloud_journeys import VoiceCall
from scripts.v2_recognition_replay import decode
from sawt.v2_provider import V2Provider

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    'new_order': ['بكم شاورما الدجاج ساندوتش؟', 'عندي شكوى وأبي أكلم مسؤول.', 'لا شكراً، ما أبي تحويل.'],
    'missing_item': ['طلبي وصل ناقص الشكشوكة، أبي استرجاع قيمتها.', 'نعم أوافق على الاسترجاع.', 'رجع قيمة نفس الشكشوكة مرة ثانية.'],
}

async def main():
    report={'scope':'local SQLite and worker, real LiveKit/OpenAI, synthetic audio; no physical playback/accent score','cases':[]}
    provider=V2Provider(voice='cedar')
    try:
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8773',timeout=60) as client:
            for scenario,texts in CASES.items():
                row={'scenario':scenario,'turns':[],'passed':False};report['cases'].append(row)
                call=VoiceCall(client,{'experience_version':'v3','conversation_mode':'model_led','voice':'cedar','scenario':scenario})
                try:
                    # Prepare caller speech before opening a billed call.
                    fixtures=[]
                    for text in texts:
                        path=ROOT/'runtime'/('support-'+hashlib.sha256(text.encode()).hexdigest()[:16]+'.mp3')
                        if not path.exists():path.write_bytes(await provider.speak(text))
                        fixtures.append(decode(path))
                    await call.start();row['call_id']=call.call['id']
                    for index,text in enumerate(texts):
                        pcm=fixtures[index];await call.state();floor=call.cursor
                        for i in range(0,len(pcm),4800):await call.queue.put(pcm[i:i+4800].ljust(4800,b'\0'))
                        while not call.queue.empty():await asyncio.sleep(.1)
                        await asyncio.sleep(.25);started=time.monotonic()
                        async with asyncio.timeout(40):
                            while True:
                                saved=await call.state();events=[e for e in saved['events'] if e['sequence']>floor]
                                assert not any(e['kind'] in ('delegation.failed','transcript.unverified') for e in events),'Request failed or needed clarification'
                                if any(e['kind']=='delegation.completed' for e in events):break
                                await asyncio.sleep(.2)
                        mode=next(e['payload']['speech_mode'] for e in reversed(events) if e['kind']=='delegation.completed')
                        state=saved['state'];h=state['hospitality'];elapsed=round(time.monotonic()-started,2)
                        assert not state['order_id'] and not state['basket']
                        if scenario=='new_order':
                            if index==0:assert not h['cases']
                            if index==1:assert h['cases'] and h['pending_resolution']
                            if index==2:assert not h['pending_resolution'] and not h['ledger']
                        else:
                            if index==0:assert h['pending_resolution'] and not h['ledger']
                            else:assert len(h['ledger'])==1 and h['ledger'][0]['amount_halalas']==3000
                        # A listening acknowledgement is not the exact support proposal.
                        # Wait for its actual playout completion before accepting it.
                        async with asyncio.timeout(35):
                            while True:
                                speech=[at for at,rms in call.output if at>=started and rms>.01]
                                latest=await call.state()
                                done=[e for e in latest['events'] if e['sequence']>floor and e['kind']=='voice.result_playout']
                                if mode=='live' and speech and time.monotonic()-speech[-1]>1.2:break
                                if done:
                                    assert done[-1]['payload']['completed'],'Exact result was interrupted'
                                    if speech and time.monotonic()-speech[-1]>1.2:break
                                await asyncio.sleep(.2)
                        row['turns'].append({'input':text,'state_seconds':elapsed,'first_audio_including_backchannel_seconds':round(speech[0]-started,2),'passed':True})
                        print(json.dumps(row['turns'][-1],ensure_ascii=False),flush=True)
                    row['passed']=True
                except Exception as exc:
                    row['error']=type(exc).__name__+': '+str(exc)
                    row['cause']=type(exc.__cause__).__name__ if exc.__cause__ else None
                    print(row['error'],flush=True)
                finally:await call.close()
    finally:
        await provider.aclose()
        report['passed']=bool(report['cases']) and all(c['passed'] for c in report['cases'])
        (ROOT/'runtime/local-support-voice.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    assert report['passed'],'See local-support-voice.json; failed attempts are not passes'

if __name__=='__main__':asyncio.run(main())
