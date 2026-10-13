"""Stateful restaurant simulation. All effects are local records, never real payments.

The menu engine stays authoritative. This adapter adds a small, coherent support
world around it; it does not turn missing menu data into invented ingredients.
"""
from __future__ import annotations
import copy
import uuid
from .domain import RuleError, money, explicit_confirmation, normalize

def resolution_confirmation(text, kind=None):
    if explicit_confirmation(text):
        return True
    phrases = {
        'نعم أوافق على الاسترجاع': {'refund_item', 'cancel_order'},
        'أوافق على الاسترجاع': {'refund_item', 'cancel_order'},
        'نعم أوافق على التعويض': {'refund_item', 'replace_item'},
        'نعم أوافق على التحويل': {'staff_review'},
    }
    return any(normalize(text)==normalize(value) and (kind is None or kind in kinds)
               for value,kinds in phrases.items())

from .transactions import StagedEngine
from .conversation import spoken_order_number
from .experience import profile
from .agent import tool

S = {'type': 'string'}
SUPPORT_TOOLS = [
    tool('restaurant_info', 'Read approved simulated operating information. Never infer ingredients/allergens.',
         {'topic': {'type': 'string', 'enum': ['hours', 'payments', 'allergens', 'support']}}, ['topic']),
    tool('lookup_order', 'Find the current or seeded order in THIS call. Unknown IDs stay unknown. Read-only.',
         {'order_id': S}),
    tool('open_support_case', 'Persist a complaint without blocking further conversation. Use known order ID when relevant. Missing/wrong item requires its exact line_id from lookup_order. Unknown orders permit general review only.',
         {'order_id': S, 'category': {'type': 'string', 'enum': ['missing_item', 'wrong_item', 'late_order', 'cancellation', 'general', 'allergy']},
          'details': S, 'line_id': S}, ['category', 'details']),
    tool('lookup_case', 'Read the actual persisted case and its resolution; do not invent progress.', {'case_id': S}, ['case_id']),
    tool('offer_resolution', 'Offer ONE policy-eligible resolution and its exact amount. Terminal. Does not execute it. The caller must hear it and accept in a later turn.',
         {'case_id': S, 'resolution': {'type': 'string', 'enum': ['refund_item', 'replace_item', 'cancel_order', 'staff_review']}}, ['case_id', 'resolution']),
    tool('accept_resolution', 'Execute only a previously played, unchanged proposal on a separate explicit yes. Terminal. Never use for yes to menu choices or for a proposal created this turn.',
         {'proposal_id': S}, ['proposal_id']),
    tool('decline_resolution', 'Reject the current support proposal, keeping the case and basket. Terminal.'),
]
SUPPORT_NAMES = {t['function']['name'] for t in SUPPORT_TOOLS}
SUPPORT_TERMINAL = {'offer_resolution', 'accept_resolution', 'decline_resolution'}
CONSEQUENTIAL = {'confirm', 'cancel_draft', 'accept_resolution'}


def new_hospitality(engine, scenario='new_order'):
    result = {'orders': {}, 'cases': [], 'pending_resolution': None, 'ledger': [], 'replacements': [], 'policy_version': 'support-1'}
    if scenario == 'new_order':
        return result
    # Exact fixture item/options: validated against the unchanged challenge CSV.
    line = engine.menu.validate_line({'line_id': 'seed-line-1', 'item_id': 'breakfast_01',
        'quantity': 1, 'options': {'portion': ['large'], 'bread': ['tamees']}, 'notes': ''}, 'ruh_narjis')
    status = 'out_for_delivery' if scenario == 'late_delivery' else 'delivered'
    result['orders']['S-DEMO7001'] = {'id': 'S-DEMO7001', 'status': status, 'items': [line],
        'total_halalas': line['line_total'] + 1500, 'paid_halalas': line['line_total'] + 1500,
        'refunded_halalas': 0, 'eta_minutes': 10 if status == 'out_for_delivery' else 0,
        'source': 'seeded_simulation'}
    return result


def ensure_current_order(state, engine):
    h = state.setdefault('hospitality', new_hospitality(engine))
    order_id = state.get('order_id')
    if order_id and order_id not in h['orders']:
        view = engine.view(state)
        h['orders'][order_id] = {'id': order_id, 'status': 'accepted', 'customer_name': state.get('customer_name', ''), 'items': copy.deepcopy(view['basket']),
            'total_halalas': view['total'], 'paid_halalas': view['total'], 'refunded_halalas': 0,
            'eta_minutes': view['eta_minutes'], 'source': 'confirmed_simulation',
            'fulfillment': {key: copy.deepcopy(view.get(key)) for key in ('service', 'branch', 'location', 'delivery_fee')}}
    return h


def hospitality_view(state, engine):
    value = engine.view(state)
    value['hospitality'] = copy.deepcopy(state.get('hospitality', {}))
    value['experience'] = copy.deepcopy(state.get('experience', {}))
    return value


class HospitalityEngine(StagedEngine):
    """Apply tools to a PRIVATE staged state, then publish with commit_bundle."""
    def __init__(self, engine, initial):
        super().__init__(engine, check_choices=True)
        pending = initial.get('hospitality', {}).get('pending_resolution')
        self.initial_proposal = copy.deepcopy(pending)
        self.initial_revision = initial['revision']
        self.support_changed = False

    def view(self, state):
        return hospitality_view(state, self.engine)

    def _record(self, state, action, args, result, *, changed=False):
        before = state['revision']
        if changed:
            # One durable revision protects BOTH order and support writes against
            # lost updates. Order records remain immutable after confirmation.
            self.engine.touch(state)
            self.support_changed = True
        self.operations.append({'tool': action, 'args': copy.deepcopy(args), 'result': copy.deepcopy(result),
                                'revision_before': before, 'revision_after': state['revision']})
        return result

    def act(self, state, action, args, *, utterance='', can_confirm=False):
        if action not in SUPPORT_NAMES:
            if action == 'get_state':
                return self._record(state, action, args, self.view(state))
            result = super().act(state, action, args, utterance=utterance, can_confirm=can_confirm)
            if action == 'confirm' and state.get('order_id'):
                ensure_current_order(state, self.engine)
                # No repeated developer disclaimer inside the disclosed simulation.
                result['reply'] = 'تأكد طلبك، يعطيك العافية.'
                self.operations[-1]['result'] = copy.deepcopy(result)
            return result
        h = ensure_current_order(state, self.engine)
        if action == 'restaurant_info':
            fact = profile()['restaurant_facts'].get(args['topic'])
            if not fact:
                raise RuleError('هالمعلومة مو متوفرة، أقدر أسجل طلب مراجعة.')
            return self._record(state, action, args, copy.deepcopy(fact))
        if action == 'lookup_order':
            oid = args.get('order_id') or state.get('order_id') or (next(iter(h['orders'])) if len(h['orders']) == 1 else None)
            order = h['orders'].get(oid)
            result = {'order': copy.deepcopy(order)} if order else {'order': None, 'question': 'وش رقم الطلب؟' if not oid else 'ما لقيت هالرقم. تتأكد لي منه؟'}
            return self._record(state, action, args, result)
        if action == 'open_support_case':
            details = args['details'].strip()
            if not details or len(details) > 600:
                raise RuleError('وضح لي المشكلة باختصار.')
            category, oid, line_id = args['category'], args.get('order_id'), args.get('line_id')
            order = h['orders'].get(oid)
            if category in ('missing_item', 'wrong_item', 'late_order', 'cancellation') and not order:
                raise RuleError('ما لقيت الطلب. نحتاج نتأكد من رقمه أول.')
            if category in ('missing_item', 'wrong_item') and not any(x['line_id'] == line_id for x in order['items']):
                raise RuleError('وش الصنف اللي فيه المشكلة؟')
            # Repeat complaints re-use an open/resolved case instead of issuing
            # several refunds for the same order line via new case IDs.
            existing = next((c for c in h['cases'] if (c['order_id'], c['category'], c['line_id']) == (oid, category, line_id)), None)
            if existing:
                return self._record(state, action, args, {'case': copy.deepcopy(existing), 'reused': True})
            case = {'id': 'C-' + uuid.uuid4().hex[:8].upper(), 'order_id': oid, 'category': category,
                    'line_id': line_id, 'details': details, 'status': 'open', 'resolution': None}
            h['cases'].append(case)
            h['pending_resolution'] = None
            return self._record(state, action, args, {'case': copy.deepcopy(case), 'reply': 'سجلت المشكلة. خلنا نشوف الحل المناسب.'}, changed=True)
        if action == 'lookup_case':
            case = next((c for c in h['cases'] if c['id'] == args['case_id']), None)
            return self._record(state, action, args, {'case': copy.deepcopy(case), 'found': case is not None})
        if action == 'decline_resolution':
            h['pending_resolution'] = None
            return self._record(state, action, args, {'terminal': True, 'reply': 'ولا يهمك، وش الحل اللي يناسبك؟'}, changed=True)
        if action == 'offer_resolution':
            case = next((c for c in h['cases'] if c['id'] == args['case_id']), None)
            if case is None:
                raise RuleError('ما لقيت البلاغ، خلنا نتأكد من رقمه.')
            if case['resolution']:
                return self._record(state, action, args, {'terminal': True, 'reply': case['resolution']['reply'], 'resolution': case['resolution']})
            kind = args['resolution']; order = h['orders'].get(case['order_id']); amount = 0
            policy = profile()['support_policy']
            policy_key = {'refund_item': 'refund_missing_or_wrong_item', 'replace_item': 'replacement_missing_or_wrong_item', 'cancel_order': 'cancel_before_preparing'}.get(kind)
            if policy_key and not policy.get(policy_key, False):
                raise RuleError('هالحل مو متاح حسب سياسة المطعم. أقدر أرفع طلب مراجعة.')
            if kind in ('refund_item', 'replace_item'):
                if not order or case['category'] not in ('missing_item', 'wrong_item') or order['status'] != 'delivered':
                    raise RuleError('هالحل ما ينطبق على حالة الطلب. أقدر أرفع المشكلة للمراجعة.')
                line = next((x for x in order['items'] if x['line_id'] == case['line_id']), None)
                if not line:
                    raise RuleError('نحتاج نحدد الصنف الصحيح أول.')
                prior = [c for c in h['cases'] if c['order_id'] == case['order_id'] and c['line_id'] == case['line_id'] and c['resolution'] and c['resolution']['kind'] in ('refund_item', 'replace_item')]
                if prior:
                    raise RuleError('الصنف سبق تعويضه، أقدر أرفع طلب مراجعة بدل تعويض مكرر.')
                amount = line['line_total'] if kind == 'refund_item' else 0
            elif kind == 'cancel_order':
                if not order or order['status'] != 'accepted':
                    raise RuleError('الطلب دخل التجهيز أو التوصيل، أقدر أرفع طلب مراجعة للإلغاء.')
                amount = order['paid_halalas'] - order['refunded_halalas']
            if order and amount > order['paid_halalas'] - order['refunded_halalas']:
                raise RuleError('المبلغ يتجاوز المتبقي من قيمة الطلب.')
            if kind == 'refund_item':
                reply = f'أقدر أرجع لك قيمة الصنف، {money(amount)} ريال. يناسبك؟'
            elif kind == 'replace_item':
                reply = f"أقدر أرسل لك نفس الصنف بديل بدون رسوم، خلال {profile()['support_policy']['replacement_eta_minutes']} دقيقة. يناسبك؟"
            elif kind == 'cancel_order':
                reply = f'الطلب ما دخل التجهيز. ألغيه وأرجع لك {money(amount)} ريال؟'
            else:
                reply = 'أرفع التفاصيل للمسؤول يراجعها؟'
            proposed = {'id': 'P-' + uuid.uuid4().hex[:10], 'case_id': case['id'], 'kind': kind,
                        'amount_halalas': amount, 'presented': False, 'reply': reply, 'revision': state['revision'] + 1}
            h['pending_resolution'] = proposed
            return self._record(state, action, args, {'terminal': True, 'reply': reply, 'proposal': copy.deepcopy(proposed)}, changed=True)
        if action == 'accept_resolution':
            proposal = h['pending_resolution']
            if (not proposal or not self.initial_proposal or proposal['id'] != args['proposal_id']
                    or proposal['id'] != self.initial_proposal['id'] or not proposal['presented']
                    or proposal['revision'] != state['revision'] or self.support_changed
                    or not resolution_confirmation(utterance, proposal['kind'])):
                raise RuleError('نراجع الحل معك أول، وبعدها نحتاج موافقتك.')
            case = next(c for c in h['cases'] if c['id'] == proposal['case_id'])
            order = h['orders'].get(case['order_id']); kind = proposal['kind']; amount = proposal['amount_halalas']
            if case['resolution']:
                raise RuleError('البلاغ سبق حله.')
            if kind in ('refund_item', 'cancel_order'):
                if not order or amount < 0 or amount > order['paid_halalas'] - order['refunded_halalas']:
                    raise RuleError('تغيرت حالة المبلغ. نراجع الحل من جديد.')
                if kind == 'cancel_order' and order['status'] != 'accepted':
                    raise RuleError('تغيرت حالة الطلب. نراجع إمكانية الإلغاء.')
                rid = 'R-' + uuid.uuid4().hex[:10].upper()
                h['ledger'].append({'id': rid, 'order_id': order['id'], 'case_id': case['id'], 'amount_halalas': amount,
                                    'type': 'refund', 'status': 'completed', 'simulated': True})
                order['refunded_halalas'] += amount
                if kind == 'cancel_order': order['status'] = 'cancelled'
                reply = ('لغيت الطلب، و' if kind == 'cancel_order' else '') + f'رجعت لك {money(amount)} ريال.'
            elif kind == 'replace_item':
                rid = 'X-' + uuid.uuid4().hex[:10].upper()
                h['replacements'].append({'id': rid, 'order_id': order['id'], 'line_id': case['line_id'],
                                          'fee_halalas': 0, 'status': 'requested', 'simulated': True})
                reply = 'سجلت لك طلب البديل بدون رسوم.'
            else:
                rid = 'M-' + uuid.uuid4().hex[:10].upper()
                reply = 'رفعت التفاصيل للمسؤول للمراجعة. رقم البلاغ ' + case['id'] + '.'
            case['status'] = 'review_requested' if kind == 'staff_review' else 'resolved'
            case['resolution'] = {'kind': kind, 'reference': rid, 'amount_halalas': amount, 'reply': reply, 'simulated': True}
            h['pending_resolution'] = None
            return self._record(state, action, args, {'terminal': True, 'reply': reply, 'resolution': copy.deepcopy(case['resolution'])}, changed=True)
        raise RuleError('خطوة غير معروفة.')
