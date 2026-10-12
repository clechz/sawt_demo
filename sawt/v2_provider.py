"""Per-event-loop connection pool and incremental checkout speech for V2."""
import asyncio
import os
import re
from pathlib import Path
import httpx
from .provider import OpenAIProvider, ProviderError, config

STYLE = 'Read the Arabic text exactly as written, in a clear Saudi accent at a natural pace.'

CALLS_UNAVAILABLE = 'خدمة المكالمات غير متاحة حالياً. حاول لاحقاً.'


class ProviderQuotaError(ProviderError):
    """Billing failure: retrying or asking the caller to repeat cannot fix it."""


def exhausted_quota(error):
    return isinstance(error,dict) and any(error.get(k) in
        ('insufficient_quota','credit_balance_exhausted') for k in ('type','code'))


def voice_name():
    # One V2 identity for live conversation, exact readback and recovery speech.
    return os.getenv('SAWT_VOICE', 'marin')


def spoken_amounts(text):
    """Spell exact monetary values so TTS cannot read 18 as separate digits."""
    from .spoken_numbers import integer_words
    def replace(match):
        whole, fraction = int(match[1]), int(match[2])
        if not fraction:return integer_words(whole)+' ريال'
        fractional={1:'هللة',2:'هللتين',3:'ثلاث هللات',4:'أربع هللات',5:'خمس هللات',
                    6:'ست هللات',7:'سبع هللات',8:'ثمان هللات',9:'تسع هللات',10:'عشر هللات'}.get(fraction,integer_words(fraction)+' هللة')
        return (integer_words(whole)+' ريال و' if whole else '')+fractional
    return re.sub(r'(?<![\d.])(\d+)\.(\d{2}) ريال', replace, text)


class V2Provider(OpenAIProvider):
    def __init__(self, *, batch_tools=True):
        self.supports_tool_batches = batch_tools
        self._client = None
        self._loop = None

    def client(self):
        loop = asyncio.get_running_loop()
        if self._client is not None and self._loop is not loop:
            raise RuntimeError('Close the provider pool before changing event loops')
        if self._client is None:
            self._loop = loop
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(35, connect=10),
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=4, keepalive_expiry=60))
        return self._client

    async def aclose(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = self._loop = None

    @staticmethod
    def headers():
        key = config()['key']
        if not key:
            raise ProviderError('خدمة الصوت تحتاج إعداد المفتاح.')
        return {'Authorization': 'Bearer ' + key}

    @staticmethod
    def check(response):
        if response.status_code >= 400:
            if response.status_code == 429:
                try:
                    if exhausted_quota(response.json().get('error')):
                        raise ProviderQuotaError(CALLS_UNAVAILABLE)
                except (ValueError,AttributeError):
                    pass
            raise ProviderError(f'تعذر الاتصال بمزود الخدمة (HTTP {response.status_code}).')

    async def request(self, path, **kwargs):
        try:
            response = await self.client().post('https://api.openai.com/v1/' + path, headers=self.headers(), **kwargs)
            self.check(response)
            return response
        except httpx.HTTPError as exc:
            raise ProviderError('تعذر الاتصال بالخدمة. حاول مرة ثانية أو اطلب موظفاً.') from exc

    async def chat(self, messages, tools):
        result = await self.request('chat/completions', json={
            'model': config()['llm'], 'messages': messages, 'tools': tools,
            'parallel_tool_calls': self.supports_tool_batches,
            'temperature': .2, 'max_tokens': 1200 if self.supports_tool_batches else 800})
        try:
            return result.json()['choices'][0]['message']
        except (KeyError, ValueError, IndexError, TypeError) as exc:
            raise ProviderError('استجابة النموذج غير صالحة. حاول مرة ثانية.') from exc

    async def speech_chunks(self, text, response_format='mp3'):
        cfg = config()
        if response_format=='pcm':
            from .fixed_voice import fixed_pcm
            cached=fixed_pcm(text,voice_name(),cfg['tts'])
            if cached is not None:
                for offset in range(0,len(cached),4800):yield cached[offset:offset+4800]
                return
        # The provider can send a tiny initial PCM fragment and then stall.
        # Hold only 250 ms of audio before exposing it. A single bounded retry
        # is safe before ANY bytes escape; never splice/restart a partial reply.
        for attempt in range(2 if response_format=='pcm' else 1):
            emitted=False
            try:
                async with asyncio.timeout(3 if response_format=='pcm' else None) as startup:
                    async with self.client().stream('POST', 'https://api.openai.com/v1/audio/speech', headers=self.headers(),
                        timeout=httpx.Timeout(8,connect=5),
                        json={'model': cfg['tts'], 'voice': voice_name(), 'input': spoken_amounts(text),
                              'instructions': STYLE, 'response_format': response_format}) as response:
                        if response.status_code >= 400:await response.aread()
                        self.check(response)
                        chunks=response.aiter_bytes()
                        pending=bytearray()
                        if response_format=='pcm':
                            while len(pending)<12000:
                                chunk=await anext(chunks,b'')
                                if not chunk:break
                                pending.extend(chunk)
                        startup.reschedule(None)
                        if pending:
                            emitted=True
                            yield bytes(pending)
                        async for chunk in chunks:
                            if chunk:
                                emitted=True
                                yield chunk
                return
            except (httpx.HTTPError,TimeoutError) as exc:
                if response_format=='pcm' and not emitted and attempt==0:continue
                raise ProviderError('تعذر تشغيل الملخص. حاول مرة ثانية.') from exc

    async def stream_speech(self, text):
        question='نأكد الطلب؟'
        if not text.rstrip().endswith(question):
            async for chunk in self.speech_chunks(text):yield chunk
            return
        # A full summary occasionally lost its final question in generated TTS.
        # Render its body progressively, then the separately verified reusable
        # question, through ONE encoder (not concatenated MP3 containers).
        from .speech_stream import SpeechEncoder
        encoder=SpeechEncoder()
        body=text.rstrip()[:-len(question)].rstrip()
        async for chunk in self.speech_chunks(body,'pcm'):
            for packet in encoder.feed(chunk):yield packet
        if voice_name()=='marin':
            pcm=(Path(__file__).resolve().parents[1]/'data/voice/confirmation-marin.pcm').read_bytes()
        else:
            pcm=b''.join([chunk async for chunk in self.speech_chunks(question,'pcm')])
        for packet in encoder.feed(pcm):yield packet
        for packet in encoder.finish():yield packet

    async def speak(self, text):
        return b''.join([chunk async for chunk in self.stream_speech(text)])

    async def recognize(self, wav, *, context='', recovery=False):
        # Separate from GPT-Live captions: this bounded check supplies the
        # transactional backend, without a second live turn detector.
        data={
            'model': os.getenv('RECOGNITION_MODEL', 'gpt-transcribe'),
            'languages[]': ['ar', 'en'], 'response_format': 'json',
            'prompt': 'مكالمة عميل لمطعم سعودي. انقل الكلام المسموع فقط دون إضافة كلمات من السياق. كلمات شائعة: استلام، بستلم، خبز صاج، بريوش، خبز بر، بدون حار. '+context[:700],
            'keywords[]': ['الطلب','إلغاء الطلب','استلام','بستلم','صاج','بريوش','خبز بر','شاي عدني','محشوة جبن','شاورما','تميس','معصوب','قلابة','كرك','شكشوكة','النرجس','الملقا','العليا','الروضة'],
        }
        if recovery:
            # A different acoustic model resolves a disagreement, not a vote
            # for the preferred words. Never give it the disputed transcript.
            # This supported legacy model is scheduled for removal 2027-02-26.
            data={'model':os.getenv('RECOGNITION_RECOVERY_MODEL','gpt-4o-transcribe'),
                  'response_format':'json','prompt':'مكالمة طلبات مطعم سعودي. انقل الكلام المسموع فقط. '+context[:700]}
        response = await self.request('audio/transcriptions', data=data,
            files={'file': ('caller-turn.wav',wav,'audio/wav')})
        try:
            text = response.json()['text']
            if not isinstance(text,str):raise ValueError('Invalid transcript')
            return text.strip()
        except (KeyError,TypeError,ValueError) as exc:
            raise ProviderError('تعذر فهم الكلام. ممكن تعيد؟') from exc
