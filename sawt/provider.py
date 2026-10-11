import os
import csv
from functools import lru_cache
import httpx
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def config():
    load_dotenv(ROOT / '.env', override=True)
    return {'key': os.getenv('OPENAI_API_KEY', '').strip(), 'llm': os.getenv('LLM_MODEL', 'gpt-4.1'),
            'stt': os.getenv('STT_MODEL', 'gpt-4o-transcribe'), 'tts': os.getenv('TTS_MODEL', 'gpt-4o-mini-tts'),
            'voice': os.getenv('TTS_VOICE', 'coral')}

class ProviderError(RuntimeError):
    pass

@lru_cache(maxsize=1)
def transcription_hint():
    with (ROOT / 'data/restaurant-menu-complex.csv').open(encoding='utf-8-sig', newline='') as source:
        rows = list(csv.DictReader(source))
    names = list(dict.fromkeys(row['item_name_ar'] for row in rows))
    options = list(dict.fromkeys(row['option_name_ar'] for row in rows))
    return ('محادثة طلب طعام باللهجة السعودية مع كلمات إنجليزية وأرقام. انسخ ما تسمع فقط؛ هذه مفردات مساعدة وليست نصاً للإضافة: '
            'توصيل، استلام، النرجس، الملقا، العليا، الروضة. خيارات وأصناف: ' + '، '.join(options + names))[:6000]

class OpenAIProvider:
    async def request(self, path, **kwargs):
        cfg = config()
        if not cfg['key']: raise ProviderError('أضف OPENAI_API_KEY في ملف .env ثم أعد المحاولة.')
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(35, connect=10)) as client:
                response = await client.post('https://api.openai.com/v1/' + path, headers={'Authorization': 'Bearer ' + cfg['key']}, **kwargs)
            if response.status_code >= 400:
                # Never return raw provider error bodies, request headers or secrets.
                code = response.status_code
                raise ProviderError(f'تعذر الاتصال بمزود الصوت أو اللغة (HTTP {code}). تحقق من المفتاح والرصيد وصلاحية النموذج.')
            return response
        except httpx.TimeoutException as exc:
            raise ProviderError('انتهت مهلة الاتصال. لم نعتمد أي تغيير جديد. حاول مرة ثانية.') from exc
        except httpx.HTTPError as exc:
            raise ProviderError('تعذر الاتصال بالخدمة. حاول مرة ثانية أو اطلب موظفاً.') from exc

    async def chat(self, messages, tools):
        result = await self.request('chat/completions', json={'model': config()['llm'], 'messages': messages, 'tools': tools,
                                                           'parallel_tool_calls': False, 'temperature': 0.2, 'max_tokens': 800})
        try: return result.json()['choices'][0]['message']
        except (KeyError, ValueError, IndexError, TypeError) as exc: raise ProviderError('استجابة النموذج غير صالحة. حاول مرة ثانية.') from exc

    async def transcribe(self, data, filename):
        result = await self.request('audio/transcriptions', data={'model': config()['stt'], 'language': 'ar', 'response_format': 'json',
            'prompt': transcription_hint()},
            files={'file': (filename, data)})
        try: return result.json()['text'].strip()
        except (KeyError, ValueError, TypeError, AttributeError) as exc: raise ProviderError('تعذر فهم التسجيل.') from exc

    async def speak(self, text):
        cfg = config()
        result = await self.request('audio/speech', json={'model': cfg['tts'], 'voice': cfg['voice'], 'input': text,
            'instructions': 'تحدث بالعربية بوضوح وبنبرة سعودية ودودة. اقرأ الأسعار والكميات بدقة وبهدوء. انطق أرقام الطلب المفصولة بفواصل رقماً رقماً.', 'response_format': 'mp3'})
        return result.content
