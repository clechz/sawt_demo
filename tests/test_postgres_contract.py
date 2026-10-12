"""Run the SAME transaction tests against isolated schemas in real Postgres.

SAWT_TEST_DATABASE_URL enables these paid/network integration tests explicitly.
"""
import os
import uuid
from pathlib import Path
import pytest
from sawt.domain import Engine, Menu
from sawt.transactions import Transactions

if not os.getenv('SAWT_TEST_DATABASE_URL'):
    pytest.skip('Set SAWT_TEST_DATABASE_URL for real Postgres integration tests', allow_module_level=True)

from test_transactions import *  # noqa: F403; deliberately reuse the contract suite


@pytest.fixture
def tx():
    import psycopg
    from psycopg import sql
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, quote
    url = os.environ['SAWT_TEST_DATABASE_URL']
    if '-pooler.' in (urlsplit(url).hostname or ''):
        pytest.fail('Schema-isolated tests need the unpooled database URL; the Neon transaction pooler rejects search_path at startup.')
    schema = 'test_' + uuid.uuid4().hex
    with psycopg.connect(url) as db:
        db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query)); query['options'] = '-c search_path='+schema
    scoped = urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query,quote_via=quote),''))
    transaction = None
    try:
        transaction = Transactions(scoped, Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv')))
        yield transaction
    finally:
        if transaction is not None:transaction.postgres.pool.close()
        with psycopg.connect(url) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def test_idle_closed_connection_is_replaced_before_creating_a_call(tx):
    # Close only this isolated test pool's own client socket while it is idle.
    # No production backend/session is terminated and no mutation is replayed.
    with tx.connect() as db:
        stale=db.connection
        db.execute('SELECT 1')
    stale.close()
    sid,token=tx.create()
    assert tx.load(sid)['state']['basket']==[]
    with tx.connect() as db:
        assert db.connection is not stale
        assert db.execute('SELECT count(*) FROM calls').fetchone()[0]==1
