"""Manual receipt verification. Uploaded evidence never issues account benefits."""
import json
from uuid import uuid4

from fastapi import HTTPException

from backend.db.task_store import utc_now
from backend.services import credits, membership


def previous(db, actor, operation, key, payload):
    row = db.execute('SELECT * FROM financial_requests WHERE actor_id=? AND operation=? AND key=?', (actor, operation, key)).fetchone()
    if row and row['fingerprint'] != credits.fingerprint(payload):
        raise HTTPException(409, '同一幂等凭证不能更改参数')
    return row['result_id'] if row else None


def record(db, actor, operation, key, payload, result):
    db.execute('INSERT INTO financial_requests VALUES (?,?,?,?,?,?)', (actor, operation, key, credits.fingerprint(payload), result, utc_now()))


def owned(db, order_id, actor):
    row = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
    if not row or (actor['role'] != 'admin' and row['user_id'] != actor['id']):
        raise HTTPException(404, '订单不存在')
    return dict(row)


def review(db, order_id, actor, action, reason):
    now = utc_now()
    db.execute('INSERT INTO order_reviews VALUES (?,?,?,?,?,?)', (uuid4().hex, order_id, actor, action, reason, now))
    db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)', (uuid4().hex, actor, 'order_'+action, order_id, reason, '{}', now))


def create(store, actor, package_id, key):
    payload = {'package_id': package_id}
    with store.transaction() as db:
        credits.begin(db)
        old = previous(db, actor['id'], 'order_create', key, payload)
        if old:
            return owned(db, old, actor)
        package = db.execute("SELECT * FROM packages WHERE id=? AND status='active'", (package_id,)).fetchone()
        code = db.execute('SELECT id FROM payment_codes WHERE active=1').fetchone()
        if not package:
            raise HTTPException(409, '套餐尚未上架或已下架')
        if not code:
            raise HTTPException(503, '尚未配置有效收款码，未创建订单')
        order_id, now = uuid4().hex, utc_now()
        db.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?, 'pending',?,?,NULL)", (order_id, actor['id'], package_id, package['name'], package['price_cents'], package['credits'], package['membership_days'], code['id'], now, now))
        record(db, actor['id'], 'order_create', key, payload, order_id)
        review(db, order_id, actor['id'], 'create', '创建人工充值订单')
        return owned(db, order_id, actor)


def evidence(store, actor, order_id, payload, key):
    params = {'order_id': order_id, **payload}
    with store.transaction() as db:
        credits.begin(db)
        order = owned(db, order_id, actor)
        if order['user_id'] != actor['id']:
            raise HTTPException(403, '仅订单本人可提交付款信息')
        if previous(db, actor['id'], 'evidence', key, params):
            return order
        if order['status'] not in ('pending', 'needs_info', 'review'):
            raise HTTPException(409, '当前订单不能提交付款信息')
        asset_id = payload.get('asset_id')
        if asset_id:
            asset = db.execute("SELECT id FROM payment_assets WHERE id=? AND owner_id=? AND purpose='evidence'", (asset_id, actor['id'])).fetchone()
            if not asset:
                raise HTTPException(404, '付款凭据不存在')
        evidence_id = uuid4().hex
        db.execute('INSERT INTO order_evidence VALUES (?,?,?,?,?,?,?)', (evidence_id, order_id, payload['declared_transaction'], payload['paid_at'], asset_id, payload['note'], utc_now()))
        db.execute("UPDATE orders SET status='review',updated_at=? WHERE id=?", (utc_now(), order_id))
        record(db, actor['id'], 'evidence', key, params, evidence_id)
        review(db, order_id, actor['id'], 'evidence', '用户提交付款信息，待人工核实')
        return owned(db, order_id, actor)


def transition(store, actor, order_id, action, reason, key):
    params = {'order_id': order_id, 'reason': reason}
    with store.transaction() as db:
        credits.begin(db)
        order = owned(db, order_id, actor)
        if previous(db, actor['id'], action, key, params):
            return order
        if action == 'cancel':
            if order['user_id'] != actor['id'] or order['status'] != 'pending':
                raise HTTPException(409, '仅能取消本人尚未提交付款信息的待付款订单')
            status = 'cancelled'
        else:
            if actor['role'] != 'admin':
                raise HTTPException(403, '需要管理员权限')
            if order['status'] != 'review':
                raise HTTPException(409, '仅待审核订单可以要求补充信息')
            status = 'needs_info'
        db.execute('UPDATE orders SET status=?,updated_at=? WHERE id=?', (status, utc_now(), order_id))
        review(db, order_id, actor['id'], action, reason)
        record(db, actor['id'], action, key, params, order_id)
        return owned(db, order_id, actor)


def verify(store, actor, order_id, payload, key, supplement=False):
    if actor['role'] != 'admin':
        raise HTTPException(403, '需要管理员权限')
    params = {'order_id': order_id, 'supplement': supplement, **payload}
    with store.transaction() as db:
        # All financial state transitions use this common transaction lock, before reading orders.
        credits.begin(db)
        order = owned(db, order_id, actor)
        if previous(db, actor['id'], 'verify', key, params):
            return order
        code = db.execute('SELECT channel FROM payment_codes WHERE id=?', (order['payment_code_id'],)).fetchone()
        if payload['channel'] != code['channel'] or payload['amount_cents'] != order['price_cents']:
            raise HTTPException(409, '核实金额或收款渠道与订单快照不一致')
        receipt = db.execute('SELECT * FROM payment_receipts WHERE order_id=?', (order_id,)).fetchone()
        if receipt:
            if (receipt['channel'], receipt['verified_transaction'], receipt['amount_cents']) != (payload['channel'], payload['verified_transaction'], payload['amount_cents']):
                raise HTTPException(409, '订单已入账，核实信息与原记录不一致')
            record(db, actor['id'], 'verify', key, params, order_id)
            return order
        if supplement:
            if order['status'] != 'cancelled':
                raise HTTPException(409, '补录入口只处理已取消但实际付款的订单')
        elif order['status'] != 'review':
            raise HTTPException(409, '请先由用户提交付款信息；已取消订单须走补录入口')
        used = db.execute('SELECT order_id FROM payment_receipts WHERE channel=? AND verified_transaction=?', (payload['channel'], payload['verified_transaction'])).fetchone()
        if used:
            raise HTTPException(409, '该收款交易号已核销其他订单')
        now = utc_now()
        db.execute('INSERT INTO payment_receipts VALUES (?,?,?,?,?,?,?)', (uuid4().hex, order_id, payload['channel'], payload['verified_transaction'], payload['amount_cents'], actor['id'], now))
        credits.grant(db, order['user_id'], order['credits'], 'paid', 'order:'+order_id)
        if order['membership_days']:
            membership.renew(db, order['user_id'], order['membership_days'], 'order:'+order_id)
        db.execute("UPDATE orders SET status='credited',credited_at=?,updated_at=? WHERE id=?", (now, now, order_id))
        review(db, order_id, actor['id'], 'supplement_verify' if supplement else 'verify', payload['reason'])
        record(db, actor['id'], 'verify', key, params, order_id)
        return owned(db, order_id, actor)


def adjust(store, actor, user_id, amount, reason, key):
    if actor['role'] != 'admin':
        raise HTTPException(403, '需要管理员权限')
    params = {'user_id': user_id, 'amount': amount, 'reason': reason}
    with store.transaction() as db:
        credits.begin(db)
        old = previous(db, actor['id'], 'adjust', key, params)
        if old:
            return {'id': old}
        if not db.execute('SELECT id FROM users WHERE id=?', (user_id,)).fetchone():
            raise HTTPException(404, '用户不存在')
        credits.expire(db, user_id)
        ident = uuid4().hex
        if amount > 0:
            credits.grant(db, user_id, amount, 'adjustment', 'adjust:'+ident)
        else:
            account = db.execute('SELECT available FROM credit_accounts WHERE user_id=?', (user_id,)).fetchone()
            if account['available'] < -amount:
                raise HTTPException(409, '可用积分不足，不能扣减冻结积分或透支')
            remaining = -amount
            lots = db.execute('SELECT * FROM credit_lots WHERE user_id=? AND available>0 ORDER BY CASE WHEN expires_at IS NULL THEN 1 ELSE 0 END,expires_at,created_at,id', (user_id,)).fetchall()
            for lot in lots:
                take = min(remaining, lot['available'])
                if not take:
                    break
                db.execute('UPDATE credit_lots SET available=available-? WHERE id=?', (take, lot['id']))
                credits.entry(db, user_id, lot['id'], 'adjust', -take, 0, 'adjust:'+ident+':'+lot['id'])
                remaining -= take
        db.execute('INSERT INTO credit_adjustments VALUES (?,?,?,?,?,?)', (ident, user_id, actor['id'], amount, reason, utc_now()))
        db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)', (uuid4().hex, actor['id'], 'credit_adjust', user_id, reason, json.dumps({'amount': amount, 'adjustment_id': ident}), utc_now()))
        record(db, actor['id'], 'adjust', key, params, ident)
        return {'id': ident}
