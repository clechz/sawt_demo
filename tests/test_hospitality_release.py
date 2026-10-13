"""Release regressions through V3 preparation AND durable publication.

Scripted planner envelopes isolate orchestration contracts; these are not
microphone, model-intelligence, or Saudi-accent measurements.
"""
import copy
import json
from pathlib import Path

import pytest

from sawt.domain import Engine, Menu, new_state
from sawt.experience import validate_experience
from sawt.hospitality_runtime import prepare_turn, commit_turn
from sawt.provider import ProviderError
from sawt.transactions import Transactions


@pytest.fixture
def engine():
    return Engine(Menu(Path(__file__).resolve().parents[1] / 'data/restaurant-menu-complex.csv'))


class Planner:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = 0

    async def chat(self, messages, tools):
        self.calls += 1
        assert self.steps, 'Unexpected additional model request'
        step = self.steps.pop(0)
        return step(messages) if callable(step) else step


def tool(name, **args):
    return {'id': name, 'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}


def calls(*items):
    return {'tool_calls': list(items)}


def fill_order(engine, state, kind):
    if kind == 'empty':
        return
    engine.act(state, 'add_item', {'item_id': 'breakfast_01', 'quantity': 1,
        'options': {} if kind == 'incomplete' else {'portion': ['large'], 'bread': ['tamees']}, 'notes': ''})
    if kind in ('complete', 'confirmed'):
        engine.act(state, 'set_service', {'service': 'pickup'})
        engine.act(state, 'set_branch', {'branch_id': 'ruh_narjis'})
    if kind == 'confirmed':
        engine.act(state, 'checkout', {})
        state['quote']['presented'] = True  # Test fixture, not receiver evidence.
        engine.act(state, 'confirm', {}, can_confirm=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['empty', 'incomplete', 'complete', 'confirmed'])
async def test_support_outcome_survives_every_order_state(engine, tmp_path, kind):
    tx = Transactions(tmp_path / 'calls.db', engine)
    sid, _ = tx.create(experience=validate_experience('cedar', 'missing_item'))
    row = tx.load(sid)
    state = copy.deepcopy(row['state'])
    fill_order(engine, state, kind)
    tx.commit_bundle(sid, 'fixture', row['epoch'], row['state']['revision'], state, [], 'fixture', {})
    before = tx.load(sid)['state']
    phrase = 'سجلت المشكلة. وش الحل اللي تفضله؟'
    planner = Planner(calls(tool('open_support_case', category='missing_item', details='الشكشوكة ناقصة',
        order_id='S-DEMO7001', line_id='seed-line-1')), {'content': phrase})
    prepared = await prepare_turn(engine, planner, tx.load(sid), 'الشكشوكة ناقصة')
    result = await commit_turn(tx, sid, 'complaint', prepared)
    saved = tx.load(sid)['state']
    assert result['reply'] == phrase
    assert saved['basket'] == before['basket']
    assert saved['order_id'] == before['order_id']
    assert len(saved['hospitality']['cases']) == 1
    assert result['outcome']['kind'] == 'support'
    assert result['outcome']['changed_domains'] == ['support']
    assert result['outcome']['task_id'] == 'complaint'
    assert result['outcome']['revision'] == saved['revision']
    assert tx.replay_bundle(sid, 'complaint', 'الشكشوكة ناقصة') == result


@pytest.mark.asyncio
async def test_unavailable_option_keeps_draft_and_returns_a_question(engine):
    state = new_state()
    engine.act(state, 'add_item', {'item_id': 'sandwiches_07', 'quantity': 1,
        'options': {'meal': ['sandwich'], 'bread': ['saj'], 'spice_level': ['not_spicy']}, 'notes': ''})
    line = state['basket'][0]['line_id']
    planner = Planner(calls(tool('update_item', line_id=line, options={'bread': ['brioche']})),
        calls(tool('ask_choice', line_id=line, group_id='bread')))
    prepared = await prepare_turn(engine, planner, {'state': state, 'epoch': 0}, 'بدل الخبز بخبز بر')
    assert prepared.state['basket'][0]['options']['bread'] == []
    assert prepared.state['pending_choice']['group_id'] == 'bread'
    assert 'خليت الخبز بريوش' not in prepared.reply
    assert prepared.outcome.kind == 'clarification'
    assert prepared.outcome.changed_domains == ('order',)
    assert state['basket'][0]['options']['bread'] == ['saj']


@pytest.mark.asyncio
async def test_rejected_free_text_question_cannot_escape_after_a_lookup(engine):
    state = new_state()
    engine.act(state, 'add_item', {'item_id': 'breakfast_01', 'quantity': 1, 'options': {}, 'notes': ''})
    line = state['basket'][0]['line_id']
    planner = Planner({'content': 'الحجم كبير ولا عادي؟'}, calls(tool('get_state')),
        calls(tool('ask_choice', line_id=line, group_id='portion')))
    prepared = await prepare_turn(engine, planner, {'state': state, 'epoch': 0}, 'وش باقي على طلبي؟')
    assert planner.calls == 3
    assert prepared.state['pending_choice']['group_id'] == 'portion'
    assert prepared.reply == prepared.state['pending_choice']['question']
    assert prepared.outcome.pending_question['kind'] == 'menu_choice'


@pytest.mark.asyncio
async def test_repeated_untracked_questions_exhaust_budget_without_becoming_reply(engine):
    state = new_state()
    engine.act(state, 'add_item', {'item_id': 'breakfast_01', 'quantity': 1, 'options': {}, 'notes': ''})
    planner = Planner(*[{'content': 'الحجم كبير ولا عادي؟'} for _ in range(6)])
    before = copy.deepcopy(state)
    with pytest.raises(ProviderError):
        await prepare_turn(engine, planner, {'state': state, 'epoch': 0}, 'وش باقي على طلبي؟')
    assert state == before


@pytest.mark.asyncio
async def test_price_information_does_not_become_order_edit(engine):
    state = new_state()
    planner = Planner(calls(tool('get_item', item_id='breakfast_01')), {'content': 'السعر يعتمد على الحجم والخبز.'})
    prepared = await prepare_turn(engine, planner, {'state': state, 'epoch': 0}, 'بكم الشكشوكة؟')
    assert prepared.outcome.kind == 'information'
    assert prepared.outcome.changed_domains == ()
    assert not prepared.state['basket']


@pytest.mark.asyncio
async def test_repeated_confirm_returns_same_order_without_planner(engine, tmp_path):
    tx = Transactions(tmp_path / 'calls.db', engine)
    sid, _ = tx.create(experience=validate_experience())
    row = tx.load(sid); state = copy.deepcopy(row['state'])
    fill_order(engine, state, 'confirmed')
    tx.commit_bundle(sid, 'fixture', 0, 0, state, [], 'fixture', {})
    original = tx.load(sid)['state']['order_id']
    prepared = await prepare_turn(engine, Planner(), tx.load(sid), 'نعم')
    await commit_turn(tx, sid, 'repeat', prepared)
    assert prepared.state['order_id'] == original
    with tx.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM placed_orders').fetchone()[0] == 1
