"""Offline customer-service contracts: no provider credits, no real payments."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sawt.agent import Agent
from sawt.domain import Engine, Menu, RuleError, new_state, requests_human
from sawt.transactions import StagedEngine


@pytest.fixture
def engine():
    return Engine(Menu(Path(__file__).resolve().parents[1] / 'data/restaurant-menu-complex.csv'))


def call(name, args, ident='support'):
    return {'id': ident, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}


@pytest.mark.parametrize('topic', [
    'refund', 'wrong_order', 'delay', 'food_quality', 'payment',
    'allergens', 'hours', 'tracking', 'promotions', 'human', 'other',
])
def test_demo_support_policy_is_grounded_and_read_only(engine, topic):
    state = new_state()
    snapshot = copy.deepcopy(state)
    result = engine.act(state, 'get_support_info', {'topic': topic})
    assert result['verified_demo_fact']
    assert result['can_issue_real_refund'] is False
    assert result['can_transfer_to_real_staff'] is False
    assert result['can_check_external_order'] is False
    assert state == snapshot


def test_open_refund_case_tracks_issue_without_money_movement_or_handoff(engine):
    state = new_state()
    engine.act(state, 'add_item', {'item_id':'sandwiches_07', 'quantity':1,
                                   'options':{}, 'notes':''})
    basket = copy.deepcopy(state['basket'])
    before_revision = state['revision']
    result = engine.act(state, 'file_support_case', {
        'category':'refund_request', 'description':'استلمت طلب ناقص وأبي استرجاع',
        'order_reference':'9999'
    })
    assert result['terminal'] and not result['duplicate']
    case = result['case']
    assert case['case_id'].startswith('T-')
    assert case['status'] == 'demo_logged'
    assert case['real_refund_issued'] is False and case['staff_reviewed'] is False
    assert case['reference_verified'] is False
    assert state['revision'] == before_revision + 1
    assert state['basket'] == basket and state['order_id'] is None
    assert state['handoff'] is None and 'استرجاع مالي' in result['reply']
    assert engine.view(state)['support_cases'] == [case]
    # Filing a mock ticket does not freeze an unrelated order.
    engine.act(state, 'set_service', {'service':'pickup'})
    assert state['service'] == 'pickup'
    repeat = engine.act(state, 'file_support_case', {
        'category':'refund_request', 'description':'استلمت طلب ناقص وأبي استرجاع',
        'order_reference':'9999'
    })
    assert repeat['duplicate'] and repeat['case']['case_id'] == case['case_id']
    assert len(state['support_cases']) == 1


def test_support_case_status_is_current_session_only(engine):
    state = new_state()
    no_case = engine.act(state, 'get_support_case_status', {})
    assert no_case['terminal'] and not no_case['found']
    filed = engine.act(state, 'file_support_case', {
        'category':'missing_item','description':'الطلب ناقص',
    })
    sid = filed['case']['case_id']
    found = engine.act(state, 'get_support_case_status', {})
    assert found['found'] and found['case']['case_id'] == sid
    assert 'ما تمت مراجعته' in found['reply']
    assert 'استرجاع' in found['reply']
    other = engine.act(new_state(), 'get_support_case_status', {'case_id':sid})
    assert not other['found']


def test_ambiguous_case_status_asks_for_reference(engine):
    state = new_state()
    for issue in ('الطلب ناقص','الطلب وصل متأخر'):
        engine.act(state, 'file_support_case', {
            'category':'other', 'description':issue,
        })
    result = engine.act(state, 'get_support_case_status', {})
    assert not result['found'] and 'رقم البلاغ' in result['reply']


def test_mock_ticket_after_confirmed_order_never_cancels_or_refunds_it(engine):
    state = new_state()
    engine.act(state, 'set_service', {'service':'pickup'})
    engine.act(state, 'set_branch', {'branch_id':'ruh_narjis'})
    engine.act(state, 'add_item', {'item_id':'sandwiches_07', 'quantity':1,
        'options':{'meal':['sandwich'],'bread':['saj'],'spice_level':['not_spicy']}, 'notes':''})
    engine.act(state, 'checkout', {})
    state['quote']['presented'] = True
    confirm = engine.act(state, 'confirm', {}, can_confirm=True)
    old_order = confirm['order_id']
    r = engine.act(state, 'file_support_case', {
        'category':'wrong_order','description':'استلمت صنف غير المطلوب',
        'order_reference':old_order
    })
    assert r['case']['reference_verified'] is True
    assert state['order_id'] == old_order
    assert state['basket'][0]['item_id'] == 'sandwiches_07'
    assert r['case']['real_refund_issued'] is False
    assert engine.act(state, 'get_support_case_status', {})['found']


@pytest.mark.parametrize('category,description', [
    ('invented','تجربة'), ('refund_request',''), ('refund_request','x'*301),
])
def test_invalid_support_case_cannot_mutate_state(engine, category, description):
    state = new_state();original = copy.deepcopy(state)
    with pytest.raises(RuleError):
        engine.act(state,'file_support_case',{'category':category,'description':description})
    assert state == original


@pytest.mark.parametrize('text', [
    'عندي شكوى', 'ابي اشتكي', 'أبغى اشتكي', 'ما أبي موظف',
    'لا حولني', 'هل أقدر أسترجع فلوسي؟',
])
def test_complaint_or_policy_question_does_not_auto_transfer_to_staff(text):
    assert not requests_human(text)


@pytest.mark.parametrize('text', ['أبي موظف', 'ابغى اكلم خدمة العملاء', 'حولني'])
def test_explicit_staff_requests_still_have_fast_path(text):
    assert requests_human(text)


def test_model_reported_issue_uses_verified_tool_and_preserves_basket(engine):
    provider = SimpleNamespace(supports_tool_batches=True,
        chat=AsyncMock(return_value={'tool_calls':[call('file_support_case', {
            'category':'food_quality', 'description':'الأكل وصل بارد'
        })]}))
    state, reply = asyncio.run(Agent(StagedEngine(engine,check_choices=True),provider).turn(
        new_state(), 'الأكل وصل بارد وأبي أرفع شكوى'))
    assert state['support_cases'][0]['category']=='food_quality'
    assert 'بلاغ تجريبي' in reply['reply']
    assert 'استرجاع مالي' in reply['reply']
    assert not state['handoff'] and not state['order_id']
    assert [x['tool'] for x in reply['events']]==['file_support_case']


def test_policy_question_does_not_file_case_without_customer_request(engine):
    provider = SimpleNamespace(supports_tool_batches=True,
        chat=AsyncMock(side_effect=[
            {'tool_calls':[call('get_support_info', {'topic':'refund'}, 'lookup')]},
            {'content':'ما عندنا استرجاع مبالغ فعلي في التجربة؛ أقدر أسجل بلاغ تجريبي إذا احتجت.'},
        ]))
    state, reply = asyncio.run(Agent(StagedEngine(engine,check_choices=True),provider).turn(
        new_state(), 'هل في سياسة استرجاع؟'))
    assert not state['support_cases']
    assert [x['tool'] for x in reply['events']]==['get_support_info']
    assert 'التجربة' in reply['reply']


def test_customer_can_check_session_case_after_it_was_filed(engine):
    initial = new_state()
    first_provider=SimpleNamespace(supports_tool_batches=True,
        chat=AsyncMock(return_value={'tool_calls':[call('file_support_case', {
            'category':'late_order', 'description':'الطلب متأخر'
        })]}))
    state, _=asyncio.run(Agent(StagedEngine(engine,check_choices=True),first_provider).turn(
        initial,'طلبي متأخر وأبي أسجل بلاغ'))
    status_provider=SimpleNamespace(supports_tool_batches=True,
        chat=AsyncMock(return_value={'tool_calls':[call('get_support_case_status', {})]}))
    later, result=asyncio.run(Agent(StagedEngine(engine,check_choices=True),status_provider).turn(
        state,'وش صار على بلاغي؟'))
    assert later['support_cases']==state['support_cases']
    assert 'ما تمت مراجعته' in result['reply']
    assert [x['tool'] for x in result['events']]==['get_support_case_status']
