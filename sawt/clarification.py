"""One authoritative choice question; short answers cannot authorize other actions."""
import re
import time
from .domain import normalize, explicit_confirmation, RuleError
from .choices import matches, ALIASES
from .conversation import say, spoken_option, SPICE_QUESTION_LABELS
from .response_style import GROUPS


def question_targets(menu, state, text):
    if '؟' not in text and '?' not in text:
        return []
    normalized = normalize(text)
    result = []
    for line in state['basket']:
        for gid, group in menu.get(line['item_id'])['groups'].items():
            keyword = re.sub(r'^ال', '', normalize(group['name']).split()[-1])
            mentions = [keyword]
            if gid == 'spice_level':
                mentions.extend(['شطه', 'حراره', 'سبايسي'])
            if group['required'] and not line['options'].get(gid) and any(word in normalized for word in mentions):
                result.append((line['line_id'], gid))
    return result


def ask(menu, state, line_id, group_id, option_id=None, utterance=''):
    line = next((x for x in state['basket'] if x['line_id'] == line_id), None)
    if not line:
        raise RuleError('سطر الطلب غير موجود.')
    item = menu.get(line['item_id'])
    group = item['groups'].get(group_id)
    # Presentation policy for the fixture's hot-tea/ice mismatch: propose the
    # catalog's no-ice option explicitly, never silently default or edit CSV.
    if item['id'] == 'beverages_09' and group_id == 'ice' and option_id is None:
        option_id = 'none'
    if not group or (option_id is not None and option_id not in group['options']):
        raise RuleError('خيار التوضيح غير موجود لهذا الصنف.')
    saved = line['options'].get(group_id, [])
    if saved and (option_id is None or saved == [option_id]):
        raise RuleError('هذا الاختيار محفوظ بالفعل: ' + '، '.join(group['options'][x]['name'] for x in saved) + '. لا تسأل عنه مرة ثانية.')
    if option_id is not None:
        option = spoken_option(group_id, option_id, group['options'][option_id]['name'])
        question = say('choice_proposal', item=item['name'], group=group['name'], option=option)
        if item['id'] == 'beverages_09' and group_id == 'ice' and option_id == 'none':
            question = say('karak_ice')
    else:
        if group_id == 'spice_level':
            question = 'كيف تبي درجة الحرارة؟'
        else:
            question = say('choice_question',item=item['name'],group=GROUPS.get(group_id,group['name']),options=' ولا '.join(x['name'] for x in group['options'].values()))
    if len(state['basket'])>1 and not (item['id']=='beverages_09' and group_id=='ice'):
        question = 'بالنسبة لـ' + item['name'] + '، ' + question
    if group_id == 'portion' and 'small' not in group['options'] and re.search(r'(?<!\w)(?:صغير|small)(?!\w)', normalize(utterance)):
        question = say('small_unavailable') + ' ' + question
    state['pending_choice'] = {'line_id': line_id, 'item_id': item['id'], 'group_id': group_id,
                               'option_id': option_id, 'revision': state['revision'],
                               'created': time.time(), 'question': question}
    return {'terminal': True, 'reply': question}


def current(state):
    pending = state.get('pending_choice')
    if (not pending or state['order_id'] or state['handoff'] or state['quote']
            or pending['revision'] != state['revision'] or time.time()-pending['created'] > 300):
        return None
    line = next((x for x in state['basket'] if x['line_id'] == pending['line_id'] and x['item_id'] == pending['item_id']), None)
    return pending if line else None


def answer(menu, state, text):
    """Accept an entire option answer, or yes to our exact single-option offer.

    Returns canonical evidence for the guard, not a general confirmation bypass.
    Compounds, questions, changes to other fields and negations go to the planner.
    """
    if '?' in text or '؟' in text:
        return None
    pending = current(state)
    if not pending:
        return None
    gid = pending['group_id']
    group = menu.get(pending['item_id'])['groups'][gid]
    normalized = normalize(text)
    chosen = pending['option_id'] if explicit_confirmation(text) else None
    if not chosen:
        if '?' in text or '؟' in text:
            return None
        # Strip only conversational padding, not negations or ordering commands.
        normalized = re.sub(r'^(?:(?:ايه|ايوه|نعم|طيب|اه|ماشي)\s+)+', '', normalized)
        normalized = re.sub(r'\s+(?:(?:ايه|ايوه|نعم|خلاص|كمل|قلتلك|يابوي)\s*)+$', '', normalized)
        normalized = re.sub(r'^(?:خل|خلي|خله|خليه|خليها)\s+', '', normalized)
        if normalized == 'بدون' and 'none' in group['options']:
            chosen = 'none'
        if not chosen and gid == 'spice_level':
            # A short answer is safe only while answering the current spice question.
            short = {'بدون': 'not_spicy', 'خفيفه': 'mild', 'خفيف': 'mild',
                     'وسط': 'medium', 'قويه': 'hot'}
            candidate = short.get(normalized)
            if candidate in group['options']:
                chosen = candidate
        if not chosen:
            for oid, option in group['options'].items():
                labels = [option['name'], option['name_en']] + ALIASES.get((gid, oid), [])
                if normalized in {normalize(x) for x in labels}:
                    chosen = oid
    if not chosen:
        return None
    return ({'line_id': pending['line_id'], 'options': {gid: [chosen]}}, spoken_option(gid, chosen, group['options'][chosen]['name']))


def next_question(menu, state):
    """Ask one remaining required choice, never a choice already persisted."""
    for line in state['basket']:
        item = menu.get(line['item_id'])
        if state['branch'] and state['branch'] not in item['available']:
            state['pending_choice'] = None
            return say('unavailable_item',item=item['name'])
    for line in state['basket']:
        item = menu.get(line['item_id'])
        for gid, group in item['groups'].items():
            if len(line['options'].get(gid, [])) < group['min']:
                return ask(menu, state, line['line_id'], gid)['reply']
    state['pending_choice'] = None
    if not state['service']:
        return say('service_question')
    if state['service'] == 'delivery' and not state['location']:
        details=state.get('delivery_details',{})
        if not details.get('city') and not details.get('zone'):return say('address_question')
        if not details.get('city'):return 'بأي مدينة؟'
        if not details.get('zone'):return 'بأي حي؟'
        if not details.get('street') and not details.get('building'):return 'واسم الشارع ورقم المبنى؟'
        if not details.get('street'):return 'وش اسم الشارع؟'
        if not details.get('building'):return 'ورقم المبنى؟'
        return 'العنوان خارج نطاق التوصيل. تبيه استلام؟'
    if not state['branch']:
        return say('branch_question')
    return None
