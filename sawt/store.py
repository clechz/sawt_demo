"""One SQLite transaction persists session, order and request replay together."""
import json
import sqlite3
from pathlib import Path
from .domain import new_state

class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS turns (session_id TEXT, request_id TEXT, input_hash TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(session_id, request_id));
            CREATE TABLE IF NOT EXISTS orders (session_id TEXT PRIMARY KEY, id TEXT UNIQUE NOT NULL, snapshot TEXT NOT NULL);
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def load(self, session):
        with self.connect() as db:
            row = db.execute('SELECT state FROM sessions WHERE id=?', (session,)).fetchone()
        return json.loads(row[0]) if row else None

    def create(self, session):
        state = new_state()
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES (?, ?)', (session, json.dumps(state, ensure_ascii=False)))
        return state

    def replay(self, session, request_id, input_hash):
        with self.connect() as db:
            row = db.execute('SELECT input_hash,response FROM turns WHERE session_id=? AND request_id=?', (session, request_id)).fetchone()
        if row:
            if row[0] != input_hash: raise ValueError('request_id reused with different input')
            return json.loads(row[1])

    def save(self, session, state, request_id=None, input_hash=None, response=None):
        with self.connect() as db:
            db.execute('UPDATE sessions SET state=? WHERE id=?', (json.dumps(state, ensure_ascii=False), session))
            if state['order_id']:
                db.execute('INSERT OR IGNORE INTO orders VALUES (?, ?, ?)', (session, state['order_id'], json.dumps(state, ensure_ascii=False)))
            if request_id:
                db.execute('INSERT INTO turns VALUES (?, ?, ?, ?)', (session, request_id, input_hash, json.dumps(response, ensure_ascii=False)))
