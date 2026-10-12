"""Small DB-API bridge for the existing, tested transaction boundary.

Business writers take one transaction-scoped advisory lock, matching SQLite's
single-writer semantics. No network/model work runs inside that transaction.
This deliberately favors correctness over write throughput for the demo.
"""
from contextlib import contextmanager
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        return Row(row) if row is not None else None

    def fetchall(self):
        return [Row(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return (Row(row) for row in self.cursor)


class Connection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters=()):
        if sql.strip().upper() == 'BEGIN IMMEDIATE':
            # All API and worker instances share this lock in the same database.
            return Cursor(self.connection.execute('SELECT pg_advisory_xact_lock(731984201)'))
        return Cursor(self.connection.execute(sql.replace('?', '%s'), parameters))

    def executemany(self, sql, parameters):
        cursor = self.connection.cursor()
        cursor.executemany(sql.replace('?', '%s'), parameters)
        return Cursor(cursor)

    def executescript(self, script):
        self.execute('BEGIN IMMEDIATE')
        for sql in script.split(';'):
            sql = sql.strip()
            if not sql or sql.startswith('PRAGMA'):
                continue
            sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'BIGSERIAL PRIMARY KEY')
            sql = sql.replace(' REAL', ' DOUBLE PRECISION')
            self.execute(sql)


class Database:
    def __init__(self, url):
        self.pool = ConnectionPool(url, min_size=0, max_size=5, timeout=15, open=True,
                                   kwargs={'row_factory': dict_row, 'connect_timeout': 10})

    @contextmanager
    def connect(self):
        with self.pool.connection() as connection:
            yield Connection(connection)
