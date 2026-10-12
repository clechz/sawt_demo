"""Per-event-loop connection pool and incremental checkout speech for V2."""
import asyncio
import os
import httpx
from .provider import OpenAIProvider, ProviderError, config

STYLE = ('Speak clear, broadly Saudi Arabic with a light regional accent. Warm, calm restaurant employee; '
         'natural medium pace, no exaggerated dialect or theatrical enthusiasm. Short pauses between items. '
         'Read exactly the provided Arabic; preserve every quantity, option, amount and confirmation question. '
         'Say ريال naturally. Do not add words, filler, greetings or music.')


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

    async def stream_speech(self, text):
        cfg = config()
        try:
            async with self.client().stream('POST', 'https://api.openai.com/v1/audio/speech', headers=self.headers(),
                json={'model': cfg['tts'], 'voice': cfg['voice'], 'input': text,
                      'instructions': STYLE, 'response_format': 'mp3'}) as response:
                self.check(response)
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            raise ProviderError('تعذر تشغيل الملخص. حاول مرة ثانية.') from exc

    async def speak(self, text):
        return b''.join([chunk async for chunk in self.stream_speech(text)])

    async def recognize(self, wav):
        # Separate from GPT-Live captions: this bounded check supplies the
        # transactional backend, without a second live turn detector.
        response = await self.request('audio/transcriptions', data={
            'model': os.getenv('RECOGNITION_MODEL', 'gpt-transcribe'),
            'languages[]': ['ar', 'en'], 'response_format': 'json',
            'prompt': 'مكالمة عميل لمطعم سعودي: يسأل عن الأسعار، يختار الحجم والعجينة، يعدل أو يلغي الطلب. انقل كلامه كما سمعته دون تخمين أصناف أو طلبات.',
            'keywords[]': ['الطلب','إلغاء الطلب','شاي عدني','محشوة جبن','شاورما','تميس','معصوب','قلابة','كرك','شكشوكة','النرجس','الملقا','العليا','الروضة'],
        }, files={'file': ('caller-turn.wav',wav,'audio/wav')})
        try:
            text = response.json()['text']
            if not isinstance(text,str):raise ValueError('Invalid transcript')
            return text.strip()
        except (KeyError,TypeError,ValueError) as exc:
            raise ProviderError('تعذر فهم الكلام. ممكن تعيد؟') from exc
