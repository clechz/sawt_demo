"""V3 conversational orchestration, separate from the V2 rollback implementation.

Native GPT-Live delegation starts work; captions are context, not a social
whitelist or a second turn detector. Exact consequential speech still uses the
existing gated PCM/readback path. A prompt is not a semantic audio guarantee:
received-speech and Saudi-listener tests remain mandatory before release.
"""
from __future__ import annotations
import asyncio
import time
import uuid
from .experience import voice_instructions, profile
from .conversation_policy import conversation_mode, release_for
from .release_contract import worker_contract
from .hospitality_runtime import prepare_turn, commit_turn, mark_proposal_presented, verified_utterance
from .recognition import AudioWindowError
from .transactions import Conflict
from .provider import ProviderError
from .v2_provider import ProviderQuotaError, CALLS_UNAVAILABLE
from .voice_routing import route_transcript, continues_wait
from .domain import normalize


def context_chunks(text, max_bytes=460):
    """Conservative byte bound is below the API's 500-token append limit.

    Split at whitespace, never cut a UTF-8 character or silently truncate facts.
    """
    current = ''
    for word in text.split():
        if len(word.encode('utf8')) > max_bytes:
            # Unbroken user strings are reference data, not useful spoken context.
            word = '[long reference omitted; use backend state]'
        candidate = (current + ' ' + word).strip()
        if len(candidate.encode('utf8')) > max_bytes:
            yield current; current = word
        else:
            current = candidate
    if current:
        yield current


def delegated_start(fragments, consumed, pending_transcript):
    """Locate native current-turn text in captured captions without inventing it.

    Older small talk need not be re-transcribed or fall outside the 45s PCM ring.
    If the native hint cannot be aligned, retain the unconsumed request.
    """
    hint = normalize(pending_transcript or '')
    if hint:
        for start in range(len(fragments)-1, consumed-1, -1):
            if normalize(''.join(fragments[start:])) == hint:
                return start
    return consumed


def make_voice_class(base):
    # The factory avoids importing a second copy of voice_worker when its CLI is
    # executed as __main__, and permits deterministic tests with a minimal base.
    class HospitalityVoice(base):
        def __init__(self, sid, room, experience):
            super().__init__(sid, room, voice=experience['voice'], instructions=voice_instructions())
            self.experience = experience
            self.conversation_mode = conversation_mode(experience.get('conversation_mode'))
            self.explicit_playing = False
            self.input_generation = 0
            self.playback_interrupted = False
            self.resume_on_input = False
            self.delegation_start = 0
            self.latest_final_transcript = ''

        async def announce_ready(self):
            from .v2_runtime import tx
            try:
                async with asyncio.timeout(25):
                    await self.provider_ready.wait(); await self.input_ready.wait()
            except TimeoutError:
                await self.close_failed_voice(); return
            if self.provider_failed or self.ending:
                return
            self.duplex_session.append_commentary(profile()['greeting'])
            self.duplex_session.append_thinking('This is an explicitly disclosed restaurant simulation. Use the actual simulated records; do not repeatedly announce the demo limitation.')
            await asyncio.to_thread(tx.event, self.sid, 'voice.connected', {
                'transport': 'livekit', 'model': 'gpt-live-1', 'release': release_for(self.conversation_mode),
                'conversation_mode': self.conversation_mode,
                'voice': self.experience['voice'], 'recognition_policy': 'critical-actions',
                'scenario': self.experience['scenario'], 'worker_contract': worker_contract(self.experience)})
            await self.send('ready', call_id=self.sid, conversation_mode=self.conversation_mode,
                            worker_release=release_for(self.conversation_mode),
                            worker_contract=worker_contract(self.experience))

        def on_provider_event(self, event):
            if event.get('type') == 'session.input_transcript.delta':
                self.input_generation += 1
                if self.explicit_playing:
                    self.playback_interrupted = True
                    # Revokes only this playout permit; the microphone keeps running.
                    self.audio_gate.set_enabled(False)
                elif self.resume_on_input and not self.reading and not self.checkout_context:
                    self.resume_on_input = False
                    self.audio_gate.allow_model(True)
                    self.audio_gate.set_enabled(True, at_boundary=True)
            # Retain ordered durable epoch invalidation and quote interruption
            # guards. Backend preparation is private and can be replanned safely.
            super().on_provider_event(event)

        def on_transcript(self, event):
            if self.ending:
                return
            self.current_item = event.item_id
            if event.is_final:
                self.latest_final_transcript = event.transcript
                self.audit('transcript.user', {'text': event.transcript, 'item_id': event.item_id})
            # Deliberately no route!='social' blanket mute, and no caption-final
            # fallback treating every social phrase as a business request.
            # GPT-Live's delegation_created event starts the backend work.

        def on_delegation(self, delegation):
            # Native delegation carries the current open caption in supported
            # LiveKit releases, not function arguments. Keep unfinished work
            # when a new delegation includes a correction to the same request.
            if not self.pending or self.pending.done():
                hint = getattr(delegation, 'pending_transcript', '') or self.latest_final_transcript
                self.delegation_start = delegated_start(self.fragments, self.consumed, hint)
            super().on_delegation(delegation)

        async def play_message(self, text, *, can_play=None):
            generation = self.input_generation
            self.explicit_playing = True
            self.playback_interrupted = False
            try:
                await super().play_message(text, can_play=can_play)
                return not self.playback_interrupted and self.input_generation == generation
            finally:
                self.explicit_playing = False
                if not self.reading and not self.checkout_context and not self.waiting and not self.ending:
                    # Do not reopen the tail of native speech generated while
                    # the external answer played. Resume on the next input.
                    self.audio_gate.allow_model(False)
                    self.resume_on_input = True
                    if self.input_generation != generation:
                        self.resume_on_input = False
                        self.audio_gate.set_enabled(False)
                        self.audio_gate.allow_model(True)
                        self.audio_gate.set_enabled(True, at_boundary=True)

        async def work(self, delegation_id):
            from .v2_runtime import tx, engine
            started = time.perf_counter()
            bundle_id = delegation_id or 'live-' + uuid.uuid4().hex
            generation = self.input_generation
            row = None
            async def still_current():
                if self.ending or generation != self.input_generation:
                    return False
                current_row = await asyncio.to_thread(tx.load, self.sid)
                return not current_row['closed'] and (row is None or current_row['epoch'] == row['epoch'])
            async def recover(text):
                if await still_current():
                    await self.play_message(text, can_play=still_current)
            try:
                # Bounded retries handle new speech during PRIVATE preparation.
                # Native speech keeps flowing; no actual mutation is replayed.
                for attempt in range(3):
                    # Caption coalescing only, NOT a GPT-Live VAD setting.
                    while time.monotonic() - self.last_input < .25:
                        await asyncio.sleep(.025)
                    if self.input_boundary:
                        await asyncio.shield(self.input_boundary)
                    self.input_invalidated = False
                    end = len(self.fragments)
                    self.pending_end = end
                    generation = self.input_generation
                    start = max(self.consumed, self.delegation_start)
                    text = ''.join(self.fragments[start:end]).strip()
                    if not text:
                        return
                    row = await asyncio.to_thread(tx.load, self.sid)
                    if row['closed']:
                        return
                    replay = await asyncio.to_thread(tx.replay_bundle, self.sid, bundle_id, text)
                    if replay is not None:
                        # Already committed work is never executed again.
                        self.consumed = end
                        return
                    route = route_transcript(text, checkout=self.checkout_context)
                    if self.waiting and continues_wait(text):
                        self.consumed = end
                        return
                    if route == 'wait':
                        await self.wait_requested(end); return
                    if route == 'end':
                        verified = await self.verify_transcript(start, end, text, row['epoch'])
                        if route_transcript(verified) != 'end':
                            raise AudioWindowError('Hangup meaning disagreed')
                        self.consumed = end
                        await self.end_requested(); return
                    if route == 'recover':
                        self.consumed = end
                        self.reading = self.checkout_context = False
                        await self.play_message('معك، أسمعك.'); return
                    self.waiting = False
                    # Captured audio must exist even when no second recognizer runs.
                    after_ms = self.fragment_spans[start-1].get('captured_ms', 0) if start else 0
                    _, window = self.input_audio.wav(self.fragment_spans[start:end], after_ms=after_ms)
                    self.audit('delegation.started', {'delegation_id': bundle_id, 'epoch': row['epoch'], 'recognition_policy': 'critical-actions', 'caption_settlement_ms': round((time.monotonic()-self.last_input)*1000), 'window': window})
                    async def progress(stage):
                        if generation != self.input_generation:
                            raise Conflict('Superseded progress')
                        await self.send('processing', stage=stage, epoch=row['epoch'])
                    try:
                        prepared = await asyncio.wait_for(prepare_turn(engine, self.provider, row, text, progress=progress,
                            conversation_mode=self.conversation_mode), 30)
                    except Conflict:
                        if generation != self.input_generation:
                            continue
                        raise
                    if generation != self.input_generation:
                        self.audit('delegation.replanned', {'reason': 'new_input', 'attempt': attempt + 1})
                        continue
                    acoustic_verified = prepared.requires_verification
                    if prepared.requires_verification:
                        # Independent acoustic verification protects final commitment
                        # and cancellation. Ordinary reads/drafts avoid that wait.
                        verified = await self.verify_transcript(start, end, text, row['epoch'])
                        verified = verified_utterance(text, verified, prepared)
                        if normalize(verified) != normalize(text):
                            # Discard the caption-based staged plan. A checked
                            # transcript authorizes only the plan derived from it.
                            prepared = await asyncio.wait_for(prepare_turn(engine, self.provider, row, verified, progress=progress,
                                conversation_mode=self.conversation_mode), 30)
                            prepared.text = text  # keep the original input replay key
                        self.audit('delegation.acoustic_check', {'verified': True, 'replanned': normalize(verified) != normalize(text)})
                    if generation != self.input_generation:
                        continue
                    result = await commit_turn(tx, self.sid, bundle_id, prepared)
                    self.consumed = end
                    self.audit('delegation.completed', {'delegation_id': bundle_id,
                        'duration_ms': round((time.perf_counter()-started)*1000),
                        'speech_mode': result['speech_mode'], 'recognition_verified': acoustic_verified,
                        'reply': result['reply']})
                    if generation != self.input_generation:
                        # State may have committed just before a correction. Preserve
                        # it, suppress stale speech, and let the next task correct it.
                        for chunk in context_chunks('Saved result; caller may be correcting it. Do not speak the obsolete answer: ' + result['reply']):
                            self.duplex_session.append_thinking(chunk, delegation_id=delegation_id)
                        return
                    quote = prepared.state.get('quote')
                    if result['speech_mode'] == 'checkout' and quote:
                        self.reading = self.checkout_context = self.output_held = True
                        self.audio_gate.allow_model(False); self.audio_gate.set_enabled(False)
                        self.duplex_session.append_instructions('التطبيق يقرأ ملخص الطلب الآن. اسكت أثناء القراءة، وانتظر موافقة العميل أو تصحيحه بعد القراءة.')
                        await self.send('readback', token=quote['token'], revision=quote['revision'])
                        return
                    self.reading = self.checkout_context = self.output_held = False
                    await self.send('updated', epoch=prepared.epoch)
                    if result['speech_mode'] == 'live':
                        self.audio_gate.allow_model(True); self.audio_gate.set_enabled(True)
                        for chunk in context_chunks(result['reply']):
                            self.duplex_session.append_commentary(chunk, delegation_id=delegation_id)
                    else:
                        for chunk in context_chunks('The app will speak this saved result exactly. Do not repeat it: ' + result['reply']):
                            self.duplex_session.append_thinking(chunk, delegation_id=delegation_id)
                        async def current():
                            latest = await asyncio.to_thread(tx.load, self.sid)
                            return not latest['closed'] and latest['epoch'] == prepared.epoch and generation == self.input_generation
                        completed = await self.play_message(result['reply'], can_play=current)
                        self.audit('voice.result_playout', {'completed': completed, 'epoch': prepared.epoch, 'speech_mode': 'exact'})
                        heard = 'The application finished playing this exact reply: ' if completed else 'The application reply was interrupted; do not assume its final words were heard: '
                        for chunk in context_chunks(heard + result['reply']):
                            self.duplex_session.append_thinking(chunk)
                        proposal = prepared.state.get('hospitality', {}).get('pending_resolution')
                        if completed and proposal and not proposal['presented'] and await current():
                            await asyncio.to_thread(mark_proposal_presented, tx, self.sid, proposal['id'], prepared.epoch)
                    return
                if await still_current():
                    self.duplex_session.append_commentary('خذ راحتك، كمل طلبك وأنا معك.', delegation_id=delegation_id)
            except ProviderQuotaError:
                self.provider_failed = True
                await self.close_failed_voice(CALLS_UNAVAILABLE)
            except (asyncio.CancelledError, Conflict):
                self.audit('delegation.superseded', {'delegation_id': delegation_id})
                self.processed = ''
            except AudioWindowError:
                self.audit('transcript.unverified', {'reason': 'unclear_critical_audio'})
                await recover('الجزء الأخير ما وضح لي، تعيده؟')
            except RuleError as exc:
                await recover(str(exc))
            except Exception as exc:
                self.audit('delegation.failed', {'error_type': type(exc).__name__, 'delegation_id': delegation_id})
                await recover('صار تأخير في النظام. خلنا نراجع آخر خطوة.')
    return HospitalityVoice


# Import only errors, not the voice worker's CLI or its server registration.
from .domain import RuleError
