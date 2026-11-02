import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.db.operations import bootstrap_admin
from backend.db.task_store import TaskStore, utc_now
from backend.main import app
from backend.services import identity, captcha
from backend.services.analyzer import Analyzer
from tests.test_v4_migrations import postgres_store


@pytest.fixture(params=['sqlite', 'postgres'])
def identity_app(tmp_path, monkeypatch, request):
    store = request.getfixturevalue('postgres_store') if request.param == 'postgres' else TaskStore(tmp_path / 'identity.db')
    admin_id = bootstrap_admin(store, 'admin', 'test-password-123', 'admin@example.com')
    for directory in ('source', 'masks'):
        (tmp_path / directory).mkdir()
    monkeypatch.setattr(app.state, 'store', store, raising=False)
    monkeypatch.setattr(app.state, 'settings', SimpleNamespace(data_dir=tmp_path, max_concurrency=3), raising=False)
    analyzer = Analyzer(store, tmp_path, SimpleNamespace(detect=lambda path: []))
    monkeypatch.setattr(app.state, 'analyzer', analyzer, raising=False)
    codes = {}
    monkeypatch.setattr(identity, 'send_sms', lambda number, purpose, code, challenge: codes.update({(number, purpose): code}))
    original_issue = captcha.issue
    def issue(store, ip):
        result = original_issue(store, ip)
        with store.transaction() as db:
            db.execute('UPDATE captcha_challenges SET code_hash=? WHERE id=?', (identity.keyed(identity.secret(db), result['captcha_id'] + ':AB234'), result['captcha_id']))
        return result
    monkeypatch.setattr(captcha, 'issue', issue)
    return store, codes, admin_id


def signup(codes, number, name):
    client = TestClient(app)
    response = client.post('/api/auth/register', json={'username': name, 'email': number + '@example.com', 'password': 'password-123', 'confirm': 'password-123'})
    assert response.status_code == 201, response.text
    assert client.post('/api/auth/login', json={'account': number + '@example.com', 'password': 'password-123'}).status_code == 200
    client.headers['X-CSRF-Token'] = client.cookies['csrf']
    return client, response.json()['id']


def image_upload(client, name='image.png'):
    stream = io.BytesIO()
    Image.new('RGB', (20, 10), 'red').save(stream, format='PNG')
    response = client.post('/api/upload', files={'files': (name, stream.getvalue(), 'image/png')})
    assert response.status_code == 200, response.text
    return response.json()['files'][0]['file_id']


def test_admin_reset_revokes_sessions_and_audits(identity_app):
    store, codes, _ = identity_app
    user, user_id = signup(codes, '13800000002', 'user_a')
    assert user.post(f'/api/admin/users/{user_id}/reset-password', json={'password': 'new-password-123', 'reason': 'verified'}).status_code == 403
    admin = TestClient(app)
    assert admin.post('/api/auth/login', json={'account': 'admin@example.com', 'password': 'test-password-123'}).status_code == 200
    admin.headers['X-CSRF-Token'] = admin.cookies['csrf']
    assert admin.post(f'/api/admin/users/{user_id}/reset-password', json={'password': 'new-password-123', 'reason': 'verified'}).status_code == 200
    assert user.get('/api/auth/me').status_code == 401
    assert user.post('/api/auth/login', json={'account': '13800000002@example.com', 'password': 'password-123'}).status_code == 401
    assert user.post('/api/auth/login', json={'account': '13800000002@example.com', 'password': 'new-password-123'}).status_code == 200
    with store.transaction() as db:
        audit = db.execute("SELECT details FROM audit_logs WHERE action='user_password_reset'").fetchone()
        assert audit and 'password' not in audit[0]


def test_two_users_isolated_across_files_jobs_zip_ocr_templates_dashboard(identity_app, tmp_path):
    store, codes, _ = identity_app
    alice, alice_id = signup(codes, '13800000003', 'alice')
    bob, bob_id = signup(codes, '13800000004', 'bobby')
    source = image_upload(alice)
    bob_source = image_upload(bob)
    result = alice.post('/api/analyze', json={'file_ids': [source]})
    assert result.status_code == 200
    thumb = result.json()['files'][0]['thumbnail_url']
    assert bob.get(thumb).status_code == 404
    assert bob.get(f'/api/files/{source}').status_code == 404
    assert bob.post('/api/analyze', json={'file_ids': [bob_source, source]}).status_code == 404
    assert bob.post('/api/composite', json={'image_ids': [bob_source, source]}).status_code == 404
    store.create_batch('alice_task', [source], {}, [dict(id='alice_job', source_id=source, step='custom_1', prompt='private', mask_path=None, input_path=str(tmp_path/'source.png'))])
    with store.transaction() as db:
        db.execute('UPDATE tasks SET owner_id=? WHERE id=?', (alice_id, 'alice_task'))
    output = tmp_path / 'private-output.png'
    Image.new('RGB', (10, 10)).save(output)
    store.update_job('alice_job', status='done', output_path=str(output), error='SECRET CHANNEL URL KEY')
    store.finalize_task('alice_task')
    for url in ('/api/task/alice_task', '/api/task/alice_task/download', '/api/files/alice_job', '/api/files/private-output.png'):
        assert bob.get(url).status_code == 404
        assert alice.get(url).status_code == 200
    assert bob.post('/api/task/alice_task/cancel').status_code == 404
    assert bob.post('/api/task/alice_task/retry', json={}).status_code == 404
    assert bob.get('/api/tasks').json()['items'] == []
    assert 'SECRET CHANNEL' not in alice.get('/api/task/alice_task').text
    assert bob.get('/api/dashboard').json()['summary']['tasks'] == 0
    assert alice.get('/api/dashboard').json()['summary']['tasks'] == 1
    assert alice.get('/api/dashboard').json()['channels'] == []
    for url in ('/api/channels', '/api/admin/users'):
        assert bob.get(url).status_code == 403
    for url in ('/api/generate/batch', '/api/task/create', '/api/edit/advanced'):
        assert bob.post(url, json={}).status_code == 403
    cat_a = alice.post('/api/prompt-categories', json={'name': '同名'}).json()
    assert bob.post('/api/prompt-categories', json={'name': '同名'}).status_code == 201
    template = alice.post('/api/prompt-templates', json={'name': 'private', 'content': 'secret', 'category_id': cat_a['id']}).json()
    assert bob.get('/api/prompt-templates').json()['items'] == []
    assert bob.get('/api/prompt-templates/'+template['id']).status_code == 404
    assert bob.delete('/api/prompt-categories/'+cat_a['id']).status_code == 404
    assert bob.post('/api/prompt-templates', json={'name': 'hack', 'content': 'hack', 'category_id': cat_a['id']}).status_code == 404
    assert bob.post('/api/prompt-templates', json={'name': 'hack', 'content': 'hack', 'visibility': 'public'}).status_code == 403
    admin = TestClient(app)
    assert admin.post('/api/auth/login', json={'account': 'admin@example.com', 'password': 'test-password-123'}).status_code == 200
    admin.headers['X-CSRF-Token'] = admin.cookies['csrf']
    public_category = admin.post('/api/prompt-categories', json={'name': '公共', 'visibility': 'public'}).json()
    public_template = admin.post('/api/prompt-templates', json={'name': 'public', 'content': 'shared', 'visibility': 'public', 'category_id': public_category['id']}).json()
    assert bob.get('/api/prompt-templates/'+public_template['id']).status_code == 200
    assert bob.put('/api/prompt-templates/'+public_template['id'], json={'name': 'hack', 'content': 'hack'}).status_code == 404
    assert bob.delete('/api/prompt-categories/'+public_category['id']).status_code == 404
    assert admin.put('/api/prompt-categories/'+public_category['id'], json={'name': 'private'}).status_code == 409


def test_login_throttle_and_no_password_echo(identity_app):
    _, codes, _ = identity_app
    user, _ = signup(codes, '13800000007', 'limited')
    for _ in range(10):
        assert user.post('/api/auth/login', json={'account': 'limited', 'password': 'incorrect'}).status_code == 401
    assert user.post('/api/auth/login', json={'account': 'limited', 'password': 'password-123'}).status_code == 429
    invalid = user.post('/api/auth/register', json={'username': '12', 'password': 'secret-input', 'phone': 'invalid', 'code': '123'})
    assert invalid.status_code == 422 and 'secret-input' not in invalid.text


def test_concurrent_registration_and_failed_sms(identity_app, monkeypatch):
    store, codes, _ = identity_app
    identity.issue_sms(store, '13800000005', 'register', 'local')
    def register(_):
        try:
            return identity.register(store, 'concurrent', '13800000005', 'password-123', codes[('13800000005', 'register')])
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(value is not None for value in pool.map(register, range(2))) == 1
    def unavailable(*args):
        raise RuntimeError('secret gateway address')
    monkeypatch.setattr(identity, 'send_sms', unavailable)
    response = TestClient(app).post('/api/auth/sms', json={'phone': '13800000006', 'purpose': 'register'})
    assert response.status_code == 410 and 'secret' not in response.text
