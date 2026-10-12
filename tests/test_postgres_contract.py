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
    schema = 'test_' + uuid.uuid4().hex
    with psycopg.connect(url) as db:
        db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query)); query['options'] = '-c search_path='+schema
    scoped = urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query,quote_via=quote),''))
    transaction = Transactions(scoped, Engine(Menu(Path(__file__).resolve().parents[1]/'data/restaurant-menu-complex.csv')))
    try:
        yield transaction
    finally:
        transaction.postgres.pool.close()
        with psycopg.connect(url) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
