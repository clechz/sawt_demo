"""Generate controlled TTS voice samples. Does not change the live voice configuration."""
import asyncio
import io
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import av
from sawt.provider import OpenAIProvider

OUTPUT = Path(__file__).resolve().parents[2] / 'voice-comparison'
TEXT = 'يا هلا، حاضرين لك. عندي لك وجبة شاورما لحم، حار، بخبز صاج. الإجمالي ثمانية وأربعين ريال. تبي تعدل شي، ولا نعتمد الطلب؟'
STYLE = '''تحدث بعربية سعودية واضحة وطبيعية، بلمسة محلية خفيفة يفهمها أهل السعودية عموماً.
نبرة هادئة وودودة مثل موظف مطعم متعاون، من دون مبالغة أو أداء إعلاني.
حافظ على اللهجة طوال المقطع. سرعة متوسطة، مخارج حروف واضحة، ووقفات قصيرة بين الجمل.
اقرأ النص كما هو. انطق أسماء الأكلات والمبلغ بوضوح. لا تضف أي كلمات.'''


async def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {'model':'gpt-4o-mini-tts', 'text':TEXT, 'instructions':STYLE,
              'scope':'Controlled checkout TTS samples, not GPT-Live conversation or an accent benchmark.', 'samples':[]}
    provider = OpenAIProvider()
    for label, voice in [('A','coral'),('B','marin'),('C','cedar')]:
        started=time.perf_counter()
        response=await provider.request('audio/speech',json={'model':report['model'],'voice':voice,
            'input':TEXT,'instructions':STYLE,'response_format':'mp3'})
        data=response.content
        with av.open(io.BytesIO(data)) as media:
            duration=sum(frame.samples/frame.sample_rate for frame in media.decode(audio=0))
        path=OUTPUT/f'sample-{label}.mp3'
        path.write_bytes(data)
        report['samples'].append({'label':label,'voice':voice,'file':path.name,'duration_seconds':duration,
                                  'generation_ms':round((time.perf_counter()-started)*1000)})
        print(f'Sample {label}: {duration:.1f}s audio generated')
    (OUTPUT/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':
    asyncio.run(main())
