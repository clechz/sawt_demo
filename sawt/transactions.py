"""V2 durable command boundary. SQLite serializes writers across processes.

Provider calls never hold a database transaction. Every operation compares its
input revision and conversation epoch inside the same transaction as its write.
"""
import copy
import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from .domain import new_state, RuleError, explicit_confirmation
from .agent import validate_args
from .conversation import say, spoken_order_number


class Conflict(Exception):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Transactions:
    def __init__(self, path, engine):
        self.path, self.engine = str(path), engine
        self.postgres = None
        if self.path.startswith(('postgres://', 'postgresql://')):
            from .postgres import Database
            self.postgres = Database(self.path)
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS calls(
              id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, state TEXT NOT NULL,
              epoch INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, closed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS operations(
              session_id TEXT, operation_id TEXT, digest TEXT NOT NULL, result TEXT NOT NULL,
              PRIMARY KEY(session_id,operation_id));
            CREATE TABLE IF NOT EXISTS receipts(
              id TEXT PRIMARY KEY, session_id TEXT NOT NULL, token TEXT NOT NULL,
              revision INTEGER NOT NULL, epoch INTEGER NOT NULL, duration REAL NOT NULL,
              started REAL, completed REAL);
            CREATE TABLE IF NOT EXISTS placed_orders(
              session_id TEXT PRIMARY KEY, id TEXT UNIQUE NOT NULL, snapshot TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
              at REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bundles(
              session_id TEXT, bundle_id TEXT, input_hash TEXT NOT NULL, response TEXT NOT NULL,
              PRIMARY KEY(session_id,bundle_id));
            CREATE TABLE IF NOT EXISTS readback_streams(
              receipt_id TEXT PRIMARY KEY, claimed INTEGER NOT NULL DEFAULT 0);
            ''')

    def connect(self):
        if self.postgres is not None:
            return self.postgres.connect()
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def create(self, enforce_limits=False):
        sid, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if enforce_limits:
                max_active = max(1, int(os.getenv('SAWT_MAX_ACTIVE_CALLS', '4')))
                max_hourly = max(1, int(os.getenv('SAWT_MAX_CALLS_PER_HOUR', '120')))
                active = db.execute('SELECT COUNT(*) FROM calls WHERE closed=0 AND created>?', (time.time()-600,)).fetchone()[0]
                hourly = db.execute('SELECT COUNT(*) FROM calls WHERE created>?', (time.time()-3600,)).fetchone()[0]
                if active >= max_active or hourly >= max_hourly:
                    raise Conflict(f'Call budget reached: at most {max_active} active calls and {max_hourly} starts/hour')
            db.execute('INSERT INTO calls(id,token_hash,state,created) VALUES(?,?,?,?)',
                       (sid, hashlib.sha256(token.encode()).hexdigest(), encode(new_state()), time.time()))
        return sid, token

    def load(self, sid, db=None):
        if db is None:
            with self.connect() as conn:
                return self.load(sid, conn)
        row = db.execute('SELECT * FROM calls WHERE id=?', (sid,)).fetchone()
        if not row:
            raise KeyError('Unknown session')
        return {**dict(row), 'state': json.loads(row['state'])}

    def authorize(self, sid, token):
        row = self.load(sid)
        if not secrets.compare_digest(row['token_hash'], hashlib.sha256(token.encode()).hexdigest()):
            raise PermissionError('Invalid session token')
        return row

    def event(self, sid, kind, payload, db=None):
        if db is None:
            with self.connect() as conn:
                self.event(sid, kind, payload, conn)
            return
        db.execute('INSERT INTO audit(session_id,at,kind,payload) VALUES(?,?,?,?)',
                   (sid, time.time(), kind, encode(payload)))

    def events(self, sid, after=0):
        with self.connect() as db:
            return [{**dict(r), 'payload': json.loads(r['payload'])} for r in db.execute(
                'SELECT sequence,at,kind,payload FROM audit WHERE session_id=? AND sequence>? ORDER BY sequence LIMIT 500', (sid, after))]

    def interrupt(self, sid, *, invalidate_quote=True, close=False):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.load(sid, db)
            state = row['state']
            if invalidate_quote:
                state['quote'] = None
            epoch = row['epoch'] + 1
            db.execute('UPDATE calls SET state=?,epoch=?,closed=? WHERE id=?',
                       (encode(state), epoch, int(close or row['closed']), sid))
            self.event(sid, 'call.closed' if close else 'input.changed', {'epoch': epoch}, db)
            return epoch

    def execute(self, sid, operation_id, expected_revision, epoch, tool, args, *, utterance=''):
        validate_args(tool, args)
        digest = hashlib.sha256(encode([expected_revision, epoch, tool, args, utterance]).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM operations WHERE session_id=? AND operation_id=?', (sid, operation_id)).fetchone()
            if prior:
                if prior['digest'] != digest:
                    raise Conflict('Operation ID reused with different input')
                return json.loads(prior['result'])
            row = self.load(sid, db)
            state = row['state']
            if row['closed'] or row['epoch'] != epoch or state['revision'] != expected_revision:
                raise Conflict('Stale operation')
            before = copy.deepcopy(state)
            quote = state['quote']
            confirmed = bool(quote and quote['presented'] and explicit_confirmation(utterance))
            result = self.engine.act(state, tool, args, utterance=utterance, can_confirm=confirmed)
            if tool == 'checkout' and state['quote']:
                state['quote']['text'] = self.engine.summary(state)
                state['quote']['text_hash'] = hashlib.sha256(state['quote']['text'].encode()).hexdigest()
            if state['order_id'] and not before['order_id']:
                # A collision fails and rolls back; never silently ignores a missing order.
                state['order_id'] = 'S-' + uuid.uuid4().hex[:12].upper()
                result['order_id'] = state['order_id']
                result['reply'] = say('confirmed',order_number=spoken_order_number(state['order_id']))
                db.execute('INSERT INTO placed_orders VALUES(?,?,?)', (sid, state['order_id'], encode(state)))
            envelope = {'result': result, 'state': state, 'operation_id': operation_id}
            db.execute('UPDATE calls SET state=? WHERE id=?', (encode(state), sid))
            db.execute('INSERT INTO operations VALUES(?,?,?,?)', (sid, operation_id, digest, encode(envelope)))
            self.event(sid, 'tool.committed', {'operation_id': operation_id, 'tool': tool, 'args': args,
                       'revision_before': before['revision'], 'revision_after': state['revision'], 'result': result}, db)
            return envelope

    def history(self, sid, epoch, history):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.load(sid, db)
            if row['epoch'] != epoch or row['closed']:
                raise Conflict('Superseded reply')
            row['state']['history'] = history[-16:]
            db.execute('UPDATE calls SET state=? WHERE id=?', (encode(row['state']), sid))

    def replay_bundle(self, sid, bundle_id, text):
        with self.connect() as db:
            row = db.execute('SELECT input_hash,response FROM bundles WHERE session_id=? AND bundle_id=?', (sid,bundle_id)).fetchone()
        if row:
            if row['input_hash'] != hashlib.sha256(text.encode()).hexdigest():
                raise Conflict('Delegation ID reused with different input')
            return json.loads(row['response'])

    def commit_bundle(self, sid, bundle_id, epoch, revision, state, operations, text='', response=None):
        """Publish a planner turn atomically; interruption discards only unpublished work."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.load(sid, db)
            if row['closed'] or row['epoch'] != epoch or row['state']['revision'] != revision:
                raise Conflict('Superseded operation bundle')
            if state['order_id'] and not row['state']['order_id']:
                db.execute('INSERT INTO placed_orders VALUES(?,?,?)', (sid, state['order_id'], encode(state)))
            for index, operation in enumerate(operations):
                oid = f'{bundle_id}:{index}'
                digest = hashlib.sha256(encode(operation).encode()).hexdigest()
                db.execute('INSERT INTO operations VALUES(?,?,?,?)', (sid, oid, digest, encode(operation)))
                self.event(sid, 'tool.committed', {**operation, 'operation_id': oid}, db)
            db.execute('UPDATE calls SET state=? WHERE id=?', (encode(state), sid))
            db.execute('INSERT INTO bundles VALUES(?,?,?,?)',
                       (sid,bundle_id,hashlib.sha256(text.encode()).hexdigest(),encode(response or {})))

    def prepare_audio(self, sid, token, duration=0):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.load(sid, db)
            quote = row['state']['quote']
            if row['closed'] or not quote or quote['token'] != token:
                raise Conflict('Readback superseded')
            rid = uuid.uuid4().hex
            db.execute('INSERT INTO receipts(id,session_id,token,revision,epoch,duration) VALUES(?,?,?,?,?,?)',
                       (rid, sid, token, row['state']['revision'], row['epoch'], duration))
            if duration == 0:
                db.execute('INSERT INTO readback_streams(receipt_id) VALUES(?)', (rid,))
            return rid

    def current_receipt(self, sid, receipt_id, db=None):
        if db is None:
            with self.connect() as conn:
                return self.current_receipt(sid, receipt_id, conn)
        row = self.load(sid, db)
        receipt = db.execute('SELECT * FROM receipts WHERE id=? AND session_id=?', (receipt_id, sid)).fetchone()
        quote = row['state']['quote']
        if (not receipt or row['closed'] or not quote or quote['token'] != receipt['token']
                or row['epoch'] != receipt['epoch'] or row['state']['revision'] != receipt['revision']
                or receipt['duration'] < 0 or time.time() - row['created'] > 600):
            raise Conflict('Invalid playback receipt')
        return dict(receipt), quote

    def claim_audio(self, sid, receipt_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            receipt, quote = self.current_receipt(sid, receipt_id, db)
            if receipt['duration'] == 0:
                changed = db.execute('UPDATE readback_streams SET claimed=1 WHERE receipt_id=? AND claimed=0', (receipt_id,)).rowcount
                if not changed:
                    raise Conflict('Readback is already streaming; request a new playback')
            return receipt, quote

    def finish_audio(self, sid, receipt_id, duration):
        if duration <= 0:
            raise Conflict('Empty readback')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.current_receipt(sid, receipt_id, db)
            db.execute('UPDATE receipts SET duration=? WHERE id=?', (duration, receipt_id))

    def fail_audio(self, sid, receipt_id):
        with self.connect() as db:
            db.execute('UPDATE receipts SET duration=-1 WHERE id=? AND session_id=? AND duration=0', (receipt_id, sid))

    def playback(self, sid, receipt_id, phase, position=0):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.load(sid, db)
            receipt = db.execute('SELECT * FROM receipts WHERE id=? AND session_id=?', (receipt_id, sid)).fetchone()
            quote = row['state']['quote']
            if (not receipt or row['closed'] or not quote or quote['token'] != receipt['token']
                    or row['epoch'] != receipt['epoch'] or row['state']['revision'] != receipt['revision']):
                raise Conflict('Invalid playback receipt')
            now = time.time()
            if phase == 'started':
                db.execute('UPDATE receipts SET started=COALESCE(started,?) WHERE id=?', (now, receipt_id))
            elif phase == 'completed':
                if receipt['duration'] <= 0 or not receipt['started'] or position < receipt['duration'] - .2 or now - receipt['started'] < receipt['duration'] - .5:
                    raise Conflict('Readback has not finished playing')
                db.execute('UPDATE receipts SET completed=COALESCE(completed,?) WHERE id=?', (now, receipt_id))
                quote['presented'] = True
                quote['receipt_id'] = receipt_id
                db.execute('UPDATE calls SET state=? WHERE id=?', (encode(row['state']), sid))
            else:
                raise ValueError('Invalid playback phase')
            self.event(sid, 'playback.' + phase, {'receipt_id': receipt_id, 'revision': receipt['revision']}, db)


class CommandEngine:
    """Adapter lets the existing tested planner use durable per-tool commits."""
    def __init__(self, transactions, sid, epoch, delegation_id):
        self.tx, self.sid, self.epoch, self.delegation_id = transactions, sid, epoch, delegation_id
        self.menu = transactions.engine.menu
        self.step = 0

    def view(self, state):
        return self.tx.engine.view(state)

    def act(self, state, action, args, *, utterance='', can_confirm=False):
        self.step += 1
        output = self.tx.execute(self.sid, f'{self.delegation_id}:{self.step}', state['revision'], self.epoch, action, args, utterance=utterance)
        state.clear()
        state.update(copy.deepcopy(output['state']))
        return output['result']


class StagedEngine:
    """Tools validate against a private draft; commit_bundle publishes all or none."""
    def __init__(self, engine, *, check_choices=False):
        self.engine, self.menu = engine, engine.menu
        self.operations = []
        self.check_choices = check_choices
        self.choice_questions = []

    def view(self, state):
        return self.engine.view(state)

    def act(self, state, action, args, **kwargs):
        validate_args(action, args)
        rejected = []
        if self.check_choices and action in ('add_item', 'update_item', 'replace_item'):
            from .choices import checked_options, check_item_variant
            previous = next((x for x in state['basket'] if x['line_id'] == args.get('line_id')), None)
            item_id = args.get('item_id') or (previous or {}).get('item_id')
            item = self.menu.get(item_id)
            if action in ('add_item', 'replace_item'):
                check_item_variant(self.menu, item, kwargs.get('utterance', ''))
            prior_options = self.menu.compatible_options(previous, item_id) if action == 'replace_item' and previous else (previous or {}).get('options')
            args, rejected = checked_options(self.menu, item, args, kwargs.get('utterance', ''),
                                             prior_options)
        before = state['revision']
        previous_order = state['order_id']
        result = self.engine.act(state, action, args, **kwargs)
        if rejected:
            line_id = args.get('line_id') or state['basket'][-1]['line_id']
            rejected = [dict(x, line_id=line_id) for x in rejected]
            self.choice_questions.extend(rejected)
            result['choice_guard'] = rejected
            result['instruction'] = 'Unverified choices were NOT saved. Keep this incomplete draft, ask the questions, and never claim the rejected choices were accepted.'
        if action == 'checkout' and state['quote']:
            state['quote']['text'] = self.engine.summary(state)
            state['quote']['text_hash'] = hashlib.sha256(state['quote']['text'].encode()).hexdigest()
        if state['order_id'] and not previous_order:
            state['order_id'] = 'S-' + uuid.uuid4().hex[:12].upper()
            result['order_id'] = state['order_id']
            result['reply'] = say('confirmed',order_number=spoken_order_number(state['order_id']))
        self.operations.append({'tool': action, 'args': copy.deepcopy(args), 'result': copy.deepcopy(result),
                                'revision_before': before, 'revision_after': state['revision']})
        return result
