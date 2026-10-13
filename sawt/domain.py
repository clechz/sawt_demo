"""Authoritative menu, validation and order state. No model or network dependency."""
from __future__ import annotations

import copy
import csv
import re
import uuid
from decimal import Decimal
from pathlib import Path
from .conversation import say, spoken_order_number, requests_cancel, spoken_option

BRANCHES = {
    'ruh_olaya': {'name': 'فرع العليا بالرياض', 'city': 'الرياض', 'zones': ['العليا', 'السليمانية'], 'fee': 1200, 'eta': 35},
    'ruh_narjis': {'name': 'فرع النرجس بالرياض', 'city': 'الرياض', 'zones': ['النرجس', 'الياسمين'], 'fee': 1500, 'eta': 40},
    'ruh_malqa': {'name': 'فرع الملقا بالرياض', 'city': 'الرياض', 'zones': ['الملقا', 'حطين'], 'fee': 1000, 'eta': 30},
    'jed_rawdah': {'name': 'فرع الروضة بجدة', 'city': 'جدة', 'zones': ['الروضة', 'السلامة'], 'fee': 1400, 'eta': 40},
}

def normalize(value: str) -> str:
    value = str(value).lower().translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹أإآٱىة', '01234567890123456789اااايه'))
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', re.sub(r'[\u064b-\u065f\u0670ـ]', '', value))).strip()

def halalas(value):
    return int(Decimal(str(value)) * 100)

def money(value):
    return f'{value / 100:.2f}'

class RuleError(ValueError):
    pass

class Menu:
    def __init__(self, path: Path):
        self.items = {}
        self.row_count = 0
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            self.columns = reader.fieldnames
            for row in reader:
                self.row_count += 1
                item = self.items.setdefault(row['item_id'], {
                    'id': row['item_id'], 'name': row['item_name_ar'], 'name_en': row['item_name_en'],
                    'category': row['category_ar'], 'category_id': row['category_id'],
                    'base': halalas(row['base_price_sar']),
                    'available': [b for b in BRANCHES if row['available_' + b].lower() == 'true'], 'groups': {},
                })
                group = item['groups'].setdefault(row['option_group_id'], {
                    'name': row['option_group_name_ar'], 'required': row['option_group_required'] == 'true',
                    'min': int(row['option_group_min_select']), 'max': int(row['option_group_max_select']), 'options': {},
                })
                group['options'][row['option_id']] = {'name': row['option_name_ar'], 'name_en': row['option_name_en'], 'delta': halalas(row['option_price_delta_sar'])}

        # Product correction: plain laban is unsweetened, not a customizable
        # sugary drink. Preserve the source CSV and apply this explicit override
        # consistently to retrieval, validation and missing-choice calculation.
        laban = self.items.get('beverages_03')
        if laban and 'sweetness' in laban['groups']:
            sweetness = laban['groups']['sweetness']
            sweetness.update(required=False, min=0,
                             options={'none': sweetness['options']['none']})

    def get(self, item_id):
        if item_id not in self.items:
            raise RuleError('الصنف غير موجود. ابحث في القائمة أولاً.')
        return copy.deepcopy(self.items[item_id])

    def search(self, query, branch=None, limit=5, offset=0):
        # Saudi category words should reach the same catalog, not look absent.
        query_text = normalize(query).replace('sweet tooth', 'desserts')
        aliases = {'حلا':'حلويات', 'حلي':'حلويات', 'حلو':'حلويات',
                   'ساندوتش':'sandwiches', 'سندوتش':'sandwiches'}
        words = [aliases.get(word, word) for word in query_text.split()]
        ranked = []
        for item in self.items.values():
            text = normalize(' '.join([item['name'], item['name_en'], item['category'], item['category_id']]))
            score = sum(1 for word in words if word in text)
            if not words or score:
                ranked.append((score, item))
        ranked.sort(key=lambda x: (-x[0], x[1]['id']))
        return {'total_matches': len(ranked),
                'partial_matches_only': bool(words) and not any(score == len(words) for score, _ in ranked),
                'items': [dict(copy.deepcopy(i), available_here=branch in i['available'] if branch else None) for _, i in ranked[offset:offset + min(limit, 5)]]}

    def categories(self):
        categories = {}
        for item in self.items.values():
            category = categories.setdefault(item['category_id'], {'id': item['category_id'], 'name': item['category'], 'count': 0})
            category['count'] += 1
        return {'categories': list(categories.values())}

    def compatible_options(self, previous, item_id):
        """Carry only identical choices into a replacement, never map by guesswork."""
        old, new = self.get(previous['item_id']), self.get(item_id)
        carried = {}
        for gid, selected in previous['options'].items():
            group = new['groups'].get(gid)
            if not group:
                continue
            options = [oid for oid in selected if oid in group['options']
                       and old['groups'][gid]['options'][oid]['name'] == group['options'][oid]['name']]
            if len(options) <= group['max']:
                carried[gid] = options
        return carried

    def validate_line(self, line, branch=None):
        item = self.get(line['item_id'])
        quantity = line['quantity']
        if type(quantity) is not int or not 1 <= quantity <= 20:
            raise RuleError('الكمية لازم تكون عدداً صحيحاً من ١ إلى ٢٠.')
        selections = line['options']
        if not isinstance(selections, dict) or set(selections) - set(item['groups']):
            raise RuleError('مجموعة خيارات غير صالحة لهذا الصنف.')
        missing, option_names, delta = [], [], 0
        for gid, group in item['groups'].items():
            chosen = selections.get(gid, [])
            if not isinstance(chosen, list) or any(not isinstance(x, str) for x in chosen):
                raise RuleError('صيغة الخيارات غير صالحة.')
            if len(chosen) != len(set(chosen)) or len(chosen) > group['max']:
                raise RuleError('عدد الخيارات أو تكرارها غير مسموح.')
            if len(chosen) < group['min']:
                missing.append(group['name'])
            for oid in chosen:
                if oid not in group['options']:
                    raise RuleError('الخيار غير موجود لهذا الصنف.')
                option = group['options'][oid]
                if not (line['item_id'] == 'beverages_03' and gid == 'sweetness'):
                    option_names.append(option['name'])
                delta += option['delta']
        if not isinstance(line['notes'], str) or len(line['notes']) > 300:
            raise RuleError('الملاحظات طويلة جداً.')
        return dict(line, name=item['name'], option_names=option_names, unit_price=item['base'] + delta,
                    line_total=(item['base'] + delta) * quantity, missing=missing,
                    available=branch in item['available'] if branch else None)

    def canonical_options(self, item_id, selections):
        """Resolve known labels/size aliases only; never guess or fill a choice."""
        item = self.get(item_id)
        if not isinstance(selections, dict): return selections
        result = copy.deepcopy(selections)
        if item_id == 'beverages_03' and not result.get('sweetness'):
            result['sweetness'] = ['none']
        size_aliases = {'large meal': 'large', 'regular meal': 'regular', 'family meal': 'family',
                        'وجبه كبيره': 'large', 'وجبه عاديه': 'regular', 'وجبه عائليه': 'family'}
        for gid, chosen in result.items():
            if gid not in item['groups'] or not isinstance(chosen, list): continue
            options = item['groups'][gid]['options']
            for index, value in enumerate(chosen):
                if not isinstance(value, str) or value in options: continue
                label = normalize(value.replace('_', ' '))
                matches = [oid for oid, opt in options.items() if label in [normalize(opt['name']), normalize(opt['name_en'])]]
                if gid == 'portion' and size_aliases.get(label) in options: matches.append(size_aliases[label])
                if len(set(matches)) == 1: chosen[index] = matches[0]
        return result

def new_state():
    return {'revision': 0, 'service': None, 'location': None, 'branch': None, 'basket': [],
            'quote': None, 'order_id': None, 'handoff': None, 'history': [], 'events': [], 'offer': 'not_offered', 'pending_choice': None, 'pending_handoff': None, 'delivery_details': {}}

class Engine:
    def __init__(self, menu):
        self.menu = menu

    def touch(self, state):
        state['revision'] += 1
        state['quote'] = None
        state['pending_choice'] = None
        state['pending_handoff'] = None

    def view(self, state):
        branch = BRANCHES.get(state['branch'])
        lines = [self.menu.validate_line(line, state['branch']) for line in state['basket']]
        fee = branch['fee'] if branch and state['service'] == 'delivery' and state['location'] else 0
        issues = []
        if not state['service']: issues.append('حدد توصيل أو استلام.')
        if not branch: issues.append('حدد الفرع أو منطقة التوصيل.')
        if state['service'] == 'delivery' and not state['location']: issues.append('نحتاج عنوان التوصيل والمنطقة.')
        if not lines: issues.append('السلة فارغة.')
        for line in lines:
            if line['available'] is False: issues.append(f"{line['name']} غير متوفر في الفرع المختار.")
            if line['missing']: issues.append(f"{line['name']}: اختر " + '، '.join(line['missing']))
        status = 'handoff' if state['handoff'] else 'completed' if state['order_id'] else 'collecting' if issues else 'awaiting_confirmation' if state['quote'] else 'ready_for_readback'
        return {'revision': state['revision'], 'status': status, 'service': state['service'], 'location': state['location'],
                'branch_id': state['branch'], 'branch': branch, 'basket': lines, 'subtotal': sum(x['line_total'] for x in lines),
                'delivery_fee': fee, 'total': sum(x['line_total'] for x in lines) + fee,
                'eta_minutes': branch['eta'] if branch and state['service'] == 'delivery' else 20 if branch else None,
                'issues': issues, 'quote': state['quote'], 'order_id': state['order_id'], 'handoff': state['handoff'],
                'pending_choice': copy.deepcopy(state.get('pending_choice')), 'pending_handoff': copy.deepcopy(state.get('pending_handoff')), 'delivery_details': copy.deepcopy(state.get('delivery_details',{}))}

    def summary(self, state):
        view = self.view(state)
        lines = []
        for x in view['basket']:
            notes = f"، ملاحظات: {x['notes']}" if x['notes'] else ''
            item = self.menu.get(x['item_id'])
            # Speak natural option names; keep catalog data and validated totals intact.
            spoken_names = [spoken_option(gid, oid, group['options'][oid]['name'])
                            for gid, group in item['groups'].items()
                            if not (x['item_id'] == 'beverages_03' and gid == 'sweetness')
                            for oid in x['options'].get(gid, [])]
            lines.append(f"{x['quantity']} من {x['name']}، " + '، '.join(spoken_names) + notes + f"، بسعر {money(x['line_total'])} ريال")
        fulfillment = ('التوصيل إلى ' + state['location']['city'] + '، حي ' + state['location']['zone'] + '، ' + state['location']['address'] + ' من ' if state['service']=='delivery' else 'استلام من ') + view['branch']['name'] + '.'
        fee_sentence = f"رسوم التوصيل {money(view['delivery_fee'])} ريال. " if state['service']=='delivery' else ''
        return say('summary',items='؛ '.join(lines),fulfillment=fulfillment,fee_sentence=fee_sentence,total=money(view['total']),eta=view['eta_minutes'])

    def act(self, state, action, args, *, utterance='', can_confirm=False):
        if action == 'search_menu': return self.menu.search(args.get('query', ''), state['branch'], offset=max(0, int(args.get('offset', 0))))
        if action == 'list_categories': return self.menu.categories()
        if action == 'get_item': return self.menu.get(args['item_id'])
        if action == 'get_state': return self.view(state)
        if action == 'list_branches': return BRANCHES
        if action == 'handoff':
            offered = bool(state.get('pending_handoff'))
            state['handoff'] = state['handoff'] or {'ticket': 'H-' + uuid.uuid4().hex[:8].upper(), 'reason': str(args.get('reason', 'طلب موظف'))[:300]}
            state['quote'] = None
            state['pending_handoff'] = state['pending_choice'] = None
            return {'terminal': True, 'reply': 'تمام، سجلت لك طلب تواصل.' if offered else say('handoff'), 'handoff': state['handoff']}
        if state['handoff']: raise RuleError('المحادثة محولة لموظف. ابدأ محادثة جديدة للطلب.')
        if action == 'offer_handoff':
            topic=args.get('topic','other')
            if topic not in ('other','hours','allergens','tracking','payments','scheduling'):raise RuleError('نوع المعلومة غير معروف.')
            state['quote'] = state['pending_choice'] = None
            state['pending_handoff'] = {'revision':state['revision'],'reason':str(args['reason'])[:300]}
            return {'terminal':True,'reply':say('missing_'+topic) + ' ' + say('offer_handoff')}
        if action == 'confirm' and state['order_id']:
            return {'terminal': True, 'reply': say('already_confirmed',order_number=spoken_order_number(state['order_id'])), 'order_id': state['order_id']}
        if state['order_id']: raise RuleError(say('confirmed_change'))
        if action == 'cancel_draft':
            if not requests_cancel(utterance):raise RuleError('إلغاء المسودة يحتاج طلباً صريحاً بإلغاء الطلب كله.')
            had_draft = bool(state['basket'] or state['service'] or state['location'] or state['branch'])
            state.update(basket=[],service=None,location=None,branch=None,delivery_details={})
            self.touch(state)
            return {'terminal': True, 'reply': say('draft_canceled' if had_draft else 'nothing_to_cancel')}
        if action == 'ask_choice':
            from .clarification import ask
            return ask(self.menu, state, args['line_id'], args['group_id'], args.get('option_id'), utterance)
        if action == 'finish_draft':
            from .clarification import next_question
            return {'terminal':True,'reply':next_question(self.menu,state) or say('next_item')}
        if action == 'set_service':
            service = args['service']
            if service not in ['delivery', 'pickup']: raise RuleError('نوع الخدمة غير صالح.')
            if service != state['service']:
                state['service'] = service
                # Delivery addresses are not silently reused after a pickup switch.
                state['location'] = None
                state['delivery_details'] = {}
                self.touch(state)
        elif action == 'set_delivery_details':
            if not args or set(args)-{'city','zone','street','building'}:raise RuleError('اذكر تفاصيل العنوان المطلوب تعديلها.')
            if any(not isinstance(v,str) or not v.strip() or len(v)>300 for v in args.values()):raise RuleError('تفاصيل العنوان غير صالحة.')
            details=copy.deepcopy(state.get('delivery_details') or state.get('location') or {})
            supplied={k:v.strip() for k,v in args.items()}
            if 'city' in supplied and details.get('city') and normalize(supplied['city'])!=normalize(details['city']):
                details={}
            elif 'zone' in supplied and details.get('zone') and normalize(supplied['zone'])!=normalize(details['zone']):
                details={k:v for k,v in details.items() if k=='city'}
            elif 'street' in supplied and details.get('street') and normalize(supplied['street'])!=normalize(details['street']):
                details.pop('building',None);details.pop('address',None)
            if 'building' in supplied:details.pop('address',None)
            details.update(supplied)
            state.update(service='delivery',location=None,branch=None,delivery_details=details)
            self.touch(state)
            city_key=re.sub(r'^مدينه\s+','',normalize(details.get('city','')))
            zone_key=re.sub(r'^حي\s+','',normalize(details.get('zone','')))
            match=[bid for bid,b in BRANCHES.items() if city_key==normalize(b['city']) and zone_key in [normalize(z) for z in b['zones']]]
            if details.get('city') and details.get('zone') and not match:
                return {'error':'المنطقة خارج نطاق التوصيل. تقدر تختار الاستلام.','state':self.view(state)}
            if match:
                state['branch']=match[0]
                address=details.get('address') or (details['street']+'، مبنى '+details['building'] if details.get('street') and details.get('building') else '')
                if address:
                    self.act(state,'set_location',{'city':details['city'],'zone':details['zone'],'address':address})
                    state['delivery_details']=details
        elif action == 'set_location':
            city, zone, address = [str(args.get(k, '')).strip() for k in ['city', 'zone', 'address']]
            state['delivery_details']={'city':city,'zone':zone,'address':address}
            city_key = re.sub(r'^مدينه\s+', '', normalize(city))
            zone_key = re.sub(r'^حي\s+', '', normalize(zone))
            match = [bid for bid, b in BRANCHES.items() if city_key == normalize(b['city']) and zone_key in [normalize(z) for z in b['zones']]]
            if len(match) != 1:
                # An unsupported correction must not leave the old delivery address active.
                state['service'], state['location'], state['branch'] = 'delivery', None, None
                self.touch(state)
                return {'error': 'المنطقة خارج نطاق التوصيل. تقدر تختار الاستلام.', 'supported_branches': BRANCHES, 'state': self.view(state)}
            if not address or len(address) > 300:
                # A partial address correction cannot retain the previous destination.
                state['service'], state['location'], state['branch'] = 'delivery', None, match[0]
                self.touch(state)
                return {'error': 'اذكر الشارع ورقم المبنى للعنوان الجديد. تم إلغاء العنوان السابق.', 'state': self.view(state)}
            state['service'] = 'delivery'
            branch = BRANCHES[match[0]]
            state['location'] = {'city': branch['city'], 'zone': next(z for z in branch['zones'] if normalize(z) == zone_key), 'address': address}
            state['branch'] = match[0]
            self.touch(state)
        elif action == 'set_branch':
            if state['service'] != 'pickup': raise RuleError('فرع التوصيل يتحدد من المنطقة. اختيار الفرع المباشر للاستلام فقط.')
            if args['branch_id'] not in BRANCHES: raise RuleError('الفرع غير موجود.')
            state['branch'] = args['branch_id']; self.touch(state)
        elif action in ['add_item', 'update_item', 'replace_item']:
            if action == 'add_item':
                if len(state['basket']) >= 30: raise RuleError('السلة كبيرة. نحتاج موظفاً لإكمال الطلب.')
                line = {'line_id': uuid.uuid4().hex[:8], 'item_id': args['item_id'], 'quantity': args.get('quantity', 1), 'options': args.get('options', {}), 'notes': args.get('notes', '')}
                line['options'] = self.menu.canonical_options(line['item_id'], line['options'])
                self.menu.validate_line(line, state['branch'])
                state['basket'].append(line)
            else:
                line = next((x for x in state['basket'] if x['line_id'] == args['line_id']), None)
                if line is None: raise RuleError('سطر الطلب غير موجود.')
                updated = copy.deepcopy(line)
                if action == 'replace_item':
                    updated['options'] = self.menu.compatible_options(line, args['item_id'])
                    updated['item_id'] = args['item_id']
                for k in ['quantity', 'notes']:
                    if k in args: updated[k] = args[k]
                # Supplied groups replace their selections; omitted groups are preserved.
                updated['options'].update(self.menu.canonical_options(updated['item_id'], args.get('options', {})))
                self.menu.validate_line(updated, state['branch'])
                line.update(updated)
            self.touch(state)
        elif action == 'remove_item':
            if args['line_id'] not in [x['line_id'] for x in state['basket']]: raise RuleError('سطر الطلب غير موجود.')
            state['basket'] = [x for x in state['basket'] if x['line_id'] != args['line_id']]
            self.touch(state)
        elif action == 'checkout':
            view = self.view(state)
            if view['issues']: return {'error': 'لا يمكن تأكيد الطلب بعد.', 'issues': view['issues']}
            state['quote'] = {'revision': state['revision'], 'token': uuid.uuid4().hex, 'presented': False}
            return {'terminal': True, 'reply': self.summary(state), 'quote': state['quote']}
        elif action == 'confirm':
            quote = state['quote']
            if not can_confirm or not quote or not quote['presented'] or quote['revision'] != state['revision'] or self.view(state)['issues']:
                raise RuleError('نحتاج قراءة الطلب الحالي كاملاً وموافقة واضحة قبل التأكيد.')
            state['order_id'] = 'S-' + str(uuid.uuid4().int % 1000000).zfill(6)
            return {'terminal': True, 'reply': say('confirmed',order_number=spoken_order_number(state['order_id'])), 'order_id': state['order_id']}
        else: raise RuleError('الأداة غير معروفة.')
        return self.view(state)

def explicit_confirmation(text):
    # Exact normalized expressions prevent a model from confirming 'yes, but remove...'.
    return normalize(text) in {normalize(x) for x in ['نعم', 'اي', 'إيه', 'ايوه', 'أيوه', 'تمام', 'موافق', 'أكد الطلب', 'أؤكد الطلب', 'نعم أكد الطلب', 'نعم اعتمد الطلب', 'نعم اعتمد', 'اعتمد', 'اعتمد الطلب', 'ايه اكد', 'ايه اكد الطلب']}

def requests_human(text):
    text = normalize(text)
    # Negated or compound requests need semantic interpretation by the model.
    # A substring shortcut must never turn "ما أبي موظف" into a handoff.
    if set(text.split()) & {'ما', 'لا', 'مو', 'مش', 'مب', 'ماني', 'لست', 'ليس', 'بدون'}:
        return False
    return any(re.search(r'(?<!\w)' + re.escape(normalize(x)) + r'(?!\w)', text) for x in ['أبي موظف', 'أبغى موظف', 'اكلم موظف', 'أكلم انسان', 'خدمة العملاء', 'عندي شكوى', 'ابي اشتكي', 'أبغى اشتكي', 'حولني'])
