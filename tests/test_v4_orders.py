import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import app
from backend.services import credits, orders
from tests.test_v4_identity import identity_app, signup
from tests.test_v4_migrations import postgres_store


def png():
    stream = io.BytesIO(); Image.new('RGB', (30, 30), 'blue').save(stream, format='PNG'); return stream.getvalue()


@pytest.fixture
def payments(identity_app):
    pytest.skip('v7 已停用二维码下单与审核流程；人工充值与会员发放见 test_v7.py')
    store, codes, admin_id = identity_app
    admin = TestClient(app)
    assert admin.post('/api/auth/login', json={'account': 'admin', 'password': 'test-password-123'}).status_code == 200
    admin.headers['X-CSRF-Token'] = admin.cookies['csrf']
    user, user_id = signup(codes, '13800000007', 'buyer')
    other, other_id = signup(codes, '13800000008', 'other_buyer')
    with store.transaction() as db:
        db.execute("UPDATE packages SET status='active' WHERE id IN ('weekly','credits30')")
    return store, admin, user, other, {'id': admin_id, 'role': 'admin'}, {'id': user_id, 'role': 'user'}


def post(client, path, payload=None, key='request-key-123'):
    return client.post(path, json=payload or {}, headers={'Idempotency-Key': key})


def code(admin):
    response = admin.post('/api/admin/payment-codes', params={'channel': 'wechat', 'instructions': '核对收款人'}, files={'file': ('code.png', png(), 'image/png')})
    assert response.status_code == 201, response.text
    ident = response.json()['id']
    assert admin.post('/api/admin/payment-codes/'+ident+'/status', json={'active': True, 'reason': '测试启用'}).status_code == 200
    return ident


def submit(user, order_id, key='evidence-key-123', asset_id=None):
    return post(user, f'/api/orders/{order_id}/evidence', {'declared_transaction': 'user-declared', 'paid_at': (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(), 'note': '说明', 'asset_id': asset_id}, key+order_id)


def verified(transaction='verified-001', amount=1200):
    return {'channel': 'wechat', 'verified_transaction': transaction, 'amount_cents': amount, 'reason': '已在收款账户核实到账'}


def test_snapshot_assets_supplement_and_visibility(payments):
    store, admin, user, other, actor, buyer = payments
    assert post(user, '/api/orders', {'package_id': 'weekly'}).status_code == 503
    first_code = code(admin)
    response = post(user, '/api/orders', {'package_id': 'weekly'})
    assert response.status_code == 201, response.text
    order = response.json(); ident = order['id']
    assert post(user, '/api/orders', {'package_id': 'weekly'}).json()['id'] == ident
    assert post(user, '/api/orders', {'package_id': 'credits30'}).status_code == 409
    with store.transaction() as db:
        db.execute("UPDATE packages SET price_cents=9999,credits=900,status='inactive' WHERE id='weekly'")
    code(admin)
    detail = user.get('/api/orders/'+ident).json()
    assert (detail['price_cents'], detail['credits'], detail['payment_code_id']) == (1200, 100, first_code)
    asset = detail['payment_code']['asset_id']
    assert user.get('/api/payment-assets/'+asset).status_code == 200
    assert other.get('/api/payment-assets/'+asset).status_code == 404
    assert other.get('/api/orders/'+ident).status_code == 404
    assert other.get('/api/orders').json()['items'] == []
    assert other.get('/api/admin/orders').status_code == 403
    evidence = user.post('/api/order-evidence-assets', files={'file': ('proof.png', png(), 'image/png')}).json()['id']
    assert other.get('/api/payment-assets/'+evidence).status_code == 404
    assert admin.get('/api/payment-assets/'+evidence).status_code == 200
    # Financial assets never enter the generic files namespace or OCR/generation reference path.
    assert user.get('/api/files/'+evidence).status_code == 404
    assert user.post('/api/analyze', json={'file_ids': [evidence]}).status_code == 404
    assert post(other, f'/api/orders/{ident}/evidence', {'declared_transaction': 'x', 'paid_at': datetime.now(timezone.utc).isoformat(), 'asset_id': evidence}).status_code == 404
    assert submit(user, ident, asset_id=evidence).status_code == 200
    assert credits.balance(store, buyer['id'])['available'] == 3
    assert post(user, f'/api/orders/{ident}/cancel').status_code == 409
    assert post(admin, f'/api/admin/orders/{ident}/needs-info', {'reason': '请补充清晰交易时间'}).status_code == 200
    assert submit(user, ident, key='supplement-key-123').status_code == 200
    detail = user.get('/api/orders/'+ident).json()
    assert len(detail['evidence']) == 2 and any(r['reason'] == '请补充清晰交易时间' for r in detail['reviews'])
    assert post(admin, f'/api/admin/orders/{ident}/verify', verified(amount=1)).status_code == 409
    assert post(admin, f'/api/admin/orders/{ident}/verify', verified()).status_code == 200
    detail = user.get('/api/orders/'+ident).json()
    assert detail['receipt']['verified_transaction'] == 'verified-001'
    assert detail['evidence'][0]['declared_transaction'] == 'user-declared'
    assert credits.balance(store, buyer['id'])['available'] == 103
    assert credits.audit_balances(store) == []


def test_parallel_review_unique_receipt_atomic_membership_and_adjustment(payments, monkeypatch):
    store, admin, user, _, actor, buyer = payments
    code(admin)
    first = post(user, '/api/orders', {'package_id': 'weekly'}, 'order-one').json()['id']
    second = post(user, '/api/orders', {'package_id': 'weekly'}, 'order-two').json()['id']
    submit(user, first); submit(user, second)
    # Crash inside benefit issuance rolls back receipt and credit issuance too.
    from backend.services import membership
    real = membership.renew
    monkeypatch.setattr(membership, 'renew', lambda *args: (_ for _ in ()).throw(RuntimeError('interrupted')))
    with pytest.raises(RuntimeError):
        orders.verify(store, actor, first, verified(), 'rollback-key')
    assert credits.balance(store, buyer['id'])['available'] == 3
    with store.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM payment_receipts').fetchone()[0] == 0
    monkeypatch.setattr(membership, 'renew', real)
    from backend.db.task_store import utc_now
    with store.transaction() as db:
        db.execute("INSERT INTO users (id,username,password_hash,role,created_at) VALUES ('second-admin','second_admin','unused','admin',?)", (utc_now(),))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda reviewer: orders.verify(store, reviewer, first, verified(), 'review-request'), [actor, {'id': 'second-admin', 'role': 'admin'}]))
    assert all(r['status'] == 'credited' for r in results)
    assert credits.balance(store, buyer['id'])['available'] == 103
    with pytest.raises(HTTPException) as error:
        orders.verify(store, actor, second, verified(), 'review-three')
    assert error.value.status_code == 409
    orders.verify(store, actor, second, verified('verified-002'), 'review-four')
    expiry = datetime.fromisoformat(membership.status(store, buyer['id'])['expires_at'])
    assert 13.99 < (expiry-datetime.now(timezone.utc)).total_seconds()/86400 <= 14
    orders.adjust(store, actor, buyer['id'], 5, '补偿', 'adjust-one')
    orders.adjust(store, actor, buyer['id'], 5, '补偿', 'adjust-one')
    orders.adjust(store, actor, buyer['id'], -4, '纠正', 'adjust-two')
    assert credits.balance(store, buyer['id'])['available'] == 204
    with pytest.raises(HTTPException):
        orders.adjust(store, actor, buyer['id'], -1000, '不能透支', 'adjust-three')
    assert credits.audit_balances(store) == []


def test_cancelled_paid_supplement_and_cross_order_receipt_race(payments):
    store, admin, user, _, actor, buyer = payments
    code(admin)
    a = post(user, '/api/orders', {'package_id': 'credits30'}, 'cancel-one').json()['id']
    assert post(user, f'/api/orders/{a}/cancel').status_code == 200
    assert submit(user, a).status_code == 409
    assert post(admin, f'/api/admin/orders/{a}/verify', verified(amount=600)).status_code == 409
    assert post(admin, f'/api/admin/orders/{a}/supplement-verify', verified(amount=600)).status_code == 200
    assert credits.balance(store, buyer['id'])['available'] == 33
    b = post(user, '/api/orders', {'package_id': 'credits30'}, 'race-one').json()['id']
    c = post(user, '/api/orders', {'package_id': 'credits30'}, 'race-two').json()['id']
    submit(user, b); submit(user, c)
    def verify_order(ident):
        try:
            return orders.verify(store, actor, ident, verified('same-transaction', 600), 'race-'+ident)['status']
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(verify_order, [b, c]))
    assert result.count('credited') == 1 and result.count(409) == 1
    assert credits.balance(store, buyer['id'])['available'] == 63


def test_financial_backup_restore_and_import(payments, tmp_path, request):
    store, admin, user, _, actor, buyer = payments
    code(admin)
    ident = post(user, '/api/orders', {'package_id': 'weekly'}).json()['id']
    assert submit(user, ident).status_code == 200
    orders.verify(store, actor, ident, verified(), 'verified-backup')
    if store.postgres:
        return
    from backend.db.operations import backup, restore, validate, import_sqlite
    from backend.db.task_store import TaskStore
    media = app.state.settings.data_dir
    # Put backup outside the media root used by this fixture.
    destination = tmp_path.parent / ('orders-backup-'+buyer['id'])
    backup(store.database_path, media, destination)
    restored_media = tmp_path.parent / ('orders-restored-media-'+buyer['id'])
    restored_db = tmp_path.parent / ('orders-restored-'+buyer['id']+'.db')
    restore(destination, restored_db, restored_media)
    restored = TaskStore(restored_db)
    assert validate(restored, restored_media)['ok']
    with restored.transaction() as db:
        from pathlib import Path
        assert all(Path(r['path']).is_relative_to(restored_media) for r in db.execute('SELECT path FROM payment_assets'))
    target = request.getfixturevalue('postgres_store')
    import_sqlite(restored_db, target)
    import_sqlite(restored_db, target)
    with target.transaction() as db:
        assert db.execute('SELECT status FROM orders WHERE id=?', (ident,)).fetchone()[0] == 'credited'
        assert db.execute('SELECT COUNT(*) FROM payment_receipts').fetchone()[0] == 1
