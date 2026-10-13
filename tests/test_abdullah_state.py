"""Real planner orchestration/domain/storage with scripted tool selection.

These tests certify persisted transitions, not Arabic model or microphone quality.
"""
import copy
import json
from pathlib import Path
import pytest
from sawt.domain import Engine, Menu
from sawt.hospitality_runtime import prepare_turn, commit_turn
from sawt.transactions import Transactions, Conflict

ROOT = Path(__file__).resolve().parents[1]

class Planner:
    def __init__(self, *batches):
        self.batches = iter(batches)
    async def chat(self, messages, tools):
        return next(self.batches)

def calls(*actions):
    return {'tool_calls': [{'id': str(i), 'function': {'name': name,
        'arguments': json.dumps(args)}} for i, (name, args) in enumerate(actions)]}

@pytest.fixture
def draft(tmp_path):
    engine = Engine(Menu(ROOT / 'data/restaurant-menu-complex.csv'))
    tx = Transactions(tmp_path / 'calls.db', engine)
    sid, _ = tx.create(experience={'voice': 'ash', 'scenario': 'new_order',
                                 'version': 'v3', 'conversation_mode': 'model_led'})
    state = tx.load(sid)['state']
    for item in ('breakfast_01', 'breakfast_02'):
        engine.act(state, 'add_item', {'item_id': item, 'quantity': 1,
            'options': {'portion': ['large'], 'bread': ['tamees']}, 'notes': ''})
    engine.act(state, 'set_service', {'service': 'pickup'})
    engine.act(state, 'set_branch', {'branch_id': 'ruh_narjis'})
    tx.commit_bundle(sid, 'seed', 0, 0, state, [])
    return engine, tx, sid

async def run(draft, actions, text, bundle):
    engine, tx, sid = draft
    row = tx.load(sid)
    p = await prepare_turn(engine, Planner(calls(*actions), {'content': 'أبشر، عدلت طلبك.'}),
                           row, text, conversation_mode='model_led')
    await commit_turn(tx, sid, bundle, p)
    # New store instance must observe the same durable result.
    persisted = Transactions(tx.path, engine).load(sid)['state']
    assert persisted == p.state
    return persisted

@pytest.mark.parametrize('phase', ['draft', 'quoted', 'presented'])
async def test_remove_persists_at_every_unconfirmed_phase(draft, phase):
    engine, tx, sid = draft
    if phase != 'draft':
        tx.execute(sid, 'quote', tx.load(sid)['state']['revision'], 0, 'checkout', {})
        if phase == 'presented':
            with tx.connect() as db:
                state = tx.load(sid, db)['state']; state['quote']['presented'] = True
                db.execute('UPDATE calls SET state=? WHERE id=?', (json.dumps(state), sid))
    before = tx.load(sid)['state']; target = before['basket'][0]['line_id']
    state = await run(draft, [('remove_item', {'line_id': target})],
                      'ايه بس شيل الشكشوكة، ما أبيها', 'remove')
    assert [x['line_id'] for x in state['basket']] == [before['basket'][1]['line_id']]
    assert state['quote'] is None and state['order_id'] is None
    assert engine.view(state)['total'] == 2600
    assert state['revision'] > before['revision']
    with tx.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM placed_orders').fetchone()[0] == 0

async def test_return_to_earlier_quantity_is_not_swallowed_by_tool_cache(draft):
    _, tx, sid = draft
    line = tx.load(sid)['state']['basket'][0]['line_id']
    state = await run(draft, [('update_item', {'line_id': line, 'quantity': n}) for n in (2, 3, 2)],
                      'اثنين لا ثلاثة، لا خلاص اثنين', 'corrections')
    assert state['basket'][0]['quantity'] == 2
    assert len([e for e in tx.events(sid) if e['kind'] == 'tool.committed']) == 3

async def test_consecutive_duplicate_add_is_still_suppressed(draft):
    _, tx, sid = draft
    args = {'item_id': 'breakfast_01', 'quantity': 1, 'options': {}, 'notes': ''}
    state = await run(draft, [('add_item', args), ('add_item', args)], 'زيد شكشوكة', 'add')
    assert len(state['basket']) == 3

async def test_quantity_options_notes_and_fulfillment_changes_persist(draft):
    engine, tx, sid = draft
    line = tx.load(sid)['state']['basket'][0]['line_id']
    state = await run(draft, [('update_item', {'line_id': line, 'quantity': 2,
        'options': {'portion': ['regular']}, 'notes': 'بدون فلفل'}),
        ('set_service', {'service': 'delivery'}),
        ('set_location', {'city': 'الرياض', 'zone': 'النرجس', 'address': 'شارع 1 عمارة 2'})],
        'خليها اثنين عادي بدون فلفل وتوصيل للنرجس بالرياض شارع واحد عمارة اثنين', 'delivery')
    assert state['basket'][0]['options'] == {'portion': ['regular'], 'bread': ['tamees']}
    assert engine.view(state)['delivery_fee'] == 1500
    state = await run(draft, [('set_service', {'service': 'pickup'}),
        ('set_branch', {'branch_id': 'ruh_olaya'}), ('update_item', {'line_id': line, 'notes': ''})],
        'لا استلام من العليا وشيل الملاحظة', 'pickup')
    assert state['location'] is None and state['branch'] == 'ruh_olaya'
    assert state['basket'][0]['notes'] == '' and engine.view(state)['delivery_fee'] == 0

async def test_interrupted_prepared_removal_cannot_overwrite_newer_input(draft):
    engine, tx, sid = draft; row = tx.load(sid)
    before = copy.deepcopy(row['state'])
    p = await prepare_turn(engine, Planner(calls(('remove_item', {'line_id': before['basket'][0]['line_id']})),
        {'content': 'شلتها.'}), row, 'شيل الشكشوكة', conversation_mode='model_led')
    tx.interrupt(sid)
    with pytest.raises(Conflict):
        await commit_turn(tx, sid, 'superseded', p)
    assert tx.load(sid)['state']['basket'] == before['basket']

async def test_requote_separate_confirmation_and_immutable_receipt_snapshot(draft):
    engine, tx, sid = draft
    row = tx.load(sid); target = row['state']['basket'][0]['line_id']
    state = await run(draft, [('remove_item', {'line_id': target})], 'شيل الشكشوكة', 'remove')
    # A new checkout binds only the surviving line and its server total.
    p = await prepare_turn(engine, Planner(calls(('checkout', {}))), tx.load(sid),
                           'خلاص هذا طلبي', conversation_mode='model_led')
    await commit_turn(tx, sid, 'requote', p)
    assert p.state['quote']['presented'] is False
    with pytest.raises(Exception):
        tx.execute(sid, 'early-yes', p.state['revision'], 0, 'confirm', {}, utterance='نعم')
    # A real receipt completion gate, with only its clock simulated for this
    # offline test; synthesis/model listening is explicitly not certified.
    rid = tx.prepare_audio(sid, p.state['quote']['token'], duration=1)
    tx.playback(sid, rid, 'started')
    with tx.connect() as db:
        db.execute('UPDATE receipts SET started=started-2 WHERE id=?', (rid,))
    tx.playback(sid, rid, 'completed', 1)
    p = await prepare_turn(engine, Planner(), tx.load(sid), 'نعم', conversation_mode='model_led')
    result = await commit_turn(tx, sid, 'confirm', p)
    persisted = Transactions(tx.path, engine).load(sid)['state']
    order = persisted['hospitality']['orders'][persisted['order_id']]
    assert order['total_halalas'] == 2600 and len(order['items']) == 1
    assert order['fulfillment']['service'] == 'pickup'
    assert order['fulfillment']['branch']['name'] == 'فرع النرجس بالرياض'
    assert tx.replay_bundle(sid, 'confirm', 'نعم') == result
    tx.interrupt(sid, close=True)
    assert tx.load(sid)['state']['hospitality']['orders'] == persisted['hospitality']['orders']
    with tx.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM placed_orders').fetchone()[0] == 1
