"""Paid real-media interruption and disconnect checks; synthetic audio, no browser."""
import asyncio,argparse,hashlib,json,os,sys,time
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.v2_cloud_journeys import VoiceCall,step
from scripts.v2_recognition_replay import decode
from sawt.v2_provider import V2Provider
ROOT=Path(__file__).resolve().parents[1]

async def send(call,pcm):
    for i in range(0,len(pcm),4800):await call.queue.put(pcm[i:i+4800].ljust(4800,b'\0'))
    while not call.queue.empty():await asyncio.sleep(.05)
    await asyncio.sleep(.25)

async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'runtime/cloud-interruptions.json')
    parser.add_argument('--local',action='store_true',help='Use isolated V3/Cedar local API on port 8773')
    args=parser.parse_args();texts=['عطني بيتزا شاورما.','انتظر شوي لو سمحت.','خلي كبير.']
    provider=V2Provider();audio={}
    try:
        for text in texts:
            path=ROOT/'runtime'/('journey-'+hashlib.sha256(text.encode()).hexdigest()[:20]+'.mp3')
            if not path.exists():path.write_bytes(await provider.speak(text))
            audio[text]=decode(path)
    finally:await provider.aclose()
    base='http://127.0.0.1:8773' if args.local else 'https://sawt-demo.vercel.app'
    password=None if args.local else os.getenv('SAWT_DEMO_PASSWORD') or json.loads((ROOT/'runtime/private-demo.json').read_text())['password']
    report={'browser':'none','scope':'Interrupt verified assistant speech with explicit wait at three offsets; resume; disconnect safely. This is not packet-loss or native-speaker certification.','cases':[]}
    async with httpx.AsyncClient(base_url=base,headers={'Origin':base},timeout=45) as client:
        if not args.local:assert (await client.post('/login',data={'password':password})).status_code==303
        for offset in [.2,.8,1.5]:
            call=VoiceCall(client,{'experience_version':'v3','conversation_mode':'model_led','voice':'cedar'} if args.local else None);row={'offset_after_audio_seconds':offset,'passed':False};report['cases'].append(row)
            try:
                await call.start();row['call_id']=call.call['id']
                initial=await call.state()
                row['worker_release']=next(e['payload'].get('release') for e in initial['events'] if e['kind']=='voice.connected')
                if os.getenv('SAWT_EXPECT_WORKER_RELEASE'):
                    assert row['worker_release']==os.environ['SAWT_EXPECT_WORKER_RELEASE'],'Unexpected worker release'
                async with asyncio.timeout(20):
                    while any(at>time.monotonic()-.8 and rms>.01 for at,rms in call.output):await asyncio.sleep(.1)
                floor=call.cursor
                await send(call,audio[texts[0]]);input_end=time.monotonic()
                async with asyncio.timeout(15):
                    while True:
                        saved=await call.state()
                        completed=[e for e in saved['events'] if e['sequence']>floor and e['kind']=='delegation.completed']
                        if completed:
                            after=max(input_end,time.monotonic()-(time.time()-completed[-1]['at']))
                            heard=[at for at,rms in call.output if at>after and rms>.01]
                            if heard:break
                        await asyncio.sleep(.1)
                first=heard[0]
                await asyncio.sleep(max(0,first+offset-time.monotonic()))
                row['actual_offset_seconds']=round(time.monotonic()-first,2)
                assert any(at>time.monotonic()-.3 and rms>.01 for at,rms in call.output),'Assistant finished before interruption'
                before=await call.state();floor=call.cursor
                await send(call,audio[texts[1]]);wait_input_end=time.monotonic()
                async with asyncio.timeout(15):
                    while True:
                        saved=await call.state()
                        recent=[e for e in saved['events'] if e['sequence']>floor]
                        if any(e['kind']=='call.wait_requested' for e in recent):break
                        if args.local and time.monotonic()-wait_input_end>2 and not any(at>wait_input_end+1 and rms>.01 for at,rms in call.output):break
                        assert not any(e['kind'] in ('delegation.failed','transcript.unverified') for e in recent),'Wait was not understood'
                        await asyncio.sleep(.2)
                row['wait_state_seconds']=round(time.monotonic()-wait_input_end,2)
                await asyncio.sleep(2)
                assert not any(at>wait_input_end+1.5 and rms>.01 for at,rms in call.output),'Speech continued after wait'
                assert saved['state']['basket']==before['state']['basket'] and not saved['state']['order_id']
                row['resumed']=await call.turn(audio[texts[2]],step(texts[2],items={'pizza_flatbread_07':{'size':['large']}}),8)
                # An explicit transport disconnect is terminal for this demo.
                # It must release capacity without placing or replaying an order.
                call.pump_task.cancel();await asyncio.gather(call.pump_task,return_exceptions=True);call.pump_task=None
                if call.pub:await call.room.local_participant.unpublish_track(call.pub.sid);call.pub=None
                if call.source:await call.source.aclose();call.source=None
                await call.room.disconnect()
                async with asyncio.timeout(15):
                    while True:
                        saved=await call.state()
                        if saved['closed']:break
                        await asyncio.sleep(.2)
                assert not saved['state']['order_id']
                row['disconnect_closes_without_order']=True;row['passed']=True
            except Exception as exc:
                row['error']=str(exc) or type(exc).__name__
                if call.call:
                    try:row['failed_state']=await call.state()
                    except Exception:pass
                from sawt.v2_provider import ProviderQuotaError
                if isinstance(exc,ProviderQuotaError):raise
            finally:
                await call.close()
                args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
                print(json.dumps({k:v for k,v in row.items() if k not in ('failed_state','resumed','call_id')}),flush=True)
    assert all(c['passed'] for c in report['cases'])

if __name__=='__main__':asyncio.run(main())
