"""Short acknowledgments derived from saved changes, not model claims."""
from .domain import BRANCHES, normalize

GROUPS = {'portion': 'الحجم', 'size': 'الحجم', 'bread': 'الخبز',
          'sweetness': 'السكر', 'ice': 'الثلج', 'spice_level': 'الحار', 'sauce': 'الصوص'}
NUMBERS = {1: 'واحد', 2: 'اثنين', 3: 'ثلاثة', 4: 'أربعة', 5: 'خمسة'}


def changes(menu, before, after):
    old = {x['line_id']: x for x in before['basket']}
    new = {x['line_id']: x for x in after['basket']}
    parts = []
    for key, line in old.items():
        if key not in new:
            parts.append('شلت ' + menu.get(line['item_id'])['name'])
    for key, line in new.items():
        item = menu.get(line['item_id'])
        prior = old.get(key)
        if prior is None:
            parts.append('ضفت لك ' + item['name'] if line['quantity']==1 else
                         f"ضفت {NUMBERS.get(line['quantity'],line['quantity'])} من {item['name']}")
            continue
        prefix = 'بالنسبة لـ' + item['name'] + '، ' if len(new) > 1 else ''
        if prior['item_id'] != line['item_id']:
            parts.append('بدلت ' + menu.get(prior['item_id'])['name'] + ' بـ' + item['name'])
        if prior['quantity'] != line['quantity']:
            parts.append(prefix + 'خليت الكمية ' + str(NUMBERS.get(line['quantity'], line['quantity'])))
        for gid, group in item['groups'].items():
            selected = line['options'].get(gid, [])
            if selected != prior['options'].get(gid, []):
                label = GROUPS.get(gid, group['name'])
                value = '، '.join(group['options'][v]['name'] for v in selected)
                if gid in ('ice', 'sweetness') and selected:
                    phrase = 'خليته ' + value.replace('نصف سكر','نص سكر')
                else:
                    phrase = 'خليت ' + label + ' ' + value if selected else 'شلت ' + label
                parts.append(prefix + phrase)
        if prior.get('notes') != line.get('notes'):
            parts.append(prefix + ('الملاحظة: ' + line['notes'] if line.get('notes') else 'شلت الملاحظة'))
    if before['service'] and before['service'] != after['service']:
        parts.append('خليته استلام' if after['service'] == 'pickup' else 'خليته توصيل')
    if after['service'] == 'pickup' and after['branch'] and before['branch'] != after['branch']:
        parts.append('الاستلام من ' + BRANCHES[after['branch']]['name'])
    if after['location'] and before['location'] != after['location']:
        loc = after['location']
        parts.append(f"التوصيل إلى {loc['city']}، حي {loc['zone']}، {loc['address']}")
    return '. '.join(parts) + ('.' if parts else '')


def combine(acknowledgment, question):
    if acknowledgment.startswith('بالنسبة لـ'):
        prefix = acknowledgment.split('، ', 1)[0] + '، '
        if question.startswith(prefix):
            question = question[len(prefix):]
    return acknowledgment + ' ' + question


def finished_order(text):
    if '?' in text or '؟' in text:
        return False
    # Whole requests only; mixed/negated requests stay with the planner.
    return normalize(text) in {normalize(x) for x in (
        'هذا كل الطلب', 'هذا طلبي', 'بس كذا', 'خلاص', 'اقرأ الطلب',
        'اقرأ الملخص', 'اقرأ ملخص الطلب', 'اقرأ لي ملخص الطلب من جديد',
        'خلاص هذا الطلب', 'كذا خلصت')}
