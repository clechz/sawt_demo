"""Explicit ownership of a completed turn, independent of global revision changes.

These are application result contracts, not an additional intent model. Values
come from executed tools and before/after state; free-form speech is not proof
that any operation succeeded.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, asdict
from typing import Literal

OutcomeKind = Literal['information', 'order_edit', 'checkout', 'support', 'clarification', 'control']
SpeechMode = Literal['live', 'exact', 'checkout']
ORDER_FIELDS = ('basket', 'service', 'branch', 'location', 'delivery_details', 'order_id')
ORDER_EDITS = frozenset({'add_item', 'update_item', 'replace_item', 'remove_item',
    'set_customer_name', 'set_service', 'set_branch', 'set_location', 'set_delivery_details'})
SUPPORT_ACTIONS = frozenset({'open_support_case', 'offer_resolution', 'accept_resolution',
    'decline_resolution', 'lookup_case', 'lookup_order'})


@dataclass(frozen=True)
class TurnOutcome:
    kind: OutcomeKind
    changed_domains: tuple[str, ...]
    pending_question: dict | None
    speech_mode: SpeechMode

    def envelope(self, task_id: str, revision: int) -> dict:
        value = asdict(self)
        value['changed_domains'] = list(self.changed_domains)
        return {'task_id': task_id, 'revision': revision, **value}


def describe_outcome(before: dict, after: dict, operations: list[dict], reply: str,
                     speech_mode: SpeechMode, *, has_choice_guard: bool = False) -> TurnOutcome:
    changed = []
    if any(before.get(key) != after.get(key) for key in ORDER_FIELDS):
        changed.append('order')
    if before.get('hospitality', {}) != after.get('hospitality', {}):
        changed.append('support')
    if before.get('choice_permissions', {}) != after.get('choice_permissions', {}):
        changed.append('conversation_permissions')
    successful = [op for op in operations if not op.get('result', {}).get('error')]
    names = {op['tool'] for op in successful}
    pending = None
    proposal = after.get('hospitality', {}).get('pending_resolution')
    choice = after.get('pending_choice')
    quote = after.get('quote')
    if proposal and proposal['reply'] == reply:
        pending = {'kind': 'support_resolution', 'id': proposal['id'],
                   'revision': proposal['revision']}
    elif speech_mode == 'checkout' and quote:
        pending = {'kind': 'order_confirmation', 'id': quote['token'], 'revision': quote['revision']}
    elif choice and choice['revision'] == after['revision'] and choice['question'] in reply:
        pending = {'kind': 'menu_choice', 'line_id': choice['line_id'],
                   'group_id': choice['group_id'], 'revision': choice['revision']}
    if speech_mode == 'checkout':
        kind = 'checkout'
    elif names & SUPPORT_ACTIONS:
        kind = 'support'
    elif names & {'cancel_draft'}:
        kind = 'control'
    elif names & {'set_choice_permission'} and not names & ORDER_EDITS:
        kind = 'clarification'
    elif has_choice_guard or (pending and pending['kind'] == 'menu_choice'):
        kind = 'clarification'
    elif names & ORDER_EDITS or names & {'confirm'}:
        kind = 'order_edit'
    else:
        kind = 'information'
    return TurnOutcome(kind, tuple(changed), copy.deepcopy(pending), speech_mode)
