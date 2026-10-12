"""Conservative evidence checks for V2 menu selections.

This is deliberately lexical, not a second language model. An unrecognized
paraphrase stays a question; a valid menu ID alone never proves customer intent.
"""
import copy
import re
from .domain import normalize

ALIASES = {
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
    if state['order_id'] or state['handoff']:
        return None
    normalized = normalize(text)
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
    if item['id'] in ('sandwiches_07','sandwiches_08'):
        proteins={'chicken':{'name':'دجاج','name_en':'chicken'},'beef':{'name':'لحم','name_en':'beef'}}
        requested={oid for _,_,oid in matches(utterance,'protein',proteins)}
        expected='chicken' if item['id']=='sandwiches_07' else 'beef'
        if expected not in requested:
            raise RuleError('الشاورما دجاج أو لحم. العميل لم يحدد هذا النوع؛ اسأل أي نوع يقصد ولا تختاره تلقائياً.')
    if item['name'] == 'فول حجازي' and not matches(utterance, 'variant', {'hijazi': {'name':'حجازي','name_en':'Hijazi'}}):
        raise RuleError('الفول له أكثر من نوع: فول حجازي وفول قلابة. لم يحدد العميل الحجازي؛ لا تختاره تلقائياً. اسأل أي نوع يفضّل، واحفظ الأصناف الواضحة الأخرى.')
    if not item['name'].startswith('تميس '):
        return
    flavors = {'cheese': {'name': 'الجبن', 'name_en': 'cheese'}, 'honey': {'name': 'العسل', 'name_en': 'honey'}}
    requested = {oid for _, _, oid in matches(utterance, 'flavor', flavors)}
    expected = 'cheese' if 'جبن' in item['name'] else 'honey' if 'عسل' in item['name'] else None
    if expected not in requested:
        available = '، '.join(x['name'] for x in menu.items.values() if x['name'].startswith('تميس '))
        raise RuleError('لم يحدد العميل هذا النوع من التميس. لا تضفه ولا تستبدله تلقائياً. المتوفر: ' + available + '. اسأل أي نوع يفضّل.')


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
