"""Real Cloud/LiveKit/GPT-Live smoke with synthetic caller audio, not human evidence."""
import asyncio
import io
import json
import sys
import os
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import av
import httpx
from livekit import rtc
from sawt.provider import OpenAIProvider, config

ROOT=Path(__file__).resolve().parents[1]

async def main():
    config()
    started=time.monotonic();events=[];frames=0
    async with httpx.AsyncClient(timeout=45) as client:
        response=await client.post('http://127.0.0.1:8766/api/calls',headers={'X-Access-Code':os.getenv('SAWT_ACCESS_CODE','')},json={'recording_consent':True});response.raise_for_status();call=response.json()
        headers={'Authorization':'Bearer '+call['token']}
        room=rtc.Room();tasks=[]
        async def listen(track):
            nonlocal frames
            async for frame in rtc.AudioStream(track):
                frames+=1
        @room.on('track_subscribed')
        def subscribed(track,publication,participant):
            if track.kind==rtc.TrackKind.KIND_AUDIO:tasks.append(asyncio.create_task(listen(track)))
        @room.on('data_received')
        def data(packet):
            if packet.topic=='sawt':events.append({'at_s':round(time.monotonic()-started,2),**json.loads(packet.data)})
        try:
            await room.connect(call['url'],call['room_token'])
            source=rtc.AudioSource(24000,1)
            track=rtc.LocalAudioTrack.create_audio_track('synthetic-caller',source)
            await room.local_participant.publish_track(track,rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
            async with asyncio.timeout(35):
                while not any(e['type']=='ready' for e in events):await asyncio.sleep(.2)
            await asyncio.sleep(7)
            speech=await OpenAIProvider().speak('أبي شكشوكة عدد واحد حجم كبير مع خبز تميس، استلام من فرع النرجس.')
            with av.open(io.BytesIO(speech)) as container:
                resampler=av.AudioResampler(format='s16',layout='mono',rate=24000)
                for decoded in container.decode(audio=0):
                    for pcm in resampler.resample(decoded):
                        await source.capture_frame(rtc.AudioFrame(bytes(pcm.planes[0])[:pcm.samples*2],24000,1,pcm.samples))
            await source.wait_for_playout()
            utterance_end=time.monotonic()
            for _ in range(100):
                await asyncio.sleep(.4)
                state=(await client.get(f"http://127.0.0.1:8766/api/calls/{call['id']}",headers=headers)).json()
                if any(e['kind']=='delegation.completed' for e in state['events']):break
            result={'kind':'synthetic_cloud_voice_smoke','session_id':call['id'],'received_audio_frames':frames,'room_events':events,'seconds_after_input':round(time.monotonic()-utterance_end,2),'state':state['state'],'events':state['events']}
            (ROOT/'evidence/v2/voice-smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps({'frames':frames,'room_events':events,'state':state['state'],'event_kinds':[e['kind'] for e in state['events']]},ensure_ascii=False,indent=2))
        finally:
            await client.post(f"http://127.0.0.1:8766/api/calls/{call['id']}/end",headers=headers)
            await room.disconnect()
            for task in tasks:task.cancel()

asyncio.run(main())
