"""Real menu, planner runtime and transactions; scripted model, not a quality score."""
import ast
import copy
import json
from pathlib import Path

import pytest

from sawt.conversation_policy import conversation_mode, model_led_tools, release_for
from sawt.domain import Engine, Menu, new_state
from sawt.hospitality import HospitalityEngine, new_hospitality
from sawt.hospitality_runtime import CATALOG, commit_turn, prepare_turn
from sawt.transactions import Conflict, Transactions

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def engine():
    return Engine(Menu(ROOT / 'data/restaurant-menu-complex.csv'))


class Scripted:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.messages = []
        self.tools = []

    async def chat(self, messages, tools):
        self.messages.append(copy.deepcopy(messages))
        self.tools.append(copy.deepcopy(tools))
        assert self.steps, 'Unexpected model round'
        step = self.steps.pop(0)
        return step(messages) if callable(step) else step


def call(name, **args):
    return {'id': name, 'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}


def calls(*values):
    return {'content': None, 'tool_calls': list(values)}


async def turn(engine, state, planner, text):
    return await prepare_turn(engine, planner, {'state': state, 'epoch': 0}, text,
                              conversation_mode='model_led')


def rice(engine, item_id='rice_05', options=None):
    state = new_state()
    engine.act(state, 'add_item', {'item_id': item_id, 'quantity': 1,
        'options': options or {}, 'notes': ''})
    return state


def reference(messages):
    text = next(m['content'] for m in messages if m['role'] == 'system'
                and m['content'].startswith('CURRENT REFERENCE DATA'))
    return json.loads(text.split('\n', 1)[1])


def test_mode_is_explicit_and_invalid_values_fail(monkeypatch):
    monkeypatch.delenv('SAWT_CONVERSATION_MODE', raising=False)
    assert conversation_mode() == 'legacy'
    monkeypatch.setenv('SAWT_CONVERSATION_MODE', 'model_led')
    assert conversation_mode() == 'model_led'
    assert conversation_mode('legacy') == 'legacy'
    with pytest.raises(ValueError):
        conversation_mode('modle_led')
    assert release_for('model_led') == 'model-led-runtime-1'


def test_tool_filter_preserves_original_and_transaction_tools():
    original = copy.deepcopy(CATALOG)
    names = {t['function']['name'] for t in model_led_tools(CATALOG)}
    assert not names & {'finish_draft', 'ask_choice'}
    assert {'checkout', 'confirm', 'accept_resolution', 'replace_item', 'get_state'} <= names
    assert CATALOG == original


@pytest.mark.asyncio
async def test_plain_pickup_reaches_model_not_shortcut(engine, monkeypatch):
    import sawt.hospitality_runtime as runtime
    def forbidden(*args, **kwargs):
        raise AssertionError('Ordinary language was intercepted')
    for name in ('choice_answer', 'service_answer', 'delivery_answer', 'simple_order', 'next_question'):
        monkeypatch.setattr(runtime, name, forbidden)
    p = await turn(engine, new_state(), Scripted(calls(call('set_service', service='pickup')),
                   {'content': 'تمام، من أي فرع؟'}), 'استلام من الفرع')
    assert p.state['service'] == 'pickup'
    assert p.reply == 'تمام، من أي فرع؟'
    assert p.conversation_mode == 'model_led'


@pytest.mark.asyncio
async def test_unlisted_service_paraphrase_can_be_interpreted(engine):
    p = await turn(engine, new_state(), Scripted(calls(call('set_service', service='pickup')),
                   {'content': 'حياك، من أي فرع بتاخذه؟'}), 'أنا بجي آخذ الأكل بنفسي')
    assert p.state['service'] == 'pickup'


@pytest.mark.asyncio
async def test_information_answer_not_replaced_by_missing_option_question(engine):
    state = rice(engine)
    before = copy.deepcopy(state)
    planner = Scripted({'content': 'إيه، متوفر مضغوط لحم ومضغوط دجاج.'})
    p = await turn(engine, state, planner, 'عندكم مضغوط لحم ولا بس دجاج؟')
    data = reference(planner.messages[0])
    assert {x['group_id'] for x in data['requirements']['missing_options']} == {'portion', 'rice', 'spice_level'}
    assert p.reply == 'إيه، متوفر مضغوط لحم ومضغوط دجاج.'
    assert not p.operations and p.state['basket'] == state['basket']
    assert state == before and p.state['pending_choice'] is None


@pytest.mark.asyncio
async def test_model_can_ask_natural_option_question_without_terminal_tool(engine):
    state = rice(engine)
    p = await turn(engine, state, Scripted({'content': 'كم شخص بياكلون معك؟'}), 'ما أعرف وش الحجم المناسب')
    assert p.reply == 'كم شخص بياكلون معك؟'
    assert p.state['pending_choice'] is None


@pytest.mark.asyncio
async def test_correction_quantity_and_delegated_rice_save_one_line(engine):
    state = rice(engine, options={'portion': ['single'], 'spice_level': ['mild']})
    line_id = state['basket'][0]['line_id']
    before = copy.deepcopy(state)
    def inspect_updated(messages):
        result = json.loads(messages[-1]['content'])['current_reference_data']
        saved = result['state']['basket'][0]
        assert saved['quantity'] == 3 and saved['item_id'] == 'rice_06'
        assert not result['requirements']['missing_options']
        return {'content': 'خليتها ثلاثة مضغوط لحم، واخترت لك الرز الأصلي.'}
    planner = Scripted(calls(call('replace_item', line_id=line_id, item_id='rice_06',
        quantity=3, options={'rice': ['original']})), inspect_updated)
    p = await turn(engine, state, planner, 'لا ما أبي دجاج، أبغى لحم بدلها وخليها ثلاثة والرز أنت اختاره')
    assert len(p.state['basket']) == 1
    line = p.state['basket'][0]
    assert line['line_id'] == line_id and line['options'] == {
        'portion': ['single'], 'spice_level': ['mild'], 'rice': ['original']}
    assert p.state['branch'] is None and p.state['service'] is None and not p.state['order_id']
    assert p.requires_verification and p.speech_mode == 'exact'
    assert p.reply == 'خليتها ثلاثة مضغوط لحم، واخترت لك الرز الأصلي.'
    assert state == before


@pytest.mark.asyncio
async def test_short_answer_uses_previous_spoken_question(engine):
    state = rice(engine)
    state['history'] = [{'role': 'assistant', 'content': 'أقترح الرز الأصلي، يناسبك؟'}]
    line_id = state['basket'][0]['line_id']
    planner = Scripted(calls(call('update_item', line_id=line_id, options={'rice': ['original']})),
                        {'content': 'تمام، كم شخص بيأكلون؟'})
    p = await turn(engine, state, planner, 'ايه')
    assert p.state['basket'][0]['options'] == {'rice': ['original']}
    assert p.state['order_id'] is None and p.state['quote'] is None
    assert any(m.get('content') == 'أقترح الرز الأصلي، يناسبك؟' for m in planner.messages[0])


@pytest.mark.asyncio
@pytest.mark.parametrize('args', [
    {'item_id': 'not-a-dish', 'quantity': 1, 'options': {}, 'notes': ''},
    {'item_id': 'rice_06', 'quantity': 21, 'options': {}, 'notes': ''},
    {'item_id': 'rice_06', 'quantity': 1, 'options': {'rice': ['invented']}, 'notes': ''},
    {'item_id': 'rice_06', 'quantity': 1, 'options': {'rice': ['original', 'white']}, 'notes': ''},
    {'item_id': 'rice_06', 'quantity': 1, 'options': {}, 'notes': '', 'price': 1},
])
async def test_business_validation_survives_bad_model_actions(engine, args):
    def after_error(messages):
        result = json.loads(messages[-1]['content'])
        assert 'error' in result
        assert result['current_reference_data']['state']['basket'] == []
        return {'content': 'ما اكتمل التعديل، خلنا نراجع الاختيار.'}
    p = await turn(engine, new_state(), Scripted(calls(call('add_item', **args)), after_error), 'اختر لي')
    assert p.state['basket'] == [] and not p.state['order_id']


@pytest.mark.asyncio
async def test_hidden_script_tool_is_rejected_even_if_model_calls_it(engine):
    state = rice(engine)
    p = await turn(engine, state, Scripted(calls(call('finish_draft')),
                   {'content': 'وش ودك تعرف عن المضغوط؟'}), 'عندي سؤال')
    assert p.state['pending_choice'] is None and not p.operations
    assert p.reply == 'وش ودك تعرف عن المضغوط؟'


@pytest.mark.asyncio
async def test_yes_without_played_quote_cannot_create_order(engine):
    p = await turn(engine, new_state(), Scripted(calls(call('confirm')),
                   {'content': 'لازم نكمل تفاصيل الطلب أول.'}), 'نعم')
    assert not p.state['order_id']


@pytest.mark.asyncio
async def test_incomplete_checkout_still_rejected(engine):
    p = await turn(engine, rice(engine), Scripted(calls(call('checkout')),
                   {'content': 'ناقصنا اختيار الحجم أول.'}), 'خلصنا اعتمد')
    assert p.state['quote'] is None and p.state['order_id'] is None


@pytest.mark.asyncio
async def test_complete_quote_stays_exact_and_needs_separate_consent(engine):
    state = rice(engine, options={'portion': ['single'], 'rice': ['original'], 'spice_level': ['mild']})
    engine.act(state, 'set_service', {'service': 'pickup'})
    engine.act(state, 'set_branch', {'branch_id': 'ruh_narjis'})
    p = await turn(engine, state, Scripted(calls(call('checkout'))), 'هذا كل شيء')
    assert p.reply == engine.summary(p.state) and p.speech_mode == 'checkout'
    assert not p.state['quote']['presented'] and not p.state['order_id']
    q = await turn(engine, p.state, Scripted(calls(call('confirm')),
                   {'content': 'نقرأ الطلب كامل أول.'}), 'نعم')
    assert q.state['order_id'] is None
    # Simulated played receipt for a deterministic contract test, not audio evidence.
    p.state['quote']['presented'] = True
    confirmed = await turn(engine, p.state, Scripted(), 'نعم')
    assert confirmed.state['order_id'] and confirmed.requires_verification


@pytest.mark.asyncio
async def test_support_acceptance_does_not_bypass_playout(engine):
    state = new_state()
    state['hospitality'] = new_hospitality(engine, 'missing_item')
    adapter = HospitalityEngine(engine, state)
    case = adapter.act(state, 'open_support_case', {'category': 'missing_item', 'details': 'ناقص',
                        'order_id': 'S-DEMO7001', 'line_id': 'seed-line-1'})['case']
    adapter.act(state, 'offer_resolution', {'case_id': case['id'], 'resolution': 'refund_item'})
    p = await turn(engine, state, Scripted(), 'نعم')
    assert not p.state['hospitality']['ledger']
    assert p.speech_mode == 'exact'


@pytest.mark.asyncio
async def test_commit_records_mode_and_rejects_stale_bundle(engine, tmp_path):
    tx = Transactions(tmp_path / 'calls.db', engine)
    sid, _ = tx.create()
    row = tx.load(sid)
    planner = Scripted(calls(call('set_service', service='pickup')), {'content': 'من أي فرع؟'})
    p = await prepare_turn(engine, planner, row, 'أنا بجي آخذ الأكل', conversation_mode='model_led')
    result = await commit_turn(tx, sid, 'model-led-test', p)
    assert result['conversation_mode'] == 'model_led'
    assert tx.load(sid)['state']['service'] == 'pickup'
    with pytest.raises(Conflict):
        await commit_turn(tx, sid, 'different-bundle-same-stale-state', p)


def test_worker_passes_same_mode_to_both_preparation_paths():
    tree = ast.parse((ROOT / 'sawt/hospitality_voice.py').read_text(encoding='utf8'))
    preparations = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == 'prepare_turn']
    assert len(preparations) == 2
    for node in preparations:
        assert any(k.arg == 'conversation_mode' and isinstance(k.value, ast.Attribute)
                   and k.value.attr == 'conversation_mode' for k in node.keywords)
    ready = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == 'send'
             and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == 'ready']
    assert len(ready) == 1
    assert {'conversation_mode', 'worker_release'} <= {k.arg for k in ready[0].keywords}


@pytest.mark.asyncio
async def test_empty_basket_claim_repaired_into_saved_item_before_reply(engine, tmp_path):
    tx = Transactions(tmp_path / 'calls.db', engine)
    sid, _ = tx.create()
    planner = Scripted({'content': 'طلبك فيه: ٢ شاورما دجاج'},
        calls(call('add_item', item_id='sandwiches_07', quantity=2,
                   options={'meal':['sandwich'], 'bread':['saj'], 'spice_level':['not_spicy']}, notes='')),
        {'content':'استلام ولا توصيل؟'})
    p = await prepare_turn(engine, planner, tx.load(sid),
        'أبي اثنين شاورما دجاج، ساندويتش صاج بدون حار', conversation_mode='model_led')
    await commit_turn(tx, sid, 'empty-basket-claim', p)
    saved = tx.load(sid)['state']
    assert len(saved['basket']) == 1
    assert saved['basket'][0]['quantity'] == 2
    assert saved['basket'][0]['options']['bread'] == ['saj']
    assert saved['order_id'] is None
    assert p.reply == 'استلام ولا توصيل؟'


@pytest.mark.asyncio
async def test_unaccepted_tea_alternative_does_not_replace_saved_new_dish(engine, tmp_path):
    tx = Transactions(tmp_path / 'calls.db', engine)
    sid, _ = tx.create()
    row = tx.load(sid)
    row['state']['history'] = [
        {'role':'user', 'content':'أبي ثلاثة شاي عدني'},
        {'role':'assistant', 'content':'ما عندنا عدني، تبي شاي أحمر أو كرك؟'}]
    planner = Scripted(
        {'content':'تم، أضيف لك شكشوكة حجم كبير مع خبز تميس. تبي شاي أحمر أو كرك؟'},
        calls(call('add_item', item_id='breakfast_01', quantity=1,
                   options={'portion':['large'], 'bread':['tamees']}, notes='')),
        calls(call('set_service', service='delivery')),
        {'content':'التوصيل بأي مدينة؟'})
    p = await prepare_turn(engine, planner, row,
        'أبي شكشوكة كبير تميس وتوصيل', conversation_mode='model_led')
    await commit_turn(tx, sid, 'new-dish-after-unavailable', p)
    saved = tx.load(sid)['state']
    assert len(saved['basket']) == 1
    assert saved['basket'][0]['item_id'] == 'breakfast_01'
    assert saved['basket'][0]['options'] == {'portion':['large'], 'bread':['tamees']}
    assert saved['service'] == 'delivery'
    assert saved['order_id'] is None
    assert p.reply == 'التوصيل بأي مدينة؟'


@pytest.mark.asyncio
async def test_pickup_claim_requires_persisted_service_and_branch(engine, tmp_path):
    tx=Transactions(tmp_path/'calls.db',engine)
    sid,_=tx.create()
    row=tx.load(sid)
    row['state']['service']='delivery'
    planner=Scripted(
        {'content':'تم تحويل الطلب للاستلام من فرع النرجس بالرياض. الطلب باسم مين؟'},
        calls(call('set_service',service='pickup'),call('set_branch',branch_id='ruh_narjis')),
        {'content':'الطلب باسم مين؟'})
    p=await prepare_turn(engine,planner,row,'خلاص استلام من فرع النرجس بالرياض',conversation_mode='model_led')
    await commit_turn(tx,sid,'pickup-repair',p)
    saved=tx.load(sid)['state']
    assert saved['service']=='pickup' and saved['branch']=='ruh_narjis'
    assert not saved['order_id']
    assert p.reply=='الطلب باسم مين؟'


def test_unrelated_edit_does_not_validate_pickup_claim():
    from sawt.reply_evidence import unsupported_claim
    before=new_state();before['service']='delivery'
    after=copy.deepcopy(before);after['customer_name']='عبدالله'
    assert unsupported_claim(before,after,'تم تحويل الطلب للاستلام من فرع النرجس بالرياض')


@pytest.mark.asyncio
async def test_missing_name_cannot_defer_explicit_pickup_branch(engine, tmp_path):
    tx=Transactions(tmp_path/'calls.db',engine);sid,_=tx.create()
    planner=Scripted(
        calls(call('set_service',service='pickup')),
        {'content':'باقي أحتاج اسمك وأحدد لك فرع النرجس بالرياض. ممكن تعطيني اسمك؟'},
        calls(call('set_branch',branch_id='ruh_narjis')),
        {'content':'الطلب باسم مين؟'})
    p=await prepare_turn(engine,planner,tx.load(sid),'خلاص استلام من فرع النرجس بالرياض',conversation_mode='model_led')
    await commit_turn(tx,sid,'branch-before-name',p)
    saved=tx.load(sid)['state']
    assert saved['service']=='pickup' and saved['branch']=='ruh_narjis'
    assert not saved.get('customer_name') and not saved['order_id']


@pytest.mark.parametrize('text',['ما أبي استلام من فرع النرجس بالرياض','هل فيه استلام من فرع النرجس بالرياض؟','لا استلام من فرع النرجس بالرياض','استلام من فرع النرجس بالرياض أو استلام من فرع الملقا بالرياض'])
def test_pickup_guard_never_selects_negated_question_or_ambiguous_branch(text):
    from sawt.reply_evidence import unpersisted_pickup_branch
    state=new_state();before=copy.deepcopy(state)
    assert unpersisted_pickup_branch(text,state) is None
    assert state==before


@pytest.mark.asyncio
async def test_clear_dish_draft_saved_before_unnecessary_questions(engine,tmp_path):
    tx=Transactions(tmp_path/'calls.db',engine);sid,_=tx.create()
    planner=Scripted(
        {'content':'طلبت شكشوكة كبير مع تميس. تبيها بدون حار؟ وأحتاج اسمك والمدينة.'},
        calls(call('add_item',item_id='breakfast_01',quantity=1,options={'portion':['large'],'bread':['tamees']},notes=''),call('set_service',service='delivery')),
        {'content':'التوصيل بأي مدينة؟'})
    p=await prepare_turn(engine,planner,tx.load(sid),'أبي شكشوكة كبير تميس وتوصيل',conversation_mode='model_led')
    await commit_turn(tx,sid,'draft-completeness',p)
    saved=tx.load(sid)['state']
    assert len(saved['basket'])==1 and saved['basket'][0]['item_id']=='breakfast_01'
    assert saved['basket'][0]['options']=={'portion':['large'],'bread':['tamees']}
    assert saved['service']=='delivery' and not saved['order_id']


@pytest.mark.asyncio
async def test_completeness_check_does_not_order_information_request(engine):
    state=new_state()
    planner=Scripted({'content':'سعر الشكشوكة يبدأ من 18 ريال.'},{'content':'سعر الشكشوكة يبدأ من 18 ريال.'})
    p=await turn(engine,state,planner,'أبي أعرف سعر الشكشوكة')
    assert not p.operations


@pytest.mark.asyncio
@pytest.mark.parametrize('old_address',[False,True])
async def test_partial_unsupported_address_persisted_before_followup(engine,tmp_path,old_address):
    tx=Transactions(tmp_path/'calls.db',engine);sid,_=tx.create()
    row=tx.load(sid);state=row['state']
    engine.act(state,'set_service',{'service':'delivery'})
    if old_address:
        engine.act(state,'set_delivery_details',{'city':'الرياض','zone':'النرجس','street':'عثمان','building':'12'})
        state['quote']={'revision':state['revision'],'total':99,'presented':False}
    with tx.connect() as db:
        db.execute('UPDATE calls SET state=? WHERE id=?',(json.dumps(state,ensure_ascii=False),sid))
    planner=Scripted(
        {'content':'احتاج اسم الشارع والمبنى في حي الفيصلية بالدمام.'},
        calls(call('set_delivery_details',city='الدمام',zone='الفيصلية')),
        {'content':'الدمام خارج نطاق التوصيل. يناسبك الاستلام؟'})
    p=await prepare_turn(engine,planner,row,'التوصيل للدمام حي الفيصلية',conversation_mode='model_led')
    await commit_turn(tx,sid,'address-before-question',p)
    saved=tx.load(sid)['state']
    assert saved['delivery_details']=={'city':'الدمام','zone':'الفيصلية'}
    assert saved['service']=='delivery'
    assert not saved['location'] and not saved['branch'] and not saved['quote']
    assert not saved['order_id']


@pytest.mark.asyncio
async def test_address_reminder_preserves_unrelated_question(engine):
    state=new_state();engine.act(state,'set_service',{'service':'delivery'})
    planner=Scripted({'content':'التوصيل يعتمد على المدينة والحي.'},
                     {'content':'التوصيل يعتمد على المدينة والحي.'})
    p=await turn(engine,state,planner,'كيف تحسبون رسوم التوصيل لكل حي؟')
    assert not p.operations


@pytest.mark.asyncio
async def test_saved_partial_address_needs_no_redundant_planner_round(engine,tmp_path):
    tx=Transactions(tmp_path/'calls.db',engine);sid,_=tx.create()
    planner=Scripted(calls(call('set_delivery_details',city='الرياض',zone='النرجس')),
                     {'content':'وش اسم الشارع؟'})
    p=await prepare_turn(engine,planner,tx.load(sid),'التوصيل للرياض حي النرجس',conversation_mode='model_led')
    await commit_turn(tx,sid,'partial-address',p)
    saved=tx.load(sid)['state']
    assert saved['delivery_details']=={'city':'الرياض','zone':'النرجس'}
    assert saved['branch']=='ruh_narjis' and not saved['location']
    assert len(planner.messages)==2


@pytest.mark.asyncio
async def test_partial_pizza_request_saved_before_crust_question(engine,tmp_path):
    tx=Transactions(tmp_path/'calls.db',engine);sid,_=tx.create()
    planner=Scripted(
        {'content':'أي نوع عجينة تفضل لبيتزا الشاورما؟'},
        calls(call('add_item',item_id='pizza_flatbread_07',quantity=1,options={},notes='')),
        {'content':'وش الحجم اللي تبيه؟'})
    p=await prepare_turn(engine,planner,tx.load(sid),'حطني بيتزا شاورما',conversation_mode='model_led')
    await commit_turn(tx,sid,'pizza-draft',p)
    saved=tx.load(sid)['state']
    assert len(saved['basket'])==1 and saved['basket'][0]['item_id']=='pizza_flatbread_07'
    assert saved['basket'][0]['options']=={} and not saved['order_id']


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['عندكم بيتزا شاورما؟','لا تحط بيتزا شاورما'])
async def test_empty_draft_followup_guard_cannot_order_questions_or_negations(engine,text):
    planner=Scripted({'content':'عندنا بيتزا شاورما، تحب تعرف خياراتها؟'},
                     {'content':'بيتزا الشاورما موجودة، وما أضفتها لطلبك.'})
    p=await turn(engine,new_state(),planner,text)
    assert not p.operations


@pytest.mark.asyncio
async def test_size_selection_claim_requires_saved_option(engine,tmp_path):
    tx=Transactions(tmp_path/'calls.db',engine);sid,_=tx.create()
    tx.execute(sid,'seed-pizza',0,0,'add_item',{'item_id':'pizza_flatbread_07','quantity':1,'options':{},'notes':''})
    row=tx.load(sid);line=row['state']['basket'][0]['line_id']
    planner=Scripted(
        {'content':'تم، اخترت لك بيتزا شاورما كبيرة. أي نوع عجينة تفضل؟'},
        calls(call('update_item',line_id=line,options={'size':['large']})),
        {'content':'أي نوع عجينة تفضل؟'})
    p=await prepare_turn(engine,planner,row,'خلي كبير',conversation_mode='model_led')
    await commit_turn(tx,sid,'saved-size',p)
    saved=tx.load(sid)['state']
    assert len(saved['basket'])==1
    assert saved['basket'][0]['options']=={'size':['large']}
    assert not saved['order_id']


@pytest.mark.asyncio
async def test_size_answer_saved_even_without_completion_claim(engine,tmp_path):
    tx=Transactions(tmp_path/'calls.db',engine);sid,_=tx.create()
    tx.execute(sid,'seed',0,0,'add_item',{'item_id':'pizza_flatbread_07','quantity':1,'options':{},'notes':''})
    row=tx.load(sid);line=row['state']['basket'][0]['line_id']
    planner=Scripted({'content':'أي نوع عجينة تفضل؟'},
        calls(call('update_item',line_id=line,options={'size':['large']})),
        {'content':'أي نوع عجينة تفضل؟'})
    p=await prepare_turn(engine,planner,row,'خلّي كبير',conversation_mode='model_led')
    await commit_turn(tx,sid,'size-answer',p)
    assert tx.load(sid)['state']['basket'][0]['options']=={'size':['large']}


@pytest.mark.asyncio
async def test_option_question_does_not_authorize_option_edit(engine):
    state=rice(engine,item_id='pizza_flatbread_07')
    planner=Scripted({'content':'الكبير حجمه أكبر.'},{'content':'الكبير حجمه أكبر.'})
    p=await turn(engine,state,planner,'وش الفرق بين كبير ووسط؟')
    assert not p.operations


def test_option_evidence_is_read_only_and_excludes_saved_or_negated(engine):
    from sawt.reply_evidence import unsaved_option_evidence
    state=rice(engine,item_id='pizza_flatbread_07',options={'size':['large']})
    before=copy.deepcopy(state)
    assert not unsaved_option_evidence(engine.menu,state,'خلي كبير')
    assert not unsaved_option_evidence(engine.menu,state,'مو صغير')
    assert state==before
