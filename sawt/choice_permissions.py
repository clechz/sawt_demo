"""Scoped, single-use menu-choice delegation for the model-led planner.

The planner interprets natural language. This module checks referenced menu
fields, records the current utterance as evidence, and prevents an interpreted
rice permission from being spent on portion/quantity/fulfillment/checkout.
Evidence matching proves provenance, NOT that an LLM understood consent or
negation correctly. Real-model semantic evaluations remain required.
"""
from __future__ import annotations

import copy
import hashlib

from .agent import tool, OPTIONS
from .domain import RuleError
from .hospitality import HospitalityEngine

PERMISSION_TOOLS = [
    tool('set_choice_permission',
         'Record the customer delegating or revoking ONLY named option groups on one existing '
         'dish. Quote the relevant CURRENT customer words verbatim; interpret them in context. '
         'A negated or retracted delegation is revoke, not delegate. This does not select food. '
         'May be batched before select_delegated_options; no generated grant ID is needed.',
         {'line_id': {'type': 'string'},
          'group_ids': {'type': 'array', 'minItems': 1, 'maxItems': 12,
                        'uniqueItems': True, 'items': {'type': 'string'}},
          'decision': {'type': 'string', 'enum': ['delegate', 'revoke']},
          'evidence': {'type': 'string', 'minLength': 1, 'maxLength': 600}},
         ['line_id', 'group_ids', 'decision', 'evidence']),
    tool('select_delegated_options',
         'Choose actual menu options ONLY within this line\'s active recorded permissions. '
         'Consumes those permissions once. Never use update_item/replace_item as a workaround '
         'for a denied delegated selection. Explain your selections in your natural reply. '
         'Existing explicitly chosen fields are preserved unless that field was delegated.',
         {'line_id': {'type': 'string'}, 'options': OPTIONS}, ['line_id', 'options']),
]
PERMISSION_NAMES = frozenset(t['function']['name'] for t in PERMISSION_TOOLS)


def validate_permission_args(name: str, args: dict) -> None:
    expected = ({'line_id', 'group_ids', 'decision', 'evidence'}
                if name == 'set_choice_permission' else {'line_id', 'options'})
    if name not in PERMISSION_NAMES or not isinstance(args, dict) or set(args) != expected:
        raise RuleError('تفاصيل تفويض الاختيار ناقصة أو غير صالحة.')
    if not isinstance(args['line_id'], str) or not 1 <= len(args['line_id']) <= 128:
        raise RuleError('حدد الصنف المقصود بالاختيار.')
    if name == 'set_choice_permission':
        groups = args['group_ids']
        if (not isinstance(groups, list) or not 1 <= len(groups) <= 12
                or any(not isinstance(g, str) or not g or len(g) > 128 for g in groups)
                or len(groups) != len(set(groups))):
            raise RuleError('حدد خيارات الصنف المقصودة فقط.')
        if args['decision'] not in ('delegate', 'revoke'):
            raise RuleError('نوع التفويض غير صالح.')
        if not isinstance(args['evidence'], str) or not 1 <= len(args['evidence'].strip()) <= 600:
            raise RuleError('اربط التفويض بكلام العميل الحالي.')
    else:
        options = args['options']
        if (not isinstance(options, dict) or not 1 <= len(options) <= 12
                or any(not isinstance(g, str) or not isinstance(v, list) or not v
                       or any(not isinstance(o, str) for o in v) for g, v in options.items())):
            raise RuleError('اختر من خيارات القائمة داخل حدود التفويض.')


def permission_view(state: dict) -> dict:
    """Detached reference data; granting nothing by merely inspecting it."""
    return copy.deepcopy(state.get('choice_permissions', {}))


class ModelLedEngine(HospitalityEngine):
    """Model-led planning with protected saved choices and scoped delegation."""
    def __init__(self, engine, initial):
        super().__init__(engine, initial)
        self.check_choices = False

    def _line(self, state, line_id):
        if state.get('order_id'):
            raise RuleError('الطلب معتمد؛ التعديل يحتاج مراجعة حالة الطلب.')
        line = next((x for x in state['basket'] if x['line_id'] == line_id), None)
        if line is None:
            raise RuleError('حدد الصنف الموجود في الطلب أول.')
        return line

    def _record_permission(self, state, name, args, result, before):
        self.operations.append({'tool': name, 'args': copy.deepcopy(args),
                                'result': copy.deepcopy(result),
                                'revision_before': before, 'revision_after': state['revision']})
        return result

    def act(self, state, action, args, *, utterance='', can_confirm=False):
        if action not in PERMISSION_NAMES:
            if action == 'update_item' and isinstance(args.get('options'), dict):
                # An explicit catalog choice cannot be overwritten with a
                # different value. Paraphrases without a lexical match stay
                # with the planner; this guard is not an intent classifier. Delegated selection
                # has its separate permission-checked path below.
                from .choices import matches
                line = self._line(state, args.get('line_id'))
                item = self.menu.get(line['item_id'])
                selections = self.menu.canonical_options(item['id'], args['options'])
                for gid, chosen in selections.items():
                    previous = set(line['options'].get(gid, []))
                    if not previous or not isinstance(chosen, list) or gid not in item['groups']:
                        continue
                    added = set(chosen) - previous
                    evidence = {oid for _, _, oid in matches(utterance, gid, item['groups'][gid]['options'])}
                    if evidence and added - evidence:
                        raise RuleError('الخيار السابق محفوظ. لا تستبدله بخيار ما طلبه العميل بوضوح. إذا الكلام تكرار أو مو واضح، احتفظ بالاختيار واسأل عن المقصود. إذا طلب تختار عنه، استخدم تفويض الاختيار المحدد.')
            result = super().act(state, action, args, utterance=utterance, can_confirm=can_confirm)
            if not result.get('error') and not result.get('choice_guard'):
                self._invalidate_explicit_changes(state, action, args)
            return result
        validate_permission_args(action, args)
        line = self._line(state, args['line_id'])
        menu_item = self.menu.get(line['item_id'])
        before = state['revision']
        if action == 'set_choice_permission':
            evidence = args['evidence'].strip()
            if not isinstance(utterance, str) or evidence not in utterance:
                raise RuleError('التفويض لازم يكون من كلام العميل الحالي، مو من افتراض.')
            if any(group not in menu_item['groups'] for group in args['group_ids']):
                raise RuleError('التفويض يخص خيارات الصنف فقط، مو الفرع أو الكمية أو تأكيد الطلب.')
            # Update only the requested groups; no wildcard or permission growth.
            permissions = state.setdefault('choice_permissions', {}).setdefault(line['line_id'], {})
            status = 'active' if args['decision'] == 'delegate' else 'revoked'
            digest = hashlib.sha256(utterance.encode('utf8')).hexdigest()
            for group in args['group_ids']:
                permissions[group] = {'item_id': line['item_id'], 'group_id': group,
                    'status': status, 'evidence': evidence, 'source_utterance': utterance,
                    'source_hash': digest, 'granted_at_revision': before,
                    'selected_option_ids': None}
            self.engine.touch(state)
            result = {'permissions': copy.deepcopy(permissions), 'scope': list(args['group_ids']),
                      'does_not_authorize_checkout': True}
            return self._record_permission(state, action, args, result, before)

        choices = args['options']
        permissions = state.get('choice_permissions', {}).get(line['line_id'], {})
        for group, values in choices.items():
            grant = permissions.get(group)
            if (group not in menu_item['groups'] or not grant
                    or grant['item_id'] != line['item_id'] or grant['status'] != 'active'):
                raise RuleError('ما عندي تفويض نشط لهالخيار. احفظ اختيارات العميل ولا تخمن الباقي.')
            if any(option not in menu_item['groups'][group]['options'] for option in values):
                raise RuleError('الخيار المقترح مو موجود في القائمة.')
        # Validate the ENTIRE edit before consuming any permission. Domain also
        # checks duplicates, cardinality and branch availability; no price input.
        result = super().act(state, 'update_item',
            {'line_id': line['line_id'], 'options': copy.deepcopy(choices)}, utterance=utterance)
        for group, values in choices.items():
            permissions[group]['status'] = 'used'
            permissions[group]['selected_option_ids'] = list(values)
        result = {'selection': copy.deepcopy(choices), 'line_id': line['line_id'],
                  'source': 'scoped_delegation', 'permissions': copy.deepcopy(permissions),
                  'result': result}
        return self._record_permission(state, action, args, result, before)

    @staticmethod
    def _invalidate_explicit_changes(state, action, args):
        permissions = state.get('choice_permissions', {})
        if action in ('cancel_draft', 'confirm'):
            targets = [(line, list(groups)) for line, groups in permissions.items()]
        elif action in ('replace_item', 'remove_item'):
            line = args.get('line_id')
            targets = [(line, list(permissions.get(line, {})))]
        elif action == 'update_item':
            targets = [(args.get('line_id'), list(args.get('options', {})))]
        else:
            return
        for line, groups in targets:
            for group in groups:
                grant = permissions.get(line, {}).get(group)
                if grant:
                    grant['status'] = 'superseded'
