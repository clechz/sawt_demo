"""Read-only order requirements for a model-led conversation.

This is reference data, not dialogue policy or permission to submit an order.
The caller decides which question is relevant; existing domain tools remain
responsible for validation, mutations, checkout and explicit confirmation.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Protocol


class MenuReader(Protocol):
    def get(self, item_id: str) -> dict[str, Any]: ...
    def validate_line(self, line: dict[str, Any], branch: str | None = None) -> dict[str, Any]: ...


def collect_requirements(menu: MenuReader, state: Mapping[str, Any]) -> dict[str, Any]:
    """Describe missing choices without selecting one, asking, or mutating state.

    Input is authoritative persisted domain state. Invalid catalog selections
    still raise through validate_line; this function does not repair them or
    translate arbitrary customer speech. Output order implies no conversation
    priority. An empty result is NOT authorization to checkout or confirm.
    """
    result: dict[str, Any] = {
        'revision': state['revision'],
        'order_status': 'confirmed' if state.get('order_id') else 'draft',
        'missing_options': [],
        'fulfillment': [],
        'unavailable_lines': [],
    }
    if state.get('order_id'):
        return result

    # Detached copies also protect state from a future mutable menu adapter.
    snapshot = copy.deepcopy(dict(state))
    branch = snapshot.get('branch')
    for line in snapshot['basket']:
        validated = menu.validate_line(copy.deepcopy(line), branch)
        item = menu.get(line['item_id'])
        if validated['available'] is False:
            result['unavailable_lines'].append({
                'line_id': line['line_id'], 'item_id': line['item_id'],
                'item_name': item['name'], 'branch_id': branch,
            })
        for group_id, group in item['groups'].items():
            selected = line['options'].get(group_id, [])
            if len(selected) >= group['min']:
                continue
            result['missing_options'].append({
                'line_id': line['line_id'], 'item_id': line['item_id'],
                'item_name': item['name'], 'group_id': group_id,
                'group_name': group['name'], 'minimum': group['min'],
                'maximum': group['max'], 'selected_option_ids': list(selected),
                'allowed_options': [dict(option_id=oid, **copy.deepcopy(option))
                                    for oid, option in group['options'].items()],
            })

    if snapshot.get('customer_name_required') and not snapshot.get('customer_name'):
        result['fulfillment'].append({'field':'customer_name','question':'الطلب باسم مين؟'})
    service = snapshot.get('service')
    if not service:
        result['fulfillment'].append({'field': 'service', 'allowed_values': ['delivery', 'pickup']})
    elif service == 'pickup':
        if not branch:
            result['fulfillment'].append({'field': 'branch'})
    elif service == 'delivery':
        if not snapshot.get('location'):
            details = snapshot.get('delivery_details', {})
            missing = [field for field in ('city', 'zone', 'street', 'building') if not details.get(field)]
            result['fulfillment'].extend({'field': field} for field in missing)
            if not missing:
                result['fulfillment'].append({'field': 'service_area_validation'})
        elif not branch:
            # Delivery routing is derived by tools, not picked by the customer.
            result['fulfillment'].append({'field': 'delivery_branch_resolution'})
    else:
        raise ValueError('Unsupported service in authoritative order state')
    return result
