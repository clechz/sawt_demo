"""Conservative evidence checks for V2 menu selections.

This is deliberately lexical, not a second language model. An unrecognized
paraphrase stays a question; a valid menu ID alone never proves customer intent.
"""
import copy
import re
from .domain import normalize
from .domain import RuleError


class SelectionClarification(RuleError):
    """A missing dish identity takes priority over checkout's missing fields."""
    def __init__(self, message, question, candidates=()):
        super().__init__(message)
        self.question = question
        self.candidates = tuple(candidates)


def service_answer(state, text):
    """Whole, explicit service selections only; never a yes or a mixed request."""
    if state['order_id'] or state['handoff'] or state['quote'] or '?' in text or '؟' in text:
        return None
    labels = {
        'pickup': ['استلام','بستلم','باستلم','أستلم','استلام الفرع','استلام من الفرع','بستلمه','أنا بستلم','pickup'],
        'delivery': ['توصيل','أبي توصيل','أبغى توصيل','delivery'],
    }
    value = normalize(text)
    return next((key for key, words in labels.items() if value in {normalize(w) for w in words}), None)


def caption_draft_answer(menu, state, text):
    """Low-risk closed-set draft answer from the live recognizer.

    Requires an existing question. No confirmation, quantities, free text,
    cancellation, service switch or closed-order edits can bypass verification.
    """
    from .clarification import answer, current
    from .domain import explicit_confirmation
    from .conversation import say
    if state['order_id'] or state['handoff'] or state['quote'] or explicit_confirmation(text):
        return False
    last = next((h['content'] for h in reversed(state['history']) if h['role']=='assistant'), '')
    if not state['service'] and last.endswith(say('service_question')) and service_answer(state,text):
        return True
    pending = current(state)
    return bool(pending and last.endswith(pending['question']) and answer(menu,state,text))


def delivery_answer(state, text):
    """Whole known city/zone answers to our current delivery question only."""
    from .domain import BRANCHES
    from .conversation import say
    if (state['service']!='delivery' or state['location'] or state['order_id']
            or state['handoff'] or state['quote'] or state.get('pending_handoff')
            or '?' in text or '؟' in text):return None
    last=next((h['content'] for h in reversed(state['history']) if h['role']=='assistant'),'')
    details=state.get('delivery_details',{})
    value=normalize(text)
    if not details.get('city') and last.endswith((say('address_question'),'بأي مدينة؟')):
        city=next((b['city'] for b in BRANCHES.values() if normalize(b['city'])==value),None)
        if city:return {'city':city}
    if details.get('city') and not details.get('zone') and last.endswith('بأي حي؟'):
        zone=next((zone for b in BRANCHES.values() if normalize(b['city'])==normalize(details['city'])
            for zone in b['zones'] if value in (normalize(zone),normalize('حي '+zone))),None)
        if zone:return {'zone':zone}
    return None

ALIASES = {
    ('crust', 'stuffed'): ['بحشو بجبن', 'حشو بجبن', 'حشوة جبن', 'محشو بجبن', 'محشوب جبن', 'محشو جبن', 'محشوة بالجبن', 'عجينة الجبن', 'عجين الجبن'],
    ('flavor', 'cheese'): ['جبن', 'جبنة'],
    ('flavor', 'honey'): ['عسل'],
    ('bread', 'brown'): ['خبز بر', 'خبز البر', 'بر', 'اسمر', 'أسمر', 'اسمري', 'أسْمري'],
    ('bread', 'brioche'): ['بريوش', 'بريوشي'],
    ('bread', 'lettuce'): ['خس'],
    ('meal', 'meal'): ['وجبة', 'وجبتين', 'وجبات', 'meal'],
    ('meal', 'sandwich'): ['ساندويتش', 'ساندوتش', 'سندوتش', 'sandwich'],
    ('portion', 'regular'): ['عادي', 'عادية', 'regular'],
    ('portion', 'large'): ['كبير', 'كبيرة', 'large'],
    ('portion', 'double'): ['دبل', 'double'],
    ('sweetness', 'half'): ['نص سكر', 'سكر نص', 'سكر نصف', 'نص السكر', 'نصف السكر', 'half sugar'],
    ('spice_level', 'not_spicy'): ['مو حار', 'غير حار', 'بدون حار', 'not spicy', 'no spice'],
    ('spice_level', 'mild'): ['خفيف', 'حار خفيف', 'mild'],
    ('spice_level', 'medium'): ['حار وسط', 'متوسط', 'medium'],
    ('spice_level', 'hot'): ['حار', 'حارة', 'hot', 'spicy'],
}


def short_choice(menu, state, text):
    """Only a whole option answer with a single unambiguous target is automatic."""
    if state['order_id'] or state['handoff'] or '?' in text or '؟' in text:
        return None
    normalized = normalize(text)
    normalized = re.sub(r'^(?:(?:ايه|ايوه|نعم|طيب|اه|ماشي)\s+)+', '', normalized)
    normalized = re.sub(r'^(?:خل|خلي|خله|خليه|خليها)\s+', '', normalized)
    # ASR often repeats emphasis: "حجم عادي عادي". No negations/alternatives.
    normalized = re.sub(r'^(?:حجم|الحجم)\s+', '', normalized)
    words = normalized.split()
    if words and len(set(words)) == 1:
        normalized = words[0]
    candidates = []
    for line in state['basket']:
        item = menu.get(line['item_id'])
        for gid, group in item['groups'].items():
            if group['max'] != 1:
                continue
            for oid, option in group['options'].items():
                labels = [option['name'], option['name_en']] + ALIASES.get((gid, oid), [])
                if normalized in {normalize(label) for label in labels}:
                    candidates.append((line, gid, oid))
    if len(candidates) > 1:
        # With several dishes, only a sole missing required choice is safe.
        candidates = [(line, gid, oid) for line, gid, oid in candidates
                      if not line['options'].get(gid) and menu.get(line['item_id'])['groups'][gid]['required']]
    if len(candidates) != 1:
        return None
    line, gid, oid = candidates[0]
    return {'line_id': line['line_id'], 'options': {gid: [oid]}}


def check_item_variant(menu, item, utterance):
    """The fixture has no plain standalone tamees; don't silently add a flavor."""
    from .domain import RuleError
    if item['category_id']=='beverages' and re.search(r'(?<!\w)(?:ال)?عدني(?!\w)',normalize(utterance)):
        label=normalize(item['name'])
        explicit=label in normalize(utterance) or (item['id']=='beverages_09' and re.search(r'(?<!\w)كرك(?!\w)',normalize(utterance)))
        if not explicit:
            raise RuleError('الشاي العدني مو موجود في المنيو. لا تستبدله بشاي أحمر أو كرك من نفسك؛ اسأل العميل وش يفضّل.')
    if item['id'] in ('sandwiches_07','sandwiches_08'):
        proteins={'chicken':{'name':'دجاج','name_en':'chicken'},'beef':{'name':'لحم','name_en':'beef'}}
        requested={oid for _,_,oid in matches(utterance,'protein',proteins)}
        expected='chicken' if item['id']=='sandwiches_07' else 'beef'
        if expected not in requested:
            raise SelectionClarification('الشاورما دجاج أو لحم. العميل لم يحدد هذا النوع؛ اسأل أي نوع يقصد ولا تختاره تلقائياً.', 'الشاورما دجاج ولا لحم؟', ('sandwiches_07','sandwiches_08'))
    if item['name'] == 'فول حجازي' and not matches(utterance, 'variant', {'hijazi': {'name':'حجازي','name_en':'Hijazi'}}):
        raise SelectionClarification('الفول له أكثر من نوع: فول حجازي وفول قلابة. لم يحدد العميل الحجازي؛ لا تختاره تلقائياً. اسأل أي نوع يفضّل، واحفظ الأصناف الواضحة الأخرى.', 'الفول حجازي ولا قلابة؟', [x['id'] for x in menu.items.values() if x['name'].startswith('فول ')])
    if not item['name'].startswith('تميس '):
        return
    flavors = {'cheese': {'name': 'الجبن', 'name_en': 'cheese'}, 'honey': {'name': 'العسل', 'name_en': 'honey'}}
    requested = {oid for _, _, oid in matches(utterance, 'flavor', flavors)}
    expected = 'cheese' if 'جبن' in item['name'] else 'honey' if 'عسل' in item['name'] else None
    if expected not in requested:
        available = '، '.join(x['name'] for x in menu.items.values() if x['name'].startswith('تميس '))
        raise SelectionClarification('لم يحدد العميل هذا النوع من التميس. لا تضفه ولا تستبدله تلقائياً. المتوفر: ' + available + '. اسأل أي نوع يفضّل.', 'التميس بالجبن ولا بالعسل؟', [x['id'] for x in menu.items.values() if x['name'].startswith('تميس ')])


def matches(text, group_id, options, *, include_negated=False):
    """Match whole words, keeping 'بدون حار' from also authorizing 'حار'."""
    text = normalize(text)
    found = []
    for oid, option in options.items():
        labels = [option['name'], option.get('name_en', '')] + ALIASES.get((group_id, oid), [])
        for label in set(normalize(x) for x in labels if x):
            # Arabic conjunction/preposition prefixes are allowed; substrings aren't.
            pattern = r'(?<!\w)(?:و|ب|ال)?' + re.escape(label) + r'(?!\w)'
            for match in re.finditer(pattern, text):
                prefix = text[:match.start()].rstrip()
                negated = re.search(r'(?:^|\s)(?:بدون|مو|غير|لا|no|not|without)$', prefix)
                if include_negated or not negated:
                    found.append((match.start(), match.end(), oid))
    return [m for m in found if not any(a <= m[0] and b >= m[1] and b-a > m[1]-m[0] for a,b,_ in found)]


def stated_single_dish_bread(item, utterance, evidence):
    """A complete, narrow one-dish order form; never infer across mixed requests.

    Example: أبي شكشوكة كبير، تميس وتوصيل. The exact named dish has a bread
    group; the sole stated bread belongs to it. Questions, two dishes, notes,
    negations and alternatives do not match and remain with the planner.
    """
    if '?' in utterance or '؟' in utterance or item['name'].startswith('تميس '):return None
    supported={oid for _,_,oid in evidence}
    if len(supported)!=1:return None
    text=normalize(utterance)
    start,end,oid=evidence[0]
    prefix=text[:start].strip();suffix=text[end:].strip()
    dish=re.escape(normalize(item['name']))
    before=rf'(?:ابي|ابغي|عطني|اريد)\s+{dish}(?:\s+(?:(?:حجم|الحجم)\s+)?(?:عادي|كبير|صغير|وسط))?(?:\s+(?:مع|خبز|بخبز))?'
    if re.fullmatch(before,prefix) and re.fullmatch(r'(?:و?\s*(?:توصيل|استلام))?',suffix):return oid
    return None


def simple_order(menu,state,text):
    """Parse only the bounded singular dish/portion/bread form on an empty draft.

    This is an optional fast path, not a general intent parser. Quantity words,
    extra dishes, notes, questions and corrections fall back to the planner.
    """
    if state['basket'] or state['order_id'] or state['handoff'] or state['quote'] or state.get('pending_handoff'):
        return None
    candidates=[]
    for item in menu.items.values():
        groups=item['groups']
        if 'bread' not in groups or 'portion' not in groups:continue
        bread=stated_single_dish_bread(item,text,matches(text,'bread',groups['bread']['options']))
        portions={oid for _,_,oid in matches(text,'portion',groups['portion']['options'])}
        if bread is None or len(portions)!=1:continue
        normalized=normalize(text)
        service='delivery' if normalized.endswith('توصيل') else 'pickup' if normalized.endswith('استلام') else None
        candidates.append({'item_id':item['id'],'quantity':1,'options':{'portion':list(portions),'bread':[bread]},'notes':'','service':service})
    return candidates[0] if len(candidates)==1 else None


def checked_options(menu, item, args, utterance, previous=None):
    args = copy.deepcopy(args)
    selections = menu.canonical_options(item['id'], args.get('options', {}))
    if not isinstance(selections, dict):
        return args, []  # Domain validator reports malformed data.
    previous = previous or {}
    rejected = []
    # Include unavailable breads in recognition so brown can never become brioche.
    bread_catalog = {}
    for candidate in menu.items.values():
        bread_catalog.update(candidate['groups'].get('bread', {}).get('options', {}))
    bread_catalog['pita'] = {'name': 'بيتا', 'name_en': 'pita'}
    bread_catalog['white'] = {'name': 'خبز أبيض', 'name_en': 'white bread'}
    for gid, group in item['groups'].items():
        catalog = bread_catalog if gid == 'bread' else group['options']
        evidence_text = utterance
        if gid == 'bread' and item['name'].startswith('تميس '):
            # The standalone dish name is not a request to change its bread
            # option to 'tamees' when replacing honey with cheese (or back).
            evidence_text = re.sub(r'(?:ال)?تميس\s+(?:ب)?(?:ال)?(?:جبن|عسل)', '', normalize(utterance))
        evidence = matches(evidence_text, gid, catalog)
        mentioned = matches(evidence_text, gid, catalog, include_negated=True)
        supported = {oid for _, _, oid in evidence}
        # Explicit self-correction supersedes earlier bread choices in this turn.
        if gid == 'bread' and evidence and re.search(r'لا لا|معليش|قصدي|اقصد|بدل', normalize(utterance)):
            supported = {max(evidence, key=lambda m: m[0])[2]}
        unavailable = supported - set(group['options'])
        if unavailable and gid == 'bread':
            selections[gid] = []
            rejected.append({'group': gid, 'reason': 'unavailable',
                'question': 'الخبز اللي طلبته مو متوفر لهذا الصنف. المتوفر: ' + '، '.join(o['name'] for o in group['options'].values()) + '. وش تختار؟'})
            continue
        chosen = selections.get(gid)
        if gid=='bread' and chosen is None:
            stated=stated_single_dish_bread(item,utterance,evidence)
            if stated in group['options']:
                selections[gid]=chosen=[stated]
        if not isinstance(chosen, list):
            continue
        # A planner's empty list is not evidence that the caller retracted a
        # required choice. Explicit corrections still invalidate the old value.
        if not chosen and group['required'] and previous.get(gid) and not mentioned:
            selections[gid] = copy.deepcopy(previous[gid])
            continue
        allowed = []
        for oid in chosen:
            # Preserve existing choices during unrelated quantity/notes changes.
            if oid in supported or (not mentioned and oid in previous.get(gid, [])):
                allowed.append(oid)
            else:
                rejected.append({'group': gid, 'reason': 'no_customer_evidence',
                    'question': group['name'] + ': ' + '، '.join(o['name'] for o in group['options'].values()) + '، وش تختار؟'})
        if group['required'] and not mentioned and previous.get(gid) and not allowed:
            allowed = copy.deepcopy(previous[gid])
        selections[gid] = allowed
    args['options'] = selections
    return args, rejected
