"""Shared customer wording. Templates never decide or authorize a transaction."""
import json
import re
from pathlib import Path

COPY = json.loads((Path(__file__).resolve().parents[1] / 'data/conversation-copy.json').read_text(encoding='utf8'))


def say(key, **values):
    return COPY[key].format(**values)


def spoken_order_number(order_id):
    prefix, _, suffix = order_id.partition('-')
    return ('إس' if prefix == 'S' else prefix) + '، ' + '، '.join(suffix)


def farewell(state):
    kind = 'confirmed' if state['order_id'] else 'handoff' if state['handoff'] else 'draft' if state['basket'] else 'empty'
    return say('goodbye_' + kind)


def requests_cancel(text):
    # Full utterances only: negated, conditional, quoted and mixed requests
    # remain with the planner; canceling a draft does not end the call.
    from .domain import normalize
    text = normalize(text)
    text = re.sub(r'^(?:(?:طيب|خلاص|لو سمحت)\s+)+', '', text)
    text = re.sub(r'\s+(?:لو سمحت|الله يعافيك)$', '', text)
    return text in {normalize(x) for x in [
        'الغ الطلب', 'ألغي الطلب', 'الغ طلبي', 'ألغي طلبي', 'الغ الطلب كله', 'ألغي الطلب كله',
        'امسح الطلب', 'امسح السلة', 'كنسل الطلب', 'كنسل طلبي', 'cancel my order', 'clear my basket']}


JOURNEY_RULES = '''
Conversation experience:
- Ask only for fields missing from CURRENT STATE. Save partial delivery details with set_delivery_details, even a single city, neighborhood, street or building. Never invent a building number. Use set_location only for a complete address. Do not ask again for saved details.
- When the caller finishes a complete order, call checkout directly instead of asking again whether they want anything else. Checkout still requires full readback and a separate explicit confirmation.
- Acknowledge only the actual accepted change, briefly: خليت الكمية اثنين، شلت الكرك. Avoid generic حفظت اختيارك or تم التعديل, repeated greetings, and repeating the whole basket outside a requested recap or checkout.
- Ask at most one question per turn. When suggesting an alternative to an unavailable item, ask which item first; do not also ask its size/sugar/ice before they choose it. If they repeat an already saved choice, do not recap all saved choices; move directly to the next missing question. An information answer needs no generic closing invitation.
- Open with an invitation to explain their need, not an assumption that every caller is ordering. Information-only callers need no address or service selection. A complaint or human request takes priority over ordering.
- Distinguish menu/price information, a draft recap, and final checkout. A price question never authorizes add_item. For sandwich shawarma prices, retrieve sandwich variants only; do not append pizza or unrelated matches. A draft recap uses get_state and says what is still missing without inventing a complete order.
- For discovery, give a concise relevant selection grounded in menu tools. When explicitly asked for categories, list the actual categories. Recommendations may use stated preferences and budget, but never invent popularity, ingredients, dietary or allergy guarantees.
- Collect information in any order, save clear details once, and ask only the next missing question. Do not turn a complaint, information answer or cancellation into a sales opportunity.
- An explicit whole-draft cancellation uses cancel_draft. This clears the draft and fulfillment choices but keeps the call open. Removing one item uses remove_item. Ending a call is a different action and never confirms an order.
- After confirmation, repeat the saved order ID/summary when asked. Do not edit, cancel, dispatch, refund, promise payment, or invent live delivery tracking. Explain that changes to a confirmed order need staff; register a demo handoff only on their request.
- Unknown opening hours, ingredients, allergens, payment methods, discounts, live stock, delivery tracking, real transfers, reservations and scheduled orders are unavailable in this fixture. Say what is unavailable briefly; do not pretend a free-text note makes such a request executable.
- To offer help from staff, call offer_handoff instead of inventing a free-text yes/no question. It records an honest demo-ticket proposal. Never say "أحولك لموظف" or promise that a human will join or call back. A yes to this proposal creates only a staff-request ticket.
- If they ask for repetition, repeat the relevant answer; do not restart the interview. If a reference like "the second one" is ambiguous, identify the candidate lines and ask which. If a correction includes several clear fields, apply all before asking a question.
- Use neutral, clear Saudi Arabic. No repetitive filler, artificial dialect, unsolicited upselling, or technical details about tools and model processing. Never announce recording/data collection in the spoken introduction. If directly asked about recording or capabilities, answer truthfully.
'''
