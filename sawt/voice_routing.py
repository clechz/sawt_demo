"""Transport-independent routing for the finalized caller transcript."""
from .domain import normalize
import re

# Only complete social phrases bypass the transactional backend. In particular,
# short option answers and a yes must not depend on the voice model delegating.
SOCIAL = {normalize(x) for x in ['هلا', 'يا هلا', 'هلا والله', 'السلام عليكم', 'مرحبا', 'شكرا', 'يعطيك العافية', 'الله يعافيك', 'كيف حالك', 'كيفك']}
END_CALL = {normalize(x) for x in ['انهي المكالمة', 'أنهِ المكالمة', 'انهي المكالمة يلا', 'اقفل المكالمة', 'سكر المكالمة', 'اغلق المكالمة', 'قفل المكالمة', 'مع السلامة', 'شكرا مع السلامة', 'خلاص مع السلامة', 'end the call', 'hang up', 'goodbye']}
WAIT = re.compile(r'(?:(?:يا حبيبي|ياخي|يا اخي|يا اخوي|يا رجال|ترا|تري|انا|ترك)\s+)*(?:ما قاعد اتكلم|مو قاعد اتكلم|ما تكلمت|ساكت|اسكت|اسكت شوي|انتظر|انتظر شوي|خلني اكمل|لحظه|لحظه خلني اكمل)(?:\s+(?:لو سمحت|الله يعافيك))?')
RECOVER = re.compile(r'(?:(?:يا حبيبي|ياخي|يا اخي|يا اخوي|يا رجال|ترا|تري|تراك|انت)\s+)*(?:ما قاعد تتكلم|مو قاعد تتكلم|ما اسمعك|ماني سامعك|صوتك ما يطلع|وين صوتك|الو)(?:\s+(?:هلا|خلاص|لو سمحت))*')

def route_transcript(text, *, checkout=False):
    text = normalize(text)
    # A polite suffix doesn't change an otherwise exact command. In particular
    # both ASR spellings انهِ/انهي normalize to supported command forms.
    command = re.sub(r'\s+(?:يلا|لو سمحت|الله يعافيك)$', '', text)
    if command in END_CALL:
        return 'end'
    # Conversation controls are not restaurant instructions. Require a whole
    # control phrase so negations, quoted notes and mixed orders still delegate.
    if WAIT.fullmatch(text):
        return 'wait'
    if RECOVER.fullmatch(text):
        return 'recover'
    if not text or (text in SOCIAL and not checkout):
        return 'social'
    return 'backend'
