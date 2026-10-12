"""Shared V2 state and bounded delegated reasoning, independent of transport."""
import asyncio
import time
import copy
import os
import re
from dotenv import load_dotenv
from pathlib import Path
from .domain import Engine, Menu, explicit_confirmation, normalize
from .agent import Agent
from .v2_provider import V2Provider
from .transactions import Transactions, StagedEngine, Conflict
from .choices import short_choice, simple_order, service_answer, delivery_answer, bread_correction
from .clarification import answer as choice_answer, next_question, question_targets, ask as ask_choice
from .conversation import say
from .response_style import changes, finished_order, combine

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
RUNTIME = Path(os.getenv('SAWT_RUNTIME_DIR') or ROOT / 'runtime')
engine = Engine(Menu(ROOT / 'data/restaurant-menu-complex.csv'))
tx = Transactions(os.getenv('DATABASE_URL') or RUNTIME / 'v2.sqlite3', engine)
provider = V2Provider()


async def delegate(sid, text, delegation_id, epoch, *, progress=None, voice_provider=None):
    started = time.perf_counter()
    replay = await asyncio.to_thread(tx.replay_bundle, sid, delegation_id, text)
    if replay is not None:
        return replay
    row = await asyncio.to_thread(tx.load, sid)
    if row['epoch'] != epoch or row['closed']:
        raise Conflict('Superseded delegation')
    if not explicit_confirmation(text) and row['state']['quote']:
        epoch = await asyncio.to_thread(tx.interrupt, sid)
        row = await asyncio.to_thread(tx.load, sid)
    adapter = StagedEngine(engine, check_choices=True)
    async def announce(stage):
        if progress:
            await progress(stage, epoch)
    agent = Agent(adapter, voice_provider or provider, progress=announce, extra_instructions='''
V2 voice: use clear, broadly Saudi Arabic with a light regional accent. One or two short sentences outside exact checkout. No forced dialect phrases or exaggerated enthusiasm. Ask a follow-up only when needed to resolve the caller's actual request.
Search may return partial matches (partial_matches_only=true); these are alternatives, not proof the requested dish exists. Explain a missing dish and ask which alternative they want; do not ask service/location first or retry the unavailable dish from old history on a new request. Save all clearly stated options: «شكشوكة كبير، تميس، وتوصيل» means large shakshuka with tamees bread and delivery, not a separate unspecified tamees dish. Use the retrieved option groups to distinguish a bread choice from a separate item.
Every accepted change MUST have a successful mutation tool result. Never imply a selected choice was saved after just get_item/search_menu. Valid IDs do not prove intent: do not substitute a similar available option for an unavailable customer request. خبز بر means brown/whole-wheat bread, NEVER brioche. Leave unstated heat/size/bread unresolved. Explain choice_guard results without retrying the same rejected selection. Do not call branches nearest; distance information is unavailable.
Use ask_choice for all menu option questions; it creates an authoritative context for a short reply. Save all unambiguous selections before asking it. For ambiguous 'سكر وسط/متوسط', ask_choice(sweetness, half) asks whether the caller means half sugar; do not save it until they agree. A catalog ice option on karak is a demo-menu inconsistency: acknowledge it honestly, offer the listed 'بدون ثلج' via ask_choice and accept their answer. Do not say ice is impossible while asking the caller to select ice. Do not infer service or create a location from a question about branch availability. Never ask a free-text yes/no option question outside ask_choice.
إذا سأل عن السعر فقط: قل سعر الأصناف المقصودة من المنيو بجملة واحدة ثم توقف. لا تقل «وش تفضل» أو «أي نوع يناسبك» ولا تذكر الوجبات والإضافات التي لم يسأل عنها. لا تحوّل سؤال المعلومة إلى أخذ طلب.
''')
    await asyncio.to_thread(tx.event, sid, 'delegation.started', {'delegation_id': delegation_id, 'epoch': epoch, 'text': text})
    await agent.report('understanding')
    contextual = choice_answer(engine.menu, row['state'], text)
    bread = bread_correction(engine.menu, row['state'], text)
    direct = contextual[0] if contextual else bread[0] if bread else short_choice(engine.menu, row['state'], text)
    simple = simple_order(engine.menu,row['state'],text)
    service = service_answer(row['state'],text)
    address = delivery_answer(row['state'],text)
    if service:
        state=copy.deepcopy(row['state'])
        await agent.report('set_service')
        result=adapter.act(state,'set_service',{'service':service},utterance=text)
        state,reply=agent.finish(state,text,next_question(engine.menu,state) or say('next_item'),
            [{'tool':'set_service','args':{'service':service},'result':result,'source':'explicit_service_answer'}])
    elif address:
        state=copy.deepcopy(row['state'])
        await agent.report('set_delivery_details')
        result=adapter.act(state,'set_delivery_details',address,utterance=text)
        state,reply=agent.finish(state,text,next_question(engine.menu,state),
            [{'tool':'set_delivery_details','args':address,'result':result,'source':'current_delivery_question'}])
    elif simple:
        state=copy.deepcopy(row['state']);events=[]
        service=simple.pop('service')
        if service:
            await agent.report('set_service')
            result=adapter.act(state,'set_service',{'service':service},utterance=text)
            events.append({'tool':'set_service','args':{'service':service},'result':result,'source':'unambiguous_single_dish'})
        await agent.report('add_item')
        result=adapter.act(state,'add_item',simple,utterance=text)
        events.append({'tool':'add_item','args':simple,'result':result,'source':'unambiguous_single_dish'})
        state,reply=agent.finish(state,text,say('next_item'),events)
    elif direct:
        state = copy.deepcopy(row['state'])
        await agent.report('update_item')
        result = adapter.act(state, 'update_item', direct, utterance=contextual[1] if contextual else bread[1] if bread else text)
        view = engine.view(state)
        spoken = changes(engine.menu, row['state'], state) or 'تمام.'
        state, reply = agent.finish(state, text, spoken, [{'tool': 'update_item', 'args': direct, 'result': result, 'source': 'unambiguous_short_choice'}])
    else:
        state, reply = await asyncio.wait_for(agent.turn(row['state'], text), timeout=45)
    canceled = any(e['tool']=='cancel_draft' and not e['result'].get('error') for e in reply['events'])
    edit_tools={'add_item','update_item','replace_item','remove_item','set_service','set_branch','set_location','set_delivery_details'}
    rejected=any(e['result'].get('choice_guard') or (e['tool'] in edit_tools and e['result'].get('error')) for e in reply['events'])
    if not canceled and not rejected and not state['handoff'] and not state.get('pending_handoff') and not state['quote'] and not state['order_id'] and not engine.view(state)['issues'] and finished_order(text):
        result = adapter.act(state, 'checkout', {})
        reply['events'].append({'tool': 'checkout', 'args': {}, 'result': result, 'source': 'finished_order'})
        reply['reply'] = engine.summary(state)
        state['history'][-1]['content'] = reply['reply']
    if not state['handoff'] and not state.get('pending_handoff') and not state['quote'] and not state['order_id'] and not canceled:
        asked = any(e['tool'] == 'ask_choice' and not e['result'].get('error') for e in reply['events'])
        changed = state['revision'] != row['state']['revision']
        failed = [e for e in reply['events'] if e['result'].get('error')]
        acknowledgment = changes(engine.menu, row['state'], state,
            unresolved={(q['line_id'], q['group']) for q in adapter.choice_questions if q['reason'] == 'unavailable'})
        if asked and state.get('pending_choice'):
            reply['reply'] = state['pending_choice']['question']
        if not asked:
            # An intervening topic expires the old proposal, so a later yes
            # cannot accidentally approve a choice from several turns ago.
            state['pending_choice'] = None
            targets = question_targets(engine.menu, state, reply['reply'])
            if targets and not failed and not changed:
                reply['reply'] = ask_choice(engine.menu,state,*targets[0])['reply']
            elif not changed and not failed and state['service']=='delivery' and not state['location'] and ('؟' in reply['reply'] or '?' in reply['reply']) and re.search(r'(?<!\w)(?:ال)?(?:مدينه|حي|شارع|مبني)(?!\w)',normalize(reply['reply'])):
                # A repeated saved choice can produce a verbose recap before an
                # address question. Render that question from missing state only.
                reply['reply'] = next_question(engine.menu,state) or reply['reply']
            elif changed or adapter.choice_questions or failed:
                question = next_question(engine.menu, state)
                unavailable = list(dict.fromkeys(q['question'] for q in adapter.choice_questions if q['reason'] == 'unavailable'))
                location_error = next((e['result']['error'] for e in reversed(failed) if e['tool'] in ('set_location','set_delivery_details')), None)
                saved_items={e['args'].get('item_id') for e in reply['events']
                    if e['tool'] in ('add_item','replace_item') and not e['result'].get('error')}
                unresolved_item = next((e['result']['customer_question'] for e in failed
                    if e['result'].get('customer_question') and not saved_items.intersection(e['result'].get('candidate_item_ids',[]))), None)
                # Ignore a rejected guess only if the correct dish was saved
                # afterward; otherwise ask about it before unrelated fields.
                if unresolved_item:
                    reply['reply'] = unresolved_item
                elif location_error and not state['location']:
                    reply['reply'] = location_error
                elif unavailable:
                    state['pending_choice'] = None
                    reply['reply'] = unavailable[0]
                elif question:
                    reply['reply'] = question
                elif failed and not changed:
                    reply['reply'] = 'ما تم التعديل. ' + str(failed[-1]['result']['error'])
                elif changed:
                    reply['reply'] = say('empty_basket') if not state['basket'] else say('next_item')
        if acknowledgment:
            reply['reply'] = combine(acknowledgment, reply['reply'])
        state['history'][-1]['content'] = reply['reply']
    await agent.report('saving')
    reply['state'] = engine.view(state)
    await asyncio.to_thread(tx.commit_bundle, sid, delegation_id, epoch, row['state']['revision'], state, adapter.operations, text, reply)
    reply['state'] = engine.view((await asyncio.to_thread(tx.load, sid))['state'])
    await asyncio.to_thread(tx.event, sid, 'delegation.completed', {'delegation_id': delegation_id, 'duration_ms': round((time.perf_counter()-started)*1000), 'reply': reply['reply']})
    return reply
