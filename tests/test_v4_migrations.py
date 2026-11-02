import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.db.operations import backup, bootstrap_admin, import_sqlite, restore, validate
from backend.db.task_store import TaskStore, utc_now
from backend.services.channels import ChannelStore, ChannelInput
from backend.services.dashboard import dashboard_stats
from backend.services.passwords import verify_password


def legacy_database(path):
    with sqlite3.connect(path) as db:
        db.executescript(Path('backend/db/baseline.sql').read_text(encoding='utf-8'))
        db.execute('INSERT INTO files VALUES (?,?,?,?,?,?,?,?)', ('source', 'old.png', 'missing.png', 'image/png', 1, 1, 1, utc_now()))
        db.execute('INSERT INTO analyses VALUES (?,?,?)', ('source', '{}', utc_now()))
        db.execute('INSERT INTO prompt_categories VALUES (?,?,?)', ('cat', 'old', utc_now()))
        db.execute('INSERT INTO prompt_templates VALUES (?,?,?,?,?,?)', ('tpl', 'old', 'content', 'cat', utc_now(), utc_now()))


def test_upgrade_old_database_and_one_time_admin(tmp_path):
    path = tmp_path / 'old.db'
    legacy_database(path)
    store = TaskStore(path)
    owner = bootstrap_admin(store, 'Admin', 'test-password-123')
    TaskStore(path)
    assert validate(store)['ok']
    with store.transaction() as db:
        assert [r[0] for r in db.execute('SELECT version FROM schema_migrations ORDER BY version')] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
        assert db.execute('SELECT owner_id FROM analyses').fetchone()[0] == owner
        encoded = db.execute('SELECT password_hash FROM users').fetchone()[0]
        assert verify_password('test-password-123', encoded)
        assert not verify_password('wrong', encoded)
    with pytest.raises(ValueError, match='已初始化'):
        bootstrap_admin(store, 'other', 'test-password-456')
    assert not validate(store, tmp_path)['ok']


def test_transaction_rolls_back_and_bootstrap_refuses_active_tasks(tmp_path):
    store = TaskStore(tmp_path / 'test.db')
    with pytest.raises(RuntimeError):
        with store.transaction() as db:
            db.execute("INSERT INTO system_settings VALUES ('test','value')")
            raise RuntimeError()
    with store.transaction() as db:
        assert db.execute("SELECT * FROM system_settings WHERE key='test'").fetchone() is None
        db.execute('INSERT INTO tasks (id,created_at,updated_at,source_ids,edit_rule) VALUES (?,?,?,?,?)', ('task', utc_now(), utc_now(), '[]', '{}'))
    with pytest.raises(ValueError, match='活动任务'):
        bootstrap_admin(store, 'admin', 'test-password-123', 'admin@example.com')
    with store.transaction() as db:
        assert db.execute('SELECT * FROM users').fetchone() is None


def test_backup_restore_and_tamper_detection(tmp_path):
    path = tmp_path / 'old.db'
    legacy_database(path)
    media = tmp_path / 'media'
    media.mkdir()
    (media / 'old.png').write_bytes(b'original')
    with sqlite3.connect(path) as db:
        db.execute('UPDATE files SET path=?', (str(media / 'old.png'),))
    snapshot = tmp_path / 'snapshot'
    backup(path, media, snapshot)
    # Backup does not migrate or otherwise change the source schema.
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone() is None
    restore(snapshot, tmp_path / 'restored.db', tmp_path / 'restored-media')
    assert (tmp_path / 'restored-media/old.png').read_bytes() == b'original'
    with sqlite3.connect(tmp_path / 'restored.db') as db:
        assert db.execute('SELECT path FROM files').fetchone()[0] == str(tmp_path / 'restored-media/old.png')
    with pytest.raises(ValueError, match='目标必须不存在'):
        restore(snapshot, path, media)
    (snapshot / 'media/old.png').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='校验失败'):
        restore(snapshot, tmp_path / 'bad.db', tmp_path / 'bad-media')
    assert not (tmp_path / 'bad.db').exists()


def test_business_routes_require_admin_session_and_csrf(tmp_path, monkeypatch):
    from backend.main import app
    store = TaskStore(tmp_path / 'auth.db')
    bootstrap_admin(store, 'admin', 'test-password-123', 'admin@example.com')
    monkeypatch.setattr(app.state, 'store', store, raising=False)
    monkeypatch.setattr(app.state, 'login_attempts', {}, raising=False)
    client = TestClient(app)
    assert client.get('/api/health').json() == {'status': 'ok'}
    for url in ('/api/tasks', '/api/files/secret.png', '/api/channels', '/api/dashboard'):
        assert client.get(url).status_code == 401
    assert client.post('/api/auth/login', json={'account': 'admin@example.com', 'password': 'test-password-123'}, headers={'origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/auth/login', json={'account': 'admin@example.com', 'password': 'test-password-123'}).status_code == 200
    assert client.get('/api/auth/me').json()['username'] == 'admin'
    assert client.post('/api/auth/logout').status_code == 403
    client.headers['X-CSRF-Token'] = client.cookies['csrf']
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/auth/me').status_code == 401


@pytest.fixture
def postgres_store():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to run PostgreSQL acceptance tests')
    import psycopg
    schema = 'test_' + uuid4().hex
    with psycopg.connect(url, autocommit=True) as db:
        db.execute(f'CREATE SCHEMA {schema}')
    # TaskStore selects its dialect from the URI; append encoded options instead.
    from urllib.parse import quote
    scoped = url + ('&' if '?' in url else '?') + 'options=' + quote(f'-c search_path={schema}')
    try:
        yield TaskStore(scoped)
    finally:
        with psycopg.connect(url, autocommit=True) as db:
            db.execute(f'DROP SCHEMA {schema} CASCADE')


def test_postgres_migration_import_transactions_and_existing_queries(postgres_store, tmp_path):
    source = tmp_path / 'legacy.db'
    legacy_database(source)
    old = TaskStore(source)
    bootstrap_admin(old, 'admin', 'test-password-123')
    with old.transaction() as db:
        db.execute("UPDATE packages SET price_cents=800,status='active',updated_at=? WHERE id='credits30'", (utc_now(),))
    channels = ChannelStore(old)
    channels.save(ChannelInput(name='local', model='model', base_url='http://localhost:9999', api_key='test-key'))
    ChannelStore(postgres_store)
    import_sqlite(source, postgres_store)
    import_sqlite(source, postgres_store)
    assert validate(postgres_store)['ok']
    with postgres_store.transaction() as db:
        assert db.execute("SELECT price_cents FROM packages WHERE id='credits30'").fetchone()[0] == 800
    assert ChannelStore(postgres_store).list()[0]['name'] == 'local'
    assert dashboard_stats(postgres_store, 'day', date.today(), 0)['summary']['tasks'] == 0
    from fastapi import FastAPI
    from backend.routes.prompts import router
    prompt_app = FastAPI()
    prompt_app.include_router(router)
    prompt_app.state.store = postgres_store
    @prompt_app.middleware("http")
    async def admin_context(request, call_next):
        with postgres_store.transaction() as db:
            request.state.user = dict(db.execute("SELECT * FROM users WHERE role='admin'").fetchone())
        return await call_next(request)
    client = TestClient(prompt_app)
    assert client.get('/api/prompt-templates', params={'q': 'content'}).json()['items'][0]['id'] == 'tpl'
    assert client.post('/api/prompt-categories', json={'name': 'new'}).status_code == 201
    assert client.post('/api/prompt-categories', json={'name': 'new'}).status_code == 409
    config = ChannelStore(postgres_store).list()[0]
    ChannelStore(postgres_store).save(ChannelInput(name='updated', model='model', base_url='http://localhost:9999', enabled=False), config['id'])
    assert not ChannelStore(postgres_store).list()[0]['enabled']
    postgres_store.create_batch('task', ['source'], {}, [dict(id='job', source_id='source', step='generate', prompt='test', mask_path=None, input_path='missing.png')])
    assert postgres_store.get_pending_jobs('task')[0]['id'] == 'job'
    postgres_store.update_job('job', status='done', output_path='old-output.png')
    assert postgres_store.finalize_task('task') == 'completed'
    assert postgres_store.get_job_by_output_name('old-output.png')['id'] == 'job'
    stats = dashboard_stats(postgres_store, 'day', date.today(), 0)
    assert stats['summary']['done'] == 1
    with pytest.raises(RuntimeError):
        with postgres_store.transaction() as db:
            db.execute("INSERT INTO system_settings VALUES ('rollback','value')")
            raise RuntimeError()
    with postgres_store.transaction() as db:
        assert db.execute('SELECT * FROM system_settings').fetchone() is None
        db.execute("UPDATE users SET username='changed'")
    with pytest.raises(ValueError, match='校验失败'):
        import_sqlite(source, postgres_store)


def test_postgres_parallel_bootstrap_creates_only_one_admin(postgres_store):
    def create(index):
        try:
            return bootstrap_admin(postgres_store, f'admin{index}', 'test-password-123')
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, range(2)))
    assert sum(result is not None for result in results) == 1
