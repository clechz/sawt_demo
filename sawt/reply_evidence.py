"""Reject unsupported completion claims, using staged state as the authority.

This is a narrow output guard, not an intent classifier. It never edits an order.
The planner can repair a rejected claim by executing a tool or clarifying.
"""
import re
from .domain import normalize


def unsupported_claim(before, after, reply):
    text = normalize(reply)
    if not after['basket'] and re.search(r'طلبك (?:فيه|يحتوي|عباره عن)|في (?:طلبك|السله)\s*[:：]', text):
        return 'The saved basket is empty. Do not describe requested dishes as an existing order. Save the clear requested items/options with tools, then summarize only saved state or ask one genuine clarification.'
    # Future offers and negative statements do not claim completed deletion.
    removed = bool(re.search(r'\b(?:شلت|حذفت|حذفنا|استبعدت|استبعدناه|انحذف|انشال)\b|\bتم (?:حذف|استبعاد|ازاله)|\b(?:removed|deleted)\b', text))
    old = {x['line_id']: x for x in before['basket']}
    new = {x['line_id']: x for x in after['basket']}
    removed_value = bool(old.keys() - new.keys()) or any(
        old[k].get('notes') != new[k].get('notes') or any(
            set(values) - set(new[k]['options'].get(group, []))
            for group, values in old[k]['options'].items()) for k in old.keys() & new.keys())
    if removed and not removed_value:
        return 'No item, option or note was removed. Do not claim removal. Execute the requested valid edit or ask what to remove; preserve all other items.'
    edits = any(before.get(key) != after.get(key) for key in ('basket','service','branch','location','delivery_details'))
    changed_claim = re.search(r'\b(?:عدلت|غيرت|بدلت|خليت|زدت|ضفت|اضفت)\b|\bتم (?:تعديل|تغيير|اضافه|اختيار|حفظ|تسجيل)|\b(?:updated|added|changed)\b', text)
    if changed_claim and not edits:
        return 'No requested draft edit was saved this turn. Do not claim a change. Use the appropriate tool to make the requested edit, or ask a focused clarification. Current saved state is authoritative.'
    h=after.get('hospitality', {})
    if h.get('pending_resolution') and re.search(r'تم (?:تسجيل موافقتك|اعتماد|استرجاع|ارجاع)|رجعنا|اعتمدنا', text):
        return 'The support proposal is still pending, so no resolution was completed. Use accept_resolution only after heard proposal and explicit consent; otherwise clarify. Do not claim approval/refund from words alone.'
    return None
