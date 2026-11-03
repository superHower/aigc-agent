from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from backend.services import credits, newcomer, subscriptions
from tests.test_v7 import setup


def test_registration_and_offer_lifetime(setup):
    store, admin, user, ident = setup
    assert credits.balance(store, ident)['available'] == 500
    assert user.get('/api/recharge').json()['newcomer_offer']['eligible']
    assert not admin.get('/api/recharge').json()['newcomer_offer']['eligible']
    assert user.post('/api/recharge/newcomer/reserve').status_code == 200
    with store.transaction() as db:
        past = (datetime.now(timezone.utc) - timedelta(hours=24, seconds=1)).isoformat()
        db.execute('UPDATE users SET created_at=? WHERE id=?', (past, ident))
    assert not user.get('/api/recharge').json()['newcomer_offer']['eligible']
    assert user.post('/api/recharge/newcomer/reserve').status_code == 409


def test_activation_snapshot_expiration_and_once_only(setup):
    store, admin, user, ident = setup
    def reserve(_):
        with store.transaction() as db:
            credits.begin(db)
            return newcomer.reserve(db, ident)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(r['reserved'] for r in pool.map(reserve, range(2)))
    with store.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM newcomer_plan_claims').fetchone()[0] == 1
        db.execute("UPDATE membership_plans SET cost=99,credits=1,duration_hours=1 WHERE id='newcomer'")
    url = f'/api/admin/users/{ident}/membership'
    headers = {'Idempotency-Key': 'newcomer-activation'}
    assert user.post(url, json={'plan_id': 'newcomer'}, headers=headers).status_code == 403
    assert admin.post(url, json={'plan_id': 'newcomer'}, headers=headers).status_code == 200
    assert admin.post(url, json={'plan_id': 'newcomer'}, headers=headers).status_code == 200
    assert credits.balance(store, ident)['available'] == 1700
    with store.transaction() as db:
        credits.begin(db)
        sub = subscriptions.current(db, ident)
        assert subscriptions.pricing(db, ident, 1)[0] == 12
        assert datetime.fromisoformat(sub['expires_at']) - datetime.fromisoformat(sub['starts_at']) == timedelta(hours=72)
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        db.execute('UPDATE subscriptions SET expires_at=? WHERE user_id=?', (past, ident))
        db.execute('UPDATE membership_periods SET expires_at=? WHERE subscription_id=?', (past, sub['id']))
        db.execute("UPDATE credit_lots SET expires_at=? WHERE user_id=? AND source='membership'", (past, ident))
    assert credits.balance(store, ident)['available'] == 500
    with store.transaction() as db:
        assert subscriptions.pricing(db, ident, 1)[0] == 25
    assert admin.post(url, json={'plan_id': 'newcomer'}, headers={'Idempotency-Key': 'second-activation'}).status_code == 409
    assert user.post('/api/recharge/newcomer/reserve').status_code == 409
    assert not credits.audit_balances(store)


@pytest.mark.parametrize('existing', ['paid', 'membership'])
def test_first_purchase_enforced_even_after_reservation(setup, existing):
    store, _, user, ident = setup
    assert user.post('/api/recharge/newcomer/reserve').status_code == 200
    with store.transaction() as db:
        credits.begin(db)
        if existing == 'paid':
            credits.grant(db, ident, 100, 'adjustment', 'paid-first')
        else:
            subscriptions.assign(db, ident, 'weekly')
    assert user.post('/api/recharge/newcomer/reserve').status_code == 409
    with store.transaction() as db:
        credits.begin(db)
        with pytest.raises(HTTPException):
            subscriptions.assign(db, ident, 'newcomer')


def test_backend_configuration_and_permissions(setup):
    _, admin, user, _ = setup
    plan = next(p for p in admin.get('/api/admin/membership-plans').json()['items'] if p['id'] == 'newcomer')
    assert (plan['price_cents'], plan['credits'], plan['cost'], plan['duration_hours']) == (1500, 1200, 12, 72)
    payload = {k: v for k, v in plan.items() if k != 'id'}
    assert user.put('/api/admin/membership-plans/newcomer', json=payload).status_code == 403
    assert admin.put('/api/admin/membership-plans/newcomer', json=payload | {'duration_hours': 0}).status_code == 422
    assert admin.put('/api/admin/membership-plans/newcomer', json=payload | {'duration_hours': 48}).status_code == 200
    assert user.get('/api/recharge').json()['newcomer_offer']['plan']['duration_hours'] == 48
