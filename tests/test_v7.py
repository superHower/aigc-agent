import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from backend.db.operations import bootstrap_admin
from backend.db.task_store import TaskStore
from backend.main import app, task_credit_summary
from backend.services import credits, subscriptions
from tests.test_v4_credits import create


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / 'v7.db')
    bootstrap_admin(store, 'admin', 'test-password-123', 'admin@example.com')
    monkeypatch.setattr(app.state, 'store', store, raising=False)
    monkeypatch.setattr(app.state, 'settings', SimpleNamespace(data_dir=tmp_path), raising=False)
    admin = TestClient(app)
    assert admin.post('/api/auth/login', json={'account': 'admin@example.com', 'password': 'test-password-123'}).status_code == 200
    admin.headers['X-CSRF-Token'] = admin.cookies['csrf']
    user = TestClient(app)
    payload = {'username': 'tester', 'email': 'User@Example.com', 'password': 'password-123', 'confirm': 'password-123'}
    result = user.post('/api/auth/register', json=payload)
    assert result.status_code == 201, result.text
    ident = result.json()['id']
    # Service tests share the historical helper's user id.
    with store.transaction() as db:
        db.execute("INSERT INTO users (id,username,email,password_hash,role,created_at) SELECT 'user','ledger_user','ledger@example.com',password_hash,role,created_at FROM users WHERE id=?", (ident,))
    assert user.post('/api/auth/login', json={'account': 'user@example.com', 'password': 'password-123'}).status_code == 200
    user.headers['X-CSRF-Token'] = user.cookies['csrf']
    return store, admin, user, ident


def test_email_auth_and_password_revocation(setup):
    store, admin, user, ident = setup
    anon = TestClient(app)
    assert anon.post('/api/auth/login', json={'account': 'tester', 'password': 'password-123'}).status_code == 401
    payload = {'username': 'another', 'email': 'USER@example.com', 'password': 'password-123', 'confirm': 'password-123'}
    assert anon.post('/api/auth/register', json=payload).status_code == 409
    assert anon.post('/api/auth/register', json=payload | {'email': 'new@example.com', 'confirm': 'different'}).status_code == 422
    assert anon.post('/api/auth/register', json=payload | {'email': 'invalid'}).status_code == 422
    reset = {'email': 'user@example.com', 'old_password': 'bad', 'password': 'new-password-123', 'confirm': 'new-password-123'}
    assert anon.post('/api/auth/reset-password', json=reset).status_code == 401
    assert anon.post('/api/auth/reset-password', json=reset | {'old_password': 'password-123'}).status_code == 200
    assert user.get('/api/auth/me').status_code == 401
    assert user.post('/api/auth/login', json={'account': 'USER@example.com', 'password': 'new-password-123'}).status_code == 200
    assert credits.balance(store, ident)['available'] == 0


def test_manual_recharge_membership_and_service_image(setup):
    store, admin, user, ident = setup
    headers = {'Idempotency-Key': 'recharge-test-key'}
    url = f'/api/admin/users/{ident}/credit-adjustments'
    assert user.post(url, json={'amount': 100}, headers=headers).status_code == 403
    assert admin.post(url, json={'amount': 100}, headers=headers).status_code == 200
    assert admin.post(url, json={'amount': 100}, headers=headers).status_code == 200
    assert admin.post(url, json={'amount': 200}, headers=headers).status_code == 409
    assert credits.balance(store, ident)['available'] == 100
    membership = f'/api/admin/users/{ident}/membership'
    assert admin.post(membership, json={'plan_id': 'weekly'}, headers={'Idempotency-Key': 'membership-test-key'}).status_code == 200
    assert admin.post(membership, json={'plan_id': 'weekly'}, headers={'Idempotency-Key': 'membership-test-key'}).status_code == 200
    assert credits.balance(store, ident)['available'] == 4100
    result = admin.get('/api/admin/users', params={'email': 'USER@example.com'}).json()
    assert result['total'] == 1 and result['items'][0]['id'] == ident
    image = io.BytesIO(); Image.new('RGB', (50, 50)).save(image, 'PNG')
    result = admin.post('/api/admin/customer-service', files={'file': ('wechat.png', image.getvalue(), 'image/png')})
    assert result.status_code == 201, result.text
    assert user.get(result.json()['url']).status_code == 200
    assert user.get('/api/recharge').json()['current_plan']['cost'] == 16
    for path in ['/api/orders', '/api/admin/orders', '/api/admin/payment-codes', '/api/auth/captcha']:
        assert admin.get(path).status_code == 410


def test_multilot_freeze_release_and_member_expiry(setup):
    store, _, _, _ = setup
    with store.transaction() as db:
        credits.begin(db)
        credits.grant(db, 'user', 10, 'paid', 'first')
        credits.grant(db, 'user', 100, 'paid', 'second')
    create(store, 'ordinary', 1)
    assert task_credit_summary(store, 'ordinary') == {'frozen': 20}
    assert credits.balance(store, 'user')['available'] == 90
    store.update_job('ordinary_0', status='failed')
    store.finalize_task('ordinary')
    assert credits.balance(store, 'user')['available'] == 110
    with store.transaction() as db:
        credits.begin(db)
        subscriptions.assign(db, 'user', 'weekly')
    create(store, 'member', 1)
    assert task_credit_summary(store, 'member') == {'frozen': 16}
    with store.transaction() as db:
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        db.execute('UPDATE subscriptions SET expires_at=?', (past,))
        db.execute('UPDATE membership_periods SET expires_at=?', (past,))
        db.execute("UPDATE credit_lots SET expires_at=? WHERE source='membership'", (past,))
    store.update_job('member_0', status='failed')
    store.finalize_task('member')
    assert credits.balance(store, 'user')['available'] == 110
    assert not credits.audit_balances(store)


def test_quarterly_periods_quota_and_snapshot(setup):
    store, _, _, _ = setup
    with store.transaction() as db:
        credits.begin(db)
        subscriptions.assign(db, 'user', 'quarterly')
        sub = subscriptions.current(db, 'user')
        periods = db.execute('SELECT * FROM membership_periods WHERE subscription_id=? ORDER BY starts_at', (sub['id'],)).fetchall()
        assert len(periods) == 1
        assert sum(p['lot_id'] is not None for p in periods) == 1
        db.execute("UPDATE membership_plans SET cost=99 WHERE id='quarterly'")
        assert subscriptions.pricing(db, 'user', 1)[0] == 8
        assert subscriptions.pricing(db, 'user', 2001)[0] == 8
    assert credits.balance(store, 'user')['available'] == 48000


def test_concurrent_reservations_idempotency_and_retries(setup):
    store, _, _, _ = setup
    with store.transaction() as db:
        credits.begin(db)
        credits.grant(db, 'user', 40, 'paid', 'concurrent')
    def submit(name):
        try:
            return create(store, name, 2)
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ['one', 'two']))
    assert sum(isinstance(r, tuple) for r in results) == 1
    assert 402 in results
    task_id = next(r[0] for r in results if isinstance(r, tuple))
    assert create(store, 'duplicate', 2, task_id) == (task_id, False)
    store.update_job(task_id + '_0', status='done', output_path='unused')
    store.update_job(task_id + '_1', status='failed')
    store.finalize_task(task_id)
    assert credits.balance(store, 'user')['available'] == 20
    assert credits.retry(store, 'user', task_id, None, 'retry-key')
    assert not credits.retry(store, 'user', task_id, None, 'retry-key')
    assert credits.balance(store, 'user')['frozen'] == 20
    store.request_cancel(task_id)
    store.update_job(task_id + '_1', status='cancelled')
    store.finalize_task(task_id)
    assert credits.balance(store, 'user')['available'] == 20
    assert not credits.audit_balances(store)


def test_period_rollover_and_switch_preserve_general_credits(setup, monkeypatch):
    store, _, _, _ = setup
    with store.transaction() as db:
        credits.begin(db)
        credits.grant(db, 'user', 100, 'paid', 'general')
        subscriptions.assign(db, 'user', 'quarterly')
        sub = subscriptions.current(db, 'user')
        periods = db.execute('SELECT * FROM membership_periods WHERE subscription_id=? ORDER BY starts_at', (sub['id'],)).fetchall()
    now = (datetime.fromisoformat(periods[0]['starts_at']) + timedelta(days=32)).isoformat()
    monkeypatch.setattr(subscriptions, 'utc_now', lambda: now)
    monkeypatch.setattr(credits, 'utc_now', lambda: now)
    assert credits.balance(store, 'user')['available'] == 48100
    assert credits.balance(store, 'user')['available'] == 48100
    with store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM credit_lots WHERE source='membership'").fetchone()[0] == 1
        credits.begin(db)
        # Return to the actual clock for the immediate plan change.
        monkeypatch.undo()
        subscriptions.assign(db, 'user', 'ordinary')
    assert credits.balance(store, 'user')['available'] == 100
    assert not credits.audit_balances(store)


def test_daily_risk_and_refund_quote(setup):
    store, admin, user, ident = setup
    settings = {'daily_limit': 16, 'concurrency': 2, 'retry_limit': 1}
    assert user.put('/api/admin/risk-settings', json=settings).status_code == 403
    assert admin.put('/api/admin/risk-settings', json=settings).status_code == 200
    assert admin.get('/api/admin/risk-settings').json() == settings
    with store.transaction() as db:
        credits.begin(db)
        subscriptions.assign(db, 'user', 'weekly')
        sub = subscriptions.current(db, 'user')
        assert subscriptions.refund_quote(db, sub['id']) == 5990
    create(store, 'risk', 1)
    with pytest.raises(HTTPException):
        create(store, 'exceeds-risk', 1)
    store.update_job('risk_0', status='done', output_path='unused')
    with store.transaction() as db:
        assert subscriptions.refund_quote(db, sub['id']) == 5990 * (4000 - 16) // 4000
    with pytest.raises(HTTPException):
        create(store, 'settled-risk', 1)
    assert 'image_limit' not in user.get('/api/recharge').json()['plans'][0]

