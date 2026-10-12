"""Real received speech review, not just basket assertions; synthetic caller only.

Each turn waits for response silence. Saves actually received audio and a second
transcription for inspection. This does not score a human accent or certify WER.
"""
import argparse, asyncio, array, hashlib, io, json, math, os, re, sys, time, wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from livekit import rtc
from scripts.v2_cloud_journeys import VoiceCall, step, ROOT
from scripts.v2_recognition_replay import decode
from sawt.v2_provider import V2Provider
from app_v2 import audio_duration

TURNS=[
    step('طال عمرك أبغى شاورما.',basket_count=0,reply_contains=['دجاج','لحم']),
    step('دجاج ساندويتش بصاج بدون حار.',items={'sandwiches_07':{'quantity':1,'meal':['sandwich'],'bread':['saj'],'spice_level':['not_spicy']}}),
    step('بستلم.',service='pickup'),
    step('استلام.',service='pickup'),
    step('فرع النرجس بالرياض.',branch='ruh_narjis'),
    step('لا خلها اثنين.',items={'sandwiches_07':{'quantity':2}}),
]


def check_fulfillment_speech(heard):
    assert 'توصيل' in heard and any(word in heard for word in ('تستلم','استلام','تستلمه')),'Saved bread must lead to fulfillment question, not a new bread question'
    assert 'أسمر' not in heard and 'اسمر' not in heard,'Voice invented unavailable bread after saving saj'

class ReviewedCall(VoiceCall):
    def __init__(self,client):
        super().__init__(client);self.frames=[]
    async def listen(self,track):
        stream=rtc.AudioStream(track,sample_rate=24000,num_channels=1)
        try:
            async for item in stream:
                at=time.monotonic();pcm=item.frame.data.tobytes();values=array.array('h',pcm)
                rms=math.sqrt(sum(v*v for v in values)/max(1,len(values)))/32768
                self.output.append((at,rms));self.frames.append((at,pcm))
        finally:await stream.aclose()
    async def silence(self):
        deadline=time.monotonic()+18
        while time.monotonic()<deadline:
            last=max((at for at,rms in self.output if rms>.01),default=0)
            if time.monotonic()-last>1:return
            await asyncio.sleep(.1)
        raise AssertionError('Assistant did not yield after its reply')
    def wav(self,start):
        out=io.BytesIO()
        with wave.open(out,'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000)
            w.writeframes(b''.join(pcm for at,pcm in self.frames if at>=start))
        return out.getvalue()

async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'runtime/conversation-review.json')
    args=parser.parse_args()
    provider=V2Provider();audio={}
    output=ROOT/'runtime/conversation-review';output.mkdir(exist_ok=True)
    report={'caller':'synthetic','browser':'none','turns':[],'passed':False,
        'limits':'Second transcription of received speech; not human accent, WER or production certification.'}
    try:
        for spec in TURNS:
            text=spec['text'];path=ROOT/'runtime'/('journey-'+hashlib.sha256(text.encode()).hexdigest()[:20]+'.mp3')
            if not path.exists():path.write_bytes(await provider.speak(text))
            audio[text]=decode(path)
        password=os.getenv('SAWT_DEMO_PASSWORD') or json.loads((ROOT/'runtime/private-demo.json').read_text())['password']
        async with httpx.AsyncClient(base_url='https://sawt-demo.vercel.app',headers={'Origin':'https://sawt-demo.vercel.app'},timeout=45) as client:
            assert (await client.post('/login',data={'password':password})).status_code==303
            call=ReviewedCall(client)
            try:
                await call.start(120);report['call_id']=call.call['id']
                saved=await call.state()
                report['worker_release']=next(e['payload'].get('release') for e in saved['events'] if e['kind']=='voice.connected')
                if os.getenv('SAWT_EXPECT_WORKER_RELEASE'):
                    assert report['worker_release']==os.environ['SAWT_EXPECT_WORKER_RELEASE'],'Unexpected worker release'
                for index,spec in enumerate(TURNS):
                    await call.silence();floor=time.monotonic()
                    result=await call.turn(audio[spec['text']],spec,6)
                    await call.silence()
                    path=output/f'received-{index+1}.wav';path.write_bytes(call.wav(floor))
                    if result['state']['quote'] and not result['state']['quote']['presented']:
                        endpoint='/api/calls/'+call.call['id']
                        response=await client.post(endpoint+'/readback',headers=call.auth);response.raise_for_status()
                        receipt=response.json();download=await client.get(receipt['url']);download.raise_for_status()
                        mp3=output/f'readback-{index+1}.mp3';mp3.write_bytes(download.content)
                        pcm=decode(mp3);duration=audio_duration(download.content)
                        with wave.open(str(path),'wb') as w:
                            w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(pcm)
                        body={'receipt_id':receipt['receipt_id'],'phase':'started','position':0}
                        (await client.post(endpoint+'/playback',headers=call.auth,json=body)).raise_for_status()
                        await asyncio.sleep(duration+.2)
                        (await client.post(endpoint+'/playback',headers=call.auth,json={**body,'phase':'completed','position':duration})).raise_for_status()
                        result['speech_source']='downloaded_exact_readback; timed simulated playback'
                    else:result['speech_source']='received_livekit_audio'
                    # Generated synthetic conversations only, never human archives.
                    heard=await provider.recognize(path.read_bytes())
                    assert heard.strip(),'No intelligible received response'
                    result['received_speech']=heard
                    result['audio_path']=str(path.relative_to(ROOT))
                    result['received_speech_passed']=False
                    # Preserve the failed turn too; otherwise the report hides
                    # the exact received speech that caused rejection.
                    report['turns'].append(result)
                    assert result['latency_passed'],'Received-speech turn exceeded its six-second stall threshold'
                    if index==0:assert 'دجاج' in heard and 'لحم' in heard,'Audible dish clarification missing'
                    if index==1:check_fulfillment_speech(heard)
                    if index in (2,3):assert not ('توصيل' in heard and 'استلام' in heard),'Audible service question repeated after pickup'
                    if result['speech_source']=='received_livekit_audio':
                        assert not any(x in heard for x in ['وعليكم السلام','خلني أراجع','دقيقة أتأكد']),'Unrelated greeting or repetitive filler'
                    else:
                        # The authorized checkout starts with خلني أراجع معك.
                        # Require its food, choices, branch and invitation too.
                        from sawt.domain import normalize
                        spoken=normalize(heard)
                        for required in ['شاورما','دجاج','صاج','بدون حار','النرجس','المجموع']:
                            assert normalize(required) in spoken,'Incomplete audible checkout: '+required
                        assert any(x in spoken for x in ['ناكد الطلب','نوكد الطلب','نؤكد الطلب','تاكد الطلب','نكد الطلب']),'Audible confirmation question missing'
                        quantity=result['state']['basket'][0]['quantity']
                        quantity_pattern=r'\b(?:1|واحد)\b' if quantity==1 else r'\b(?:2|اثنين)\b'
                        assert re.search(quantity_pattern,spoken),'Audible checkout quantity missing'
                        total_patterns={1800:r'(?:18|ثمانيه\s*عشر|ثمن(?:ت)?ا?عش(?:ر)?|ثمانتاعشر)',3600:r'(?:36|سته\s*و\s*ثلاثين)'}
                        assert re.search(r'المجموع\s+'+total_patterns[result['state']['total']]+r'\s*ريال',spoken),'Audible checkout total missing or wrong'
                    result['received_speech_passed']=True
                    print(json.dumps({'turn':index+1,'state_s':result['seconds_to_state'],'audio_s':result['first_received_audio_seconds'],'heard':heard},ensure_ascii=False),flush=True)
                saved=await call.state()
                report['scheduler_lag_ms']=[e['payload']['max_lag_ms'] for e in saved['events'] if e['kind']=='voice.scheduler']
                report['passed']=True
            finally:await call.close()
    except Exception as exc:
        report['error']=str(exc) or type(exc).__name__
        raise
    finally:
        await provider.aclose()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')

if __name__=='__main__':asyncio.run(main())
