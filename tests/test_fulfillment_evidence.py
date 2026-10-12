"""Live regression: a dish-only request must never become a delivery order."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sawt import v2_runtime as runtime
from sawt.domain import new_state, RuleError
from sawt.transactions import StagedEngine, Transactions
from sawt.choices import bread_correction


@pytest.mark.parametrize('text', [
    'أبي شاورما لحم وجبة بصاج بدون حار.', 'هل عندكم توصيل؟',
    'ما أبي توصيل', 'أبي استلام مو توصيل', 'توصيل إذا مجاني',
    'اكتب ملاحظة توصيل', 'قلت توصيل أمس', 'قال "توصيل"',
    'توصيل ولا استلام؟', 'no delivery', 'delivery if free', 'عندكم توصيل', 'مو لازم توصيل',
])
@pytest.mark.parametrize('action,args', [
    ('set_service', {'service': 'delivery'}),
    ('set_delivery_details', {'city': 'الرياض'}),
    ('set_location', {'city': 'الرياض', 'zone': 'النرجس', 'address': 'شارع 1'}),
])
def test_unstated_or_ambiguous_service_cannot_enter_through_any_fulfillment_tool(text, action, args):
    state = new_state(); before = copy.deepcopy(state)
    staged = StagedEngine(runtime.engine, check_choices=True)
    with pytest.raises(RuleError):
        staged.act(state, action, args, utterance=text)
    assert state == before and not staged.operations


@pytest.mark.parametrize('text,service', [
    ('أبي شاورما لحم وجبة بصاج بدون حار وتوصيل', 'delivery'),
    ('أبي استلام من فرع النرجس بالرياض', 'pickup'),
    ('خلاص استلام مو توصيل', 'pickup'),
    ('أبي توصيل لو سمحت', 'delivery'),
    ('بستلمه', 'pickup'), ('pickup please', 'pickup'), ('delivery', 'delivery'),
])
def test_explicit_service_selections_and_corrections_are_saved(text, service):
    state = new_state()
    StagedEngine(runtime.engine, check_choices=True).act(state, 'set_service', {'service': service}, utterance=text)
    assert state['service'] == service


def test_address_answer_does_not_need_to_repeat_already_selected_delivery():
    state = new_state(); state['service'] = 'delivery'
    StagedEngine(runtime.engine, check_choices=True).act(state, 'set_delivery_details', {'city': 'الرياض'}, utterance='الرياض')
    assert state['delivery_details'] == {'city': 'الرياض'}


def seeded_shawarma():
    state = new_state()
    runtime.engine.act(state, 'add_item', {'item_id': 'sandwiches_08', 'quantity': 1,
        'options': {'meal': ['meal'], 'bread': ['saj'], 'spice_level': ['not_spicy']}, 'notes': ''})
    return state


@pytest.mark.parametrize('text', ['خل الخبز بر مو صاج', 'خل الخبز برمو صاج', 'أقصد خبز أسمر بدل الصاج', 'أبي خبز بر'])
async def test_unavailable_bread_is_explained_without_planner_or_silent_service_change(tmp_path, monkeypatch, text):
    tx = Transactions(tmp_path / 'bread.db', runtime.engine); sid, _ = tx.create()
    state = seeded_shawarma(); tx.commit_bundle(sid, 'seed', 0, 0, state, [], response={})
    monkeypatch.setattr(runtime, 'tx', tx)
    provider = SimpleNamespace(chat=AsyncMock(side_effect=AssertionError('No planner required')))
    result = await runtime.delegate(sid, text, 'correction', 0, voice_provider=provider)
    assert result['state']['service'] is None
    assert result['state']['basket'][0]['options'] == {'meal': ['meal'], 'bread': [], 'spice_level': ['not_spicy']}
    assert not result['state']['quote'] and not result['state']['order_id']
    assert 'مو متوفر' in result['reply'] and 'شلت الخبز' not in result['reply']
    assert 'بريوش' in result['reply'] and 'صاج' in result['reply']
    provider.chat.assert_not_awaited()


@pytest.mark.parametrize('text', [
    'خل الخبز بر لو متوفر', 'خل الخبز بر وزيد الكمية اثنين',
    'لا تغير الخبز', 'هل عندكم خبز بر؟', 'قال "خل الخبز بر"',
    'خل الخبز بر مو بريوش', 'خل الخبز بر أو خس',
])
def test_bread_shortcut_defers_conditions_mixed_requests_and_wrong_target(text):
    assert bread_correction(runtime.engine.menu, seeded_shawarma(), text) is None


def test_bread_shortcut_cannot_choose_between_two_dishes():
    state = seeded_shawarma(); state['basket'].append(copy.deepcopy(state['basket'][0]))
    assert bread_correction(runtime.engine.menu, state, 'خل الخبز بر مو صاج') is None


@pytest.mark.parametrize('text', ['أبي خبز أسمر بدل الصاج', 'بدل الصاج خبز بر'])
def test_planner_bread_guard_does_not_keep_the_rejected_old_bread(text):
    state = seeded_shawarma()
    result = StagedEngine(runtime.engine, check_choices=True).act(state, 'update_item',
        {'line_id': state['basket'][0]['line_id'], 'options': {'bread': ['saj']}}, utterance=text)
    assert state['basket'][0]['options']['bread'] == []
    assert result['choice_guard'][0]['reason'] == 'unavailable'


async def test_planner_hallucinated_service_is_rejected_while_clear_dish_survives(tmp_path, monkeypatch):
    tx = Transactions(tmp_path / 'service.db', runtime.engine); sid, _ = tx.create()
    monkeypatch.setattr(runtime, 'tx', tx)
    def call(name, args):
        return {'id': name, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}
    provider = SimpleNamespace(supports_tool_batches=True, chat=AsyncMock(side_effect=[
        {'tool_calls': [call('set_service', {'service': 'delivery'}), call('add_item', {
            'item_id': 'sandwiches_08', 'quantity': 1, 'notes': '',
            'options': {'meal': ['meal'], 'bread': ['saj'], 'spice_level': ['not_spicy']}}), call('finish_draft', {})]},
        {'tool_calls': [call('finish_draft', {})]},
    ]))
    result = await runtime.delegate(sid, 'أبي شاورما لحم وجبة بصاج بدون حار', 'dish', 0, voice_provider=provider)
    assert result['state']['service'] is None and len(result['state']['basket']) == 1
    from sawt.conversation import say
    assert result['reply'].endswith(say('service_question'))
    assert not result['state']['quote']
