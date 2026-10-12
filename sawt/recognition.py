"""Bounded copies of the exact PCM sent to GPT-Live, for backend verification.

This does not detect speech turns or control the live microphone. Transcript
timestamps select audio only after the existing delegation/settlement boundary.
"""
import base64
import io
import wave
import re
import math
from .domain import normalize

RATE = 24000
BYTES_PER_MS = RATE * 2 // 1000


class AudioWindowError(ValueError):
    pass


class AudioWindow:
    def __init__(self, seconds=45):
        self.limit = seconds * RATE * 2
        self.data = bytearray()
        self.total = 0

    @property
    def duration_ms(self):
        return self.total / BYTES_PER_MS

    def append(self, encoded):
        pcm = base64.b64decode(encoded, validate=True)
        if len(pcm) % 2:
            raise AudioWindowError('Unaligned PCM')
        self.data.extend(pcm)
        self.total += len(pcm)
        if len(self.data) > self.limit:
            del self.data[:len(self.data)-self.limit]

    def wav(self, spans, *, after_ms=0):
        if not spans or any(type(s.get('start_ms')) not in (int,float) or type(s.get('end_ms')) not in (int,float)
                            or not math.isfinite(s['start_ms']) or not math.isfinite(s['end_ms'])
                            or s['start_ms'] < 0 or s['end_ms'] <= s['start_ms'] for s in spans):
            raise AudioWindowError('Missing transcript timing')
        # GPT-Live timestamps are approximate caption intervals, not word
        # boundaries. Cloud replay showed the opening بكم two seconds before
        # its caption. Retain three seconds of pre-roll, bounded by the last
        # consumed caption's capture position so earlier requests cannot repeat.
        # Provider time can advance across transport stalls while our PCM clock
        # counts only delivered samples. Anchor ahead-of-PCM captions to the
        # capture position observed when each delta arrived, not wall time.
        aligned = []
        for span in spans:
            start, end = span['start_ms'], span['end_ms']
            captured = span.get('captured_ms')
            if isinstance(captured, (int,float)) and math.isfinite(captured) and 0 <= captured <= self.duration_ms and end-captured > 1000:
                offset = end-captured
                start, end = max(0,start-offset), captured
            aligned.append((start,end))
        if not isinstance(after_ms, (int,float)) or not math.isfinite(after_ms) or after_ms < 0:
            raise AudioWindowError('Invalid consumed audio boundary')
        start_ms = max(0, after_ms, min(s[0] for s in aligned)-3000)
        end_ms = max(s[1] for s in aligned)+450
        if end_ms > self.duration_ms + 1000:
            raise AudioWindowError('Transcript ahead of captured audio')
        start = int(start_ms)*BYTES_PER_MS
        end = min(int(end_ms)*BYTES_PER_MS, self.total)
        offset = self.total-len(self.data)
        if start < offset or end <= start:
            raise AudioWindowError('Audio window expired')
        pcm = self.data[start-offset:end-offset]
        if len(pcm) < 4800:
            raise AudioWindowError('Audio window too short')
        out = io.BytesIO()
        with wave.open(out,'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm)
        return out.getvalue(), {'start_ms':start_ms,'end_ms':end/BYTES_PER_MS}


def check_recognition(caption, verified):
    """Do not silently drop a question, a negation or a differing quantity."""
    a,b=normalize(caption),normalize(verified)
    from .conversation import requests_cancel
    if b and requests_cancel(caption) != requests_cancel(verified):
        raise AudioWindowError('Cancellation intent disagreement')
    question=r'^(?:بكم|بيكم|كم|وش سعر|ايش سعر|how much|what is the price)\b'
    if re.search(question,a) and b and not re.search(question,b):
        raise AudioWindowError('Question intent disagreement')
    negatives=r'\b(?:لا|مو|بدون|not|no|without|dont)\b'
    if re.search(negatives,a) and b and not re.search(negatives,b):
        raise AudioWindowError('Negation disagreement')
    numbers={'واحد':'1','واحدة':'1','واحده':'1','وحده':'1','اثنين':'2','اثنتين':'2','ثلاثة':'3','ثلاثه':'3','اربعة':'4','اربعه':'4',
             'خمسة':'5','خمسه':'5','ستة':'6','سته':'6','سبعة':'7','سبعه':'7','ثمانية':'8','ثمانيه':'8','تسعة':'9','تسعه':'9','عشرة':'10','عشره':'10',
             'ثلاث':'3','اربع':'4','خمس':'5','ست':'6','سبع':'7','ثمان':'8','تسع':'9','عشر':'10',
             'one':'1','two':'2','three':'3','four':'4','five':'5','six':'6','seven':'7','eight':'8','nine':'9','ten':'10'}
    def quantities(text):
        return [numbers.get(w,w) for w in text.split() if w in numbers or w.isdigit()]
    qa,qb=quantities(a),quantities(b)
    if qa and b and qa!=qb:
        raise AudioWindowError('Quantity disagreement')


def reconcile_spacing(caption, verified):
    """Restore spaces only when both recognizers returned identical letters.

    Never join/split digits or replace words based on a guessed intent.
    """
    a,b=normalize(caption),normalize(verified)
    if not any(c.isdigit() for c in a+b) and a.replace(' ','')==b.replace(' ',''):
        from .voice_routing import route_transcript
        from .conversation import requests_cancel
        # Prefer an intact verified control over a caption that split a word
        # (e.g. إن تظر). Otherwise preserve caption boundaries, including
        # negations; both recognizers must agree on every letter.
        if route_transcript(verified) in ('wait','end','recover') or requests_cancel(verified):
            return verified
        return caption
    return verified


def reconcile_transcripts(caption, verified):
    verified = reconcile_spacing(caption, verified)
    a, b = normalize(caption), normalize(verified)
    # Conservatively retain a price question when the second recognizer drops
    # ONLY its opening word. This cannot turn the question into an order.
    question = re.fullmatch(r'(?:بكم|بيكم)\s+(.+)', a)
    if question and question.group(1) == b:
        return caption
    return verified
