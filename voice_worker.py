"""LiveKit owns media; GPT-Live owns conversational turn taking.

No competing live turn detector is enabled. Bounded audio transcription verifies
the words sent to the order engine; GPT-Live still owns conversational timing.
"""
import asyncio
import os
import json
import time
import uuid
import logging
import base64
from livekit import rtc
from types import SimpleNamespace
from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, AgentServer, JobContext, cli
from livekit.plugins import openai
from sawt.v2_runtime import ROOT, RUNTIME, tx, delegate, engine
from sawt import cloud_storage
from sawt.v2_provider import V2Provider, voice_name, ProviderQuotaError, exhausted_quota, CALLS_UNAVAILABLE
from sawt.transactions import Conflict
from sawt.recording import CallRecorder, AuditWriter, prune
from sawt.voice_routing import route_transcript, continues_wait
from sawt.recognition import AudioWindow, AudioWindowError, check_recognition, check_transcript_clarity
from sawt.provider import ProviderError
from sawt.conversation import say, farewell
from sawt.audio_gate import SpeechGate


def set_output_enabled(voice, enabled, *, at_boundary=False):
    gate = getattr(voice, "audio_gate", None)
    if gate is not None:
        gate.set_enabled(enabled, at_boundary=at_boundary)
    else:
        voice.session.output.set_audio_enabled(enabled)


load_dotenv(ROOT / '.env')
server = AgentServer(num_idle_processes=1)
PERSONA = '''أنت صوت، مساعد مطعم بالذكاء الاصطناعي. كلامك سعودي واضح بلمسة محلية خفيفة.
تكلم بهدوء وبسرعة طبيعية، جملة أو جملتين. لا تبالغ باللهجة أو الحماس ولا تتنقل بين لهجات.
تجنّب الفصحى الرسمية وكثرة «أبشر» والتكرار. لا تبدأ كل جواب بتحية أو مجاملة.
استخدم كلاماً بسيطاً يناسب العميل، ولا تفرض العبارات المقترحة في كل جواب.
رحب مرة واحدة بالافتتاحية المحددة أدناه. لا تفترض أنه يريد طلباً؛ قد يسأل عن معلومة أو عنده شكوى.
لا تضف إعلاناً عن التسجيل أو جمع البيانات في الترحيب. إذا سألك عن التسجيل جاوبه بصدق: المكالمات تُحفظ للمراجعة وتحسين التجربة.
المطعم تجريبي والطلبات والتحويل لموظف محاكاة. جاوب المجاملات مباشرة.
Backchannel policy
المجاملات رد عليها بود وباختصار، ولا تعيد الترحيب أو سؤال «كيف أساعدك» كل مرة.
في الطلبات انتظر النتيجة بصمت ثم قل الجواب مباشرة، بلا مقدمة. السؤال القصير تقوله مرة واحدة ثم تسكت لتسمع العميل.
لا تضف «دقيقة أتأكد» أو «خلني أراجع» أو «خلني أشوف» لنتيجة جاهزة. إذا وصلك سؤال عن الفرع قل السؤال نفسه مباشرة؛ لا تدّع أن التحقق ما زال جارياً.
لا تقل «تم» أو «ضفت» أو تكرر خيار العميل كأنه محفوظ قبل نتيجة الخلفية.
Interruption policy
اترك العميل يكمل أو يصحح كلامه. خذ التصحيح الأخير ولا تتكلم فوقه.
الصمت والضوضاء ليست سؤالاً. انتظر إذا سكت العميل، ولا تكرر سؤالاً لمجرد أنه لم يجب بعد.
إذا قال «لحظة» أو «اسكت شوي» أو «ما قاعد أتكلم»، توقف وانتظره بصمت. لا تسأله وش يفضّل ولا تفتح موضوعاً جديداً. استأنف عندما يتكلم معك من جديد.
Delegation policy
فوّض كل طلب أو تعديل أو سؤال عن المنيو والأسعار والفروع والحساسية إلى الخلفية.
لا تخمن أي معلومة ولا تعلن نجاح تغيير أو تأكيد قبل نتيجة الخلفية.
الفروع المتاحة ليست بالضرورة الأقرب؛ لا تدّع قرب فرع بدون بيانات المسافة.
إذا صحح العميل كلامه انتظر كلامه الأحدث وفوّضه. لا تعتمد على ملخص قديم.
حتى الردود القصيرة مثل «عادي» و«أسمر» و«تمام» لازم تفوّضها. السلة المحفوظة وحدها مرجعك؛ لا تعلن تسجيل الطلب إلا بعد نتيجة فيها رقم طلب مؤكد. عند نتيجة الخلفية قل المعلومة المعتمدة مرة واحدة ثم انتظر العميل. إذا النتيجة سؤال قصير، اسأل نفس السؤال مباشرة بدون «بس للتأكيد» أو مقدمة. لا تكمل بتأكيد أو معلومة جديدة من عندك.
عند الملخص النهائي التطبيق يشغل قراءة دقيقة منفصلة: اسكت ولا تكررها ولا تطلب التأكيد بنفسك.
لا تقل إن الطلب تم إرساله لمطعم حقيقي. التحويل للموظف تذكرة تجريبية فقط. لا تنه المكالمة لمجرد «شكراً» أو «خلاص». نهاية الطلب ليست نهاية المكالمة.
بعد تأكيد الطلب، لا تسأل عن أصناف جديدة. اتركه يسأل أو ينهي المكالمة.'''
PERSONA += '\nالافتتاحية: ' + say('greeting')


class RestaurantVoice(Agent):
    def __init__(self, sid, room, *, voice=None, instructions=None):
        selected_voice = voice or voice_name()
        super().__init__(instructions=instructions or PERSONA, llm=openai.realtime.GPTLiveModel(delegation='client', voice=selected_voice))
        self.sid, self.room = sid, room
        self.provider = V2Provider(voice=selected_voice)
        self.pending = None
        self.last_input = 0.0
        self.last_output_audio = 0.0
        self.input_invalidated = False
        self.input_boundary = None
        self.latest = ''
        self.fragments = []
        self.fragment_spans = []
        self.input_audio = AudioWindow()
        self.consumed = 0
        self.current_item = None
        self.processed = ''
        self.pending_end = -1
        self.output_held = False
        self.waiting = False
        self.tasks = set()
        self.reading = False
        self.checkout_context = False
        self.last_heard_quote = None
        self.provider_failed = False
        self.ending = False
        self.provider_ready = asyncio.Event()
        self.input_ready = asyncio.Event()
        self.recorder = CallRecorder(RUNTIME / 'recordings', sid)
        self.audit_writer = AuditWriter(tx, sid)

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.task_finished)
        return task

    def task_finished(self, task):
        self.tasks.discard(task)
        if not task.cancelled() and task.exception():
            error=task.exception()
            self.audit('voice.task_failed', {'task':task.get_coro().__qualname__, 'error_type':type(error).__name__})
            logging.getLogger('sawt').error('Voice background task failed',exc_info=(type(error),error,error.__traceback__))
            if isinstance(error,ProviderQuotaError) and not self.provider_failed:
                self.provider_failed=True
                self.audit('voice.provider_unavailable', {'reason':'credit_balance_exhausted'})
                self.spawn(self.close_failed_voice(CALLS_UNAVAILABLE))

    def audit(self, kind, payload):
        try:
            self.audit_writer.append(kind, payload)
        except Exception:
            logging.getLogger('sawt').error('Unable to persist voice audit event: %s', kind)

    async def send(self, kind, **data):
        await self.room.local_participant.publish_data(json.dumps({'type': kind, **data}).encode(), reliable=True, topic='sawt')

    async def on_enter(self):
        self.media_session = self.session
        self.audio_gate = SpeechGate(self.session.output.audio, lambda at: setattr(self, 'last_output_audio', at))
        self.session.output.audio = self.audio_gate
        self.duplex_session.on('delegation_created', self.on_delegation)
        self.duplex_session.on('openai_server_event_received', self.on_provider_event)
        self.duplex_session.on('openai_client_event_queued', self.on_client_event)
        self.session.on('user_input_transcribed', self.on_transcript)
        self.spawn(self.watch_lifetime())
        self.spawn(self.watch_event_loop())
        if self.duplex_session.session_id:
            self.provider_ready.set()
        self.spawn(self.announce_ready())

    async def announce_ready(self):
        # A joined room is not yet a working microphone/provider connection.
        # Do not invite the caller to speak while startup audio is still queued.
        try:
            async with asyncio.timeout(25):
                await self.provider_ready.wait()
                await self.input_ready.wait()
        except TimeoutError:
            self.audit('voice.startup_failed', {'reason':'media_not_ready'})
            await self.close_failed_voice()
            return
        if self.provider_failed or self.ending:
            return
        self.duplex_session.append_commentary(say('greeting'))
        await asyncio.to_thread(tx.event, self.sid, 'voice.connected', {'transport': 'livekit', 'model': 'gpt-live-1', 'recognition_policy':'contextual-draft-v9', 'release':'conversation-v32'})
        await self.send('ready')

    def on_client_event(self, event):
        if event.get('type') == 'session.input_audio.append':
            self.input_ready.set()
            self.input_audio.append(event.get('audio', ''))
            self.recorder.append('caller', event.get('audio', ''))

    def on_provider_event(self, event):
        kind = event.get('type', '')
        if self.provider_failed or getattr(self,'ending',False):
            return
        if kind == 'session.started':
            self.provider_ready.set()
        if kind == 'session.output_audio.delta':
            self.recorder.append('generated-assistant', event.get('delta', ''))
        if kind == 'session.input_transcript.delta':
            self.last_input = time.monotonic()
            self.fragments.append(event.get('delta', ''))
            span = {k:event.get(k) for k in ('start_ms','end_ms')}
            span['captured_ms'] = self.input_audio.duration_ms
            self.fragment_spans.append(span)
            self.audit('transcript.fragment', {**span, 'text':event.get('delta',''), 'captured_ms':self.input_audio.duration_ms})
            # One durable invalidation per unsettled burst. Reset before any
            # verification/transaction work so new speech always supersedes it.
            if not self.input_invalidated:
                self.input_invalidated = True
                previous = getattr(self, 'input_boundary', None)
                self.input_boundary = self.spawn(RestaurantVoice.invalidate_input(self, previous))
            if self.reading:
                self.reading = False
                self.spawn(self.send('readback.cancelled'))
        elif kind in ('session.output_transcript.delta', 'session.usage.updated', 'session.closed', 'error'):
            self.audit(kind, {k: v for k, v in event.items() if k not in ('event_id', 'audio', 'delta')} |
                     ({'text': event.get('delta', '')} if 'transcript' in kind else {}))
            if kind in ('error', 'session.closed'):
                self.provider_failed = True
                if exhausted_quota(event.get('error')):
                    self.audit('voice.provider_unavailable', {'reason':'credit_balance_exhausted'})
                    self.spawn(self.close_failed_voice(CALLS_UNAVAILABLE))
                else:
                    self.spawn(self.close_failed_voice())

    async def invalidate_input(self, previous):
        # Keep durable epochs in caption order while socket I/O keeps flowing.
        if previous:
            await asyncio.shield(previous)
        row = await asyncio.to_thread(tx.load, self.sid)
        quote = row['state']['quote']
        epoch = await asyncio.to_thread(tx.interrupt, self.sid,
            invalidate_quote=bool(quote and not quote['presented']))
        await self.send('input', epoch=epoch)

    async def close_failed_voice(self, message=None):
        if self.pending and not self.pending.done():
            self.pending.cancel()
        await asyncio.to_thread(tx.interrupt, self.sid, close=True)
        try:
            if self.room.isconnected():
                await self.send('error', fatal=True, code='credit_balance_exhausted' if message==CALLS_UNAVAILABLE else 'voice_unavailable', message=message or say('voice_error'))
        finally:
            await self.media_session.aclose()
            await self.room.disconnect()

    def on_transcript(self, event):
        if getattr(self,'ending',False):return
        self.current_item = event.item_id
        route = route_transcript(event.transcript, checkout=self.checkout_context)
        # Suppress speculative order speech while the caller's business turn is
        # unresolved. The microphone and the model's listening remain enabled.
        if route != 'social' and not self.output_held:
            if getattr(self,'audio_gate',None):self.audio_gate.allow_model(False)
            self.output_held = True
            set_output_enabled(self, False)
        if event.is_final:
            self.audit('transcript.user', {'text': event.transcript, 'item_id': event.item_id})
            if route != 'social':
                # SDK is_final only closes a caption segment. Never execute a
                # hangup/pause/order from it before joining and checking audio.
                self.on_delegation(SimpleNamespace(id=None))
            elif route_transcript(''.join(self.fragments[self.consumed:]), checkout=self.checkout_context) != 'social':
                self.on_delegation(SimpleNamespace(id=None))
            else:
                self.consumed = len(self.fragments)
                self.waiting = False
                self.output_held = False
                if getattr(self,'audio_gate',None):self.audio_gate.allow_model(True)
                set_output_enabled(self, True)

    async def verify_transcript(self, start, end, text, epoch):
        await self.send('processing', stage='recognizing', epoch=epoch)
        started = time.perf_counter()
        after_ms = self.fragment_spans[start-1].get('captured_ms', 0) if start else 0
        wav, window = self.input_audio.wav(self.fragment_spans[start:end], after_ms=after_ms)
        from sawt.choices import caption_draft_answer
        row = await asyncio.to_thread(tx.load, self.sid)
        if row['closed'] or row['epoch'] != epoch or end != len(self.fragments):
            raise Conflict('Recognition superseded')
        from sawt.voice_routing import caption_audio_check
        if caption_audio_check(text):
            self.audit('transcript.verified', {'caption':text, 'text':text, **window,
                'source':'nontransactional_audio_check', 'duration_ms':round((time.perf_counter()-started)*1000)})
            return text
        if caption_draft_answer(engine.menu, row['state'], text):
            self.audit('transcript.verified', {'caption':text, 'text':text, **window,
                'source':'contextual_live_caption', 'duration_ms':round((time.perf_counter()-started)*1000)})
            return text
        last_question=next((h['content'] for h in reversed(row['state']['history']) if h['role']=='assistant'),'')
        verified = await asyncio.wait_for(self.provider.recognize(wav,
            context='سؤال الموظف السابق (ليس جزءاً من تسجيل العميل): '+last_question), timeout=8)
        from sawt.recognition import reconcile_transcripts
        verified = reconcile_transcripts(text, verified)
        row = await asyncio.to_thread(tx.load, self.sid)
        if row['closed'] or row['epoch'] != epoch or end != len(self.fragments):
            raise Conflict('Recognition superseded')
        check_transcript_clarity(text, verified)
        self.audit('transcript.verified', {'caption':text, 'text':verified, **window, 'source':'independent_audio',
            'duration_ms':round((time.perf_counter()-started)*1000)})
        try:
            check_recognition(text, verified)
        except AudioWindowError as disagreement:
            self.audit('transcript.disagreement', {'reason':str(disagreement)})
            recovered = await asyncio.wait_for(self.provider.recognize(wav,
                context='سؤال الموظف السابق (ليس جزءاً من تسجيل العميل): '+last_question, recovery=True),timeout=3)
            row = await asyncio.to_thread(tx.load, self.sid)
            if row['closed'] or row['epoch'] != epoch or end != len(self.fragments):
                raise Conflict('Recovery recognition superseded')
            recovered = reconcile_transcripts(text, recovered)
            check_recognition(text, recovered)
            # Recovery must not erase a cancellation, question, negation or
            # explicit conflicting quantity found by the second recognizer.
            # A missing number there can still be recovered from the PCM;
            # contradictory explicit meanings require a caller clarification.
            check_recognition(verified, recovered)
            row = await asyncio.to_thread(tx.load, self.sid)
            if row['closed'] or row['epoch'] != epoch or end != len(self.fragments):
                raise Conflict('Recovery recognition superseded')
            verified = recovered
            self.audit('transcript.verified', {'caption':text,'text':verified,**window,'source':'independent_recovery',
                'duration_ms':round((time.perf_counter()-started)*1000)})
        return verified

    async def clarify_recognition(self, end, epoch):
        row = await asyncio.to_thread(tx.load, self.sid)
        if row['closed'] or row['epoch'] != epoch or end != len(self.fragments):
            raise Conflict('Recognition superseded')
        self.consumed = end
        epoch = await asyncio.to_thread(tx.interrupt, self.sid)
        self.reading = self.checkout_context = self.waiting = self.output_held = False
        set_output_enabled(self, True)
        await self.play_message(say('unclear'))
        await self.send('updated', epoch=epoch)

    async def recover_audio(self, end):
        self.consumed = end
        self.waiting = self.output_held = False
        set_output_enabled(self, True)
        self.audit('call.audio_check', {'source':'verified_caller_request'})
        await self.play_message(say('audio_check'))
        await self.send('updated', epoch=(await asyncio.to_thread(tx.load, self.sid))['epoch'])

    async def wait_requested(self, end=None):
        end = len(self.fragments) if end is None else end
        # A scheduled pause must not swallow speech that arrived after it.
        self.consumed = max(self.consumed, end)
        if end < len(self.fragments):
            return
        if self.pending and self.pending is not asyncio.current_task() and not self.pending.done():
            self.pending.cancel()
        self.waiting = True
        self.pending_end = self.consumed
        self.processed = ''
        self.reading = False
        self.checkout_context = False
        self.output_held = True
        set_output_enabled(self, False)
        epoch = await asyncio.to_thread(tx.interrupt, self.sid)
        self.audit('call.wait_requested', {'source': 'explicit_caller_control'})
        self.duplex_session.append_instructions('العميل طلب الانتظار. انتظر بصمت، ولا تكرر سؤالاً. استأنف عندما يتكلم معك من جديد.')
        await self.send('waiting', epoch=epoch)

    async def end_requested(self):
        if self.ending:return
        self.ending = True
        session = self.session
        if self.pending and self.pending is not asyncio.current_task() and not self.pending.done():
            self.pending.cancel()
        # Supersede pending mutations now, but keep media alive for the closing
        # line. Ending a call neither creates nor cancels a confirmed order.
        await asyncio.to_thread(tx.interrupt, self.sid)
        closing_text = farewell((await asyncio.to_thread(tx.load, self.sid))['state'])
        self.audit('call.end_requested', {'source': 'explicit_caller_command'})
        try:
            await self.send('ending')
            await asyncio.wait_for(self.play_closing(closing_text),timeout=8)
            self.audit('call.goodbye_completed', {'text':closing_text})
        except Exception as exc:
            self.audit('call.goodbye_failed', {'error_type':type(exc).__name__})
        finally:
            await asyncio.to_thread(tx.interrupt, self.sid, close=True)
            try:
                await self.send('ended')
            finally:
                try:
                    await session.aclose()
                finally:
                    await self.room.disconnect()

    async def play_closing(self, text):
        self.duplex_session.append_instructions('التطبيق ينهي المكالمة الآن. لا تتكلم ولا تفوض أي طلب جديد.')
        await self.play_message(text)

    async def play_message(self, text, *, can_play=None):
        # Prime only the first PCM chunk, not a complete MP3. A short recovery
        # used to wait for full synthesis before producing even its first word.
        stream=self.provider.speech_chunks(text,'pcm')
        speech=None
        gate=getattr(self,'audio_gate',None)
        permit=None
        started=time.monotonic()
        self.audit('voice.explicit_playback',{'stage':'requested'})
        try:
            first=await anext(stream,b'')
            if not first:raise ProviderError('Empty recovery speech')
            self.audit('voice.explicit_playback',{'stage':'first_chunk','duration_ms':round((time.monotonic()-started)*1000)})
            if can_play and not await can_play():return
            async def frames():
                from sawt.speech_stream import pcm_frames
                async for data in pcm_frames(first,stream):
                    if gate:
                        if gate.playback_permit is not permit:return
                        gate.bind_playback(permit)
                    self.recorder.append('generated-assistant',base64.b64encode(data).decode())
                    yield rtc.AudioFrame(data,24000,1,len(data)//2)
            await self.session.interrupt(force=True)
            self.audit('voice.explicit_playback',{'stage':'interrupted','duration_ms':round((time.monotonic()-started)*1000)})
            if can_play and not await can_play():return
            if gate:
                gate.allow_model(False)
                permit=gate.begin_playback()
            set_output_enabled(self, True)
            speech = self.session.say(text,audio=frames())
            await speech.wait_for_playout()
            self.audit('voice.explicit_playback',{'stage':'completed','duration_ms':round((time.monotonic()-started)*1000)})
        finally:
            if gate and permit is not None:gate.end_playback(permit)
            if speech is not None and not speech.done():
                speech.interrupt(force=True)
                await asyncio.wait_for(speech.wait_for_playout(),2)
            await stream.aclose()

    async def speak_verified_reply(self, text, end, epoch):
        async def current():
            if self.ending or self.waiting or self.reading or len(self.fragments)!=end:return False
            row=await asyncio.to_thread(tx.load,self.sid)
            return not row['closed'] and row['epoch']==epoch
        if not await current():return
        if getattr(self,'audio_gate',None):self.audio_gate.allow_model(False)
        self.output_held=False
        self.audit('voice.verified_speech',{'source':'exact_backend_text'})
        await self.play_message(text,can_play=current)

    def on_delegation(self, delegation):
        if getattr(self,'ending',False):return
        if getattr(self, 'waiting', False) and len(self.fragments) <= self.consumed:
            return
        # Coalesce repeated requests for the same changing utterance.
        if self.pending and not self.pending.done():
            if self.pending_end == len(self.fragments):
                # A fallback and a model event can describe the same utterance.
                # Keep the existing job instead of paying for it twice.
                if delegation.id:
                    self.duplex_session.append_thinking('The current request is already being checked. Wait for its verified result.', delegation_id=delegation.id)
                return
            self.pending.cancel()
        self.pending_end = len(self.fragments)
        self.pending = self.spawn(self.work(delegation.id))

    async def work(self, delegation_id):
        try:
            while time.monotonic() - self.last_input < .75:
                await asyncio.sleep(.1)
            boundary = getattr(self, 'input_boundary', None)
            if boundary:
                await asyncio.shield(boundary)
            self.input_invalidated = False
            end = len(self.fragments)
            self.pending_end = end
            text = ''.join(self.fragments[self.consumed:end]).strip()
            identity = str(self.current_item) + ':' + text
            if not text or identity == self.processed:
                self.duplex_session.append_thinking('The current request has already been processed. Use the latest verified result.', delegation_id=delegation_id)
                if not self.reading and not self.checkout_context and not self.waiting:
                    self.output_held = False
                    set_output_enabled(self, True)
                return
            self.processed = identity
            row = await asyncio.to_thread(tx.load, self.sid)
            try:
                text = await self.verify_transcript(self.consumed, end, text, row['epoch'])
            except ProviderQuotaError:
                raise
            except (AudioWindowError, ProviderError, TimeoutError) as exc:
                current = await asyncio.to_thread(tx.load, self.sid)
                if current.get('closed') or current['epoch'] != row['epoch'] or end != len(self.fragments):
                    raise Conflict('Recognition clarification superseded')
                self.audit('transcript.unverified', {'error_type':type(exc).__name__,
                    'reason':str(exc) if isinstance(exc,AudioWindowError) else 'recognition_service_unavailable'})
                await self.clarify_recognition(end, row['epoch'])
                return
            if not text:
                # No intelligible speech is not an order or a confirmation.
                self.consumed = end
                if not row['state']['quote']:
                    self.reading = self.checkout_context = False
                self.output_held = self.reading or self.checkout_context or self.waiting
                set_output_enabled(self, not self.output_held)
                self.duplex_session.append_thinking('No intelligible new caller speech was found. Wait silently; do not infer a request.')
                await self.send('waiting' if self.waiting else 'updated', epoch=row['epoch'])
                return
            route = route_transcript(text, checkout=self.checkout_context)
            if getattr(self, 'waiting', False) and continues_wait(text):
                self.consumed = end
                self.output_held = True
                set_output_enabled(self, False)
                self.audit('call.wait_continued', {'source':'verified_polite_suffix'})
                await self.send('waiting', epoch=row['epoch'])
                return
            if route == 'end':
                self.consumed = end
                await self.end_requested()
                return
            if route == 'wait':
                await self.wait_requested()
                return
            if route == 'recover':
                await self.recover_audio(end)
                return
            if route == 'social':
                self.consumed = end
                self.waiting = self.output_held = False
                if getattr(self,'audio_gate',None):self.audio_gate.allow_model(True)
                set_output_enabled(self, True)
                await self.send('updated', epoch=row['epoch'])
                return
            self.waiting = False
            row = await asyncio.to_thread(tx.load, self.sid)
            async def progress(stage, epoch):
                # If the caller has corrected the request, drop old UI updates
                # at the same boundary that guards the durable transaction.
                current = await asyncio.to_thread(tx.load, self.sid)
                if current['closed'] or current['epoch'] != epoch:
                    raise Conflict('Superseded progress')
                self.audit('delegation.progress', {'stage': stage, 'epoch': epoch})
                await self.send('processing', stage='get_state' if stage=='finish_draft' else stage, epoch=epoch)
            result = await delegate(self.sid, text, delegation_id or 'transcript-' + uuid.uuid4().hex, row['epoch'], progress=progress, voice_provider=self.provider)
            if end != len(self.fragments):
                raise Conflict('New caller speech before reply')
            self.consumed = end
            quote = result['state']['quote']
            if quote and not quote['presented']:
                self.reading = True
                self.checkout_context = True
                set_output_enabled(self, False)
                self.output_held = True
                self.duplex_session.append_instructions('التطبيق يشغل الملخص الدقيق الآن. لا تتكلم حتى يعطيك نتيجة طلب العميل التالية.')
                await self.send('readback', token=quote['token'], revision=quote['revision'])
            else:
                self.reading = False
                self.checkout_context = False
                # Injection limit is 500 tokens; a byte bound also works without
                # assuming English tokenization for Arabic text.
                speech = result['reply'].encode('utf-8')[:480].decode('utf-8', errors='ignore')
                verified = 'CONFIRMED order ' + result['state']['order_id'] if result['state']['order_id'] else 'DRAFT ONLY. No order has been placed. Do not say registered, confirmed, or ready for pickup.'
                reply_row = await asyncio.to_thread(tx.load, self.sid)
                if reply_row['closed'] or end != len(self.fragments):
                    raise Conflict('New caller speech before reply injection')
                if getattr(self,'audio_gate',None):self.audio_gate.allow_model(False)
                self.duplex_session.append_thinking(verified+' The application will speak this exact result; do not repeat it: '+speech, delegation_id=delegation_id)
                current = await asyncio.to_thread(tx.load, self.sid)
                output_epoch = current['epoch']
                if current['closed'] or end != len(self.fragments) or output_epoch != reply_row['epoch']:
                    raise Conflict('New caller speech before audible reply')
                self.output_held = False
                await self.send('updated', epoch=output_epoch)
                await self.speak_verified_reply(result['reply'],end,output_epoch)
        except ProviderQuotaError:
            self.provider_failed = True
            self.audit('voice.provider_unavailable', {'reason':'credit_balance_exhausted'})
            await self.close_failed_voice(CALLS_UNAVAILABLE)
        except (asyncio.CancelledError, Conflict):
            self.processed = ''
            self.audit('delegation.superseded', {'delegation_id': delegation_id})
            # Committed tools remain in storage; the next request sees them.
        except Exception as exc:
            self.processed = ''
            self.audit('delegation.failed', {'delegation_id': delegation_id, 'error_type': type(exc).__name__})
            set_output_enabled(self, True)
            self.output_held = False
            self.duplex_session.append_commentary(say('backend_error'), delegation_id=delegation_id)
            await self.send('error', message='تعذر إكمال الخطوة. حاول مرة ثانية أو اطلب موظف.')

    async def watch_lifetime(self):
        # Keep the session object: Agent.session becomes unavailable after a
        # browser disconnect even while this task is awaiting the DB read.
        session = self.session
        deadline = time.monotonic() + 600
        while True:
            await asyncio.sleep(1)
            if self.ending:return
            try:
                row = await asyncio.to_thread(tx.load, self.sid)
            except Exception:
                await self.send('error', message=say('storage_error'))
                await session.aclose()
                await self.room.disconnect()
                return

            quote = row['state']['quote']
            if quote and quote['presented'] and quote['token'] != self.last_heard_quote:
                self.last_heard_quote = quote['token']
                self.reading = False
                self.duplex_session.append_thinking('The application has finished playing the exact checkout summary to the caller. Await their explicit acceptance or correction; delegate even a short yes. Do not repeat the summary.')
            if row['closed'] or time.time() - row['created'] > 600 or time.monotonic() > deadline:
                if not row['closed']:
                    await asyncio.to_thread(tx.interrupt, self.sid, close=True)
                await self.send('ended')
                await session.aclose()
                await self.room.disconnect()
                return

    async def watch_event_loop(self):
        """Measure scheduling stalls separately from model and network latency."""
        worst = 0.0
        ticks = 0
        while True:
            before = time.monotonic()
            await asyncio.sleep(.1)
            worst = max(worst, time.monotonic()-before-.1)
            ticks += 1
            if ticks == 50:
                self.audit('voice.scheduler', {'max_lag_ms':round(worst*1000)})
                worst, ticks = 0.0, 0


@server.rtc_session(agent_name=os.getenv('SAWT_AGENT_NAME','sawt-v2'))
async def entrypoint(ctx: JobContext):
    sid = ctx.job.metadata
    if not sid or (await asyncio.to_thread(tx.load, sid))['closed']:
        ctx.shutdown(reason='Session already closed')
        return
    await asyncio.to_thread(prune, RUNTIME / 'recordings')
    session = AgentSession()
    from sawt.experience import call_experience
    experience = call_experience((await asyncio.to_thread(tx.load, sid))['state'])
    if experience['version'] == 'v3':
        from sawt.hospitality_voice import make_voice_class
        HospitalityVoice = make_voice_class(RestaurantVoice)
        voice = HospitalityVoice(sid, ctx.room, experience)
    else:
        voice = RestaurantVoice(sid, ctx.room, voice=experience['voice'])
    @ctx.room.on('participant_disconnected')
    def disconnected(participant):
        if participant.identity == 'caller-' + sid:
            voice.spawn(asyncio.to_thread(tx.interrupt, sid, close=True))
    async def cleanup():
        for task in list(voice.tasks):
            task.cancel()
        await asyncio.to_thread(tx.interrupt, sid, close=True)
        await asyncio.to_thread(voice.recorder.close)
        await asyncio.to_thread(voice.audit_writer.close)
        try:
            if cloud_storage.enabled():
                for artifact in voice.recorder.path.iterdir():
                    if artifact.suffix in ('.wav','.json'):
                        await asyncio.to_thread(cloud_storage.upload, artifact, sid)
                await asyncio.to_thread(tx.event, sid, 'recording.archived', {'storage':'private_cloud'})
                await asyncio.to_thread(cloud_storage.prune)
        except Exception as exc:
            await asyncio.to_thread(tx.event, sid, 'recording.archive_failed', {'error_type':type(exc).__name__})
            logging.getLogger('sawt').exception('Cloud recording archive failed')
        finally:
            await voice.provider.aclose()
            await asyncio.to_thread(tx.event, sid, 'voice.disconnected', {})
    ctx.add_shutdown_callback(cleanup)
    await ctx.connect()
    await session.start(agent=voice, room=ctx.room)


if __name__ == '__main__':
    cli.run_app(server)
