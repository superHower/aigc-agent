"""Small DB-API boundary shared by SQLite development and PostgreSQL deployments."""
from __future__ import annotations

import re
import sqlite3


class Record(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowcount = cursor.rowcount

    def _row(self, row):
        return Record(row) if row is not None else None

    def fetchone(self):
        return self._row(self.cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    def __init__(self, raw, postgres=False):
        self.raw, self.postgres = raw, postgres

    def execute(self, sql, parameters=()):
        if self.postgres:
            parameters = tuple(int(v) if isinstance(v, bool) else v for v in parameters)
            sql = sql.replace('BEGIN IMMEDIATE', 'BEGIN').replace('rowid', 'id')
            sql = re.sub(r'julianday\(([^)]+)\)', r'CAST(\1 AS TIMESTAMPTZ)', sql)
            sql = sql.replace("SUM(j.status = 'done')", "SUM(CASE WHEN j.status = 'done' THEN 1 ELSE 0 END)")
            sql = sql.replace("SUM(j.status = 'failed')", "SUM(CASE WHEN j.status = 'failed' THEN 1 ELSE 0 END)")
            sql = sql.replace('instr(lower(name), lower(?)) > 0', 'position(lower(?) in lower(name)) > 0')
            sql = sql.replace('instr(lower(content), lower(?)) > 0', 'position(lower(?) in lower(content)) > 0')
            # Escape literal percent signs for psycopg, then replace bind markers.
            sql = sql.replace('%', '%%').replace('?', '%s')
        try:
            cursor = self.raw.execute(sql, parameters)
            return Cursor(cursor) if self.postgres else cursor
        except Exception as exc:
            if self.postgres:
                import psycopg
                if isinstance(exc, psycopg.IntegrityError):
                    raise sqlite3.IntegrityError(str(exc)) from exc
                if isinstance(exc, psycopg.OperationalError):
                    raise sqlite3.OperationalError(str(exc)) from exc
            raise

    def executescript(self, sql):
        # Unlike sqlite3.executescript, never implicitly commit the caller's transaction.
        for statement in sql.split(';'):
            if statement.strip():
                self.execute(statement)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        try:
            self.raw.rollback() if kind else self.raw.commit()
        finally:
            self.raw.close()


def connect(url):
    if str(url).startswith(('postgresql://', 'postgres://')):
        import psycopg
        from psycopg.rows import dict_row
        return Connection(psycopg.connect(url, row_factory=dict_row), True)
    raw = sqlite3.connect(url, timeout=30)
    raw.row_factory = sqlite3.Row
    raw.execute('PRAGMA foreign_keys = ON')
    return Connection(raw)
