"""Reject unsupported completion claims, using staged state as the authority.

This is a narrow output guard, not an intent classifier. It never edits an order.
The planner can repair a rejected claim by executing a tool or clarifying.
"""
import re
from .domain import normalize, BRANCHES


def unsupported_claim(before, after, reply):
    text = normalize(reply)
    review_claim = re.search(r'\b(?:تم رفع|رفعت|رفعنا) (?:الشكوي|الشكوى|التفاصيل|البلاغ|طلب المراجعه|المشكله)', text)
    reviewed = any(c.get('status') == 'review_requested' and
                   (c.get('resolution') or {}).get('kind') == 'staff_review'
                   for c in after.get('hospitality', {}).get('cases', []))
    if review_claim and not reviewed:
        return 'No staff review has been accepted and saved. Do not claim the complaint was raised. If a presented proposal exists and the caller explicitly accepted it, use accept_resolution; otherwise offer or repeat the actual pending proposal and wait for separate acceptance.'
    if not after.get('customer_name') and re.search(r'(?:الطلب|طلبك) باسم\s*[:：]?\s*(?!مين\b|من\b|ايش\b|وش\b)\S+', text):
        return 'The customer name has not been saved. Use set_customer_name with the name supplied by the caller before claiming the order is under that name. If they requested the summary and all fields are complete, execute checkout next; do not ask permission to calculate the price.'
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
    edits = any(before.get(key) != after.get(key) for key in ('basket','service','branch','location','delivery_details','customer_name'))
    changed_claim = re.search(r'\b(?:عدلت|غيرت|بدلت|خليت|زدت|ضفت|اضفت|اخترت)\b|\bتم (?:تعديل|تغيير|تحويل|نقل|اضافه|اختيار|حفظ|تسجيل)|\b(?:updated|added|changed)\b', text)
    fulfillment_claim = re.search(r'(?:تم (?:تحويل|تغيير)|حولت|غيرت) (?:الطلب|طلبك)(?: الي| الى)? (?:ل)?(لاستلام|استلام|للتوصيل|توصيل)', text)
    if fulfillment_claim:
        desired = 'pickup' if 'استلام' in fulfillment_claim[1] else 'delivery'
        if after.get('service') != desired:
            return 'The claimed fulfillment mode is not saved. Execute set_service with the caller requested mode, then set_branch or delivery details they supplied. Do not acknowledge pickup/delivery from text alone or from unrelated edits.'
    accepted_add = re.search(r'\b(?:تم|تمام|ابشر)[،, ]+(?:راح )?(?:اضيف|نضيف)\b', text)
    if accepted_add and before['basket'] == after['basket']:
        return 'The promised item addition was not saved. Save the requested available dish with add_item before acknowledging it. A fulfillment change alone is not an item addition. Unaccepted alternatives are not ordered items.'
    if changed_claim and not edits:
        return 'No requested draft edit was saved this turn. Do not claim a change. Use the appropriate tool to make the requested edit, or ask a focused clarification. Current saved state is authoritative.'
    h=after.get('hospitality', {})
    if h.get('pending_resolution') and re.search(r'تم (?:تسجيل موافقتك|اعتماد|استرجاع|ارجاع)|رجعنا|اعتمدنا', text):
        return 'The support proposal is still pending, so no resolution was completed. Use accept_resolution only after heard proposal and explicit consent; otherwise clarify. Do not claim approval/refund from words alone.'
    return None


def unpersisted_pickup_branch(text, state):
    """Guard an explicit complete pickup selection, never infer a branch.

    Questions, negations and ambiguous multi-branch requests stay with the
    planner. This returns a repair instruction, not a state mutation.
    """
    normalized = normalize(text)
    if any(mark in text for mark in ('?', '؟')) or re.search(r'\b(?:لا|مو|بدون|هل|كيف|وين|بكم|اذا)\b|ما ابي', normalized):
        return None
    matches = [bid for bid, branch in BRANCHES.items()
               if 'استلام من ' + normalize(branch['name']) in normalized]
    if len(matches) != 1 or state.get('order_id'):
        return None
    if state.get('service') != 'pickup' or state.get('branch') != matches[0]:
        return 'The caller explicitly selected pickup from ' + matches[0] + '. Persist set_service(pickup) and set_branch for that supplied branch before asking for the customer name or another missing field. Name is required at checkout, not before saving fulfillment. If a tool rejects the selection, explain its actual validation error; do not claim or defer the change.'
    return None


def unsaved_option_evidence(menu, state, text):
    """Read-only candidates for a completeness check, never choice authority.

    Questions and ambiguous references can mention these labels too; the planner
    must interpret the current utterance before calling a validated edit tool.
    """
    from .choices import matches
    if state.get('order_id'):
        return []
    result = []
    for line in state['basket']:
        for gid, group in menu.get(line['item_id'])['groups'].items():
            mentioned = {oid for _, _, oid in matches(text, gid, group['options'])}
            missing = mentioned - set(line['options'].get(gid, []))
            if missing:
                result.append({'line_id':line['line_id'], 'group':gid,
                               'mentioned_not_saved':sorted(missing)})
    return result


def unapproved_confirmation_claim(reply):
    """Ignore only explicit local refusals; inspect every subsequent claim."""
    text = normalize(reply)
    pattern = r'\b(?:ناكد|نوكد|ااكد|اؤكد|اكد|نعتمد|اعتمد) (?:لك )?(?:الطلب|طلبك)|تاكد طلبك|تم تاكيد|(?:اضغط|اضغطي|اضغطوا) تاكيد'
    for match in re.finditer(pattern, text):
        prefix = text[:match.start()]
        if re.search(r'(?:\bما (?:اقدر|نقدر|اقدر ان|نقدر ان)|\bلا (?:يمكنني|يمكننا)|\bلن|\bلم)\s+$', prefix):
            continue
        return True
    return False
