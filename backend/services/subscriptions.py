"""Immediate membership benefits, immutable pricing snapshots and expiry."""
import calendar
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from backend.db.task_store import utc_now


def add_months(value, months):
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def current(db, user_id):
    now = utc_now()
    return db.execute('SELECT * FROM subscriptions WHERE user_id=? AND starts_at<=? AND expires_at>? AND cancelled_at IS NULL ORDER BY created_at DESC LIMIT 1', (user_id, now, now)).fetchone()


def sync(db, user_id):
    from backend.services import credits
    sub = current(db, user_id)
    if sub:
        now = utc_now()
        for period in db.execute('SELECT * FROM membership_periods WHERE subscription_id=? AND starts_at<=? AND expires_at>? AND lot_id IS NULL', (sub['id'], now, now)).fetchall():
            if period['credits']:
                lot = credits.grant(db, user_id, period['credits'], 'membership', 'period:' + period['id'], period['expires_at'])
                db.execute('UPDATE membership_periods SET lot_id=? WHERE id=?', (lot, period['id']))
    return sub


def assign(db, user_id, plan_id):
    from backend.services import credits
    plan = db.execute('SELECT * FROM membership_plans WHERE id=?', (plan_id,)).fetchone()
    if not plan:
        raise HTTPException(404, '套餐不存在')
    now = datetime.now(timezone.utc)
    if plan_id == 'newcomer':
        from backend.services.newcomer import activate
        plan = activate(db, user_id)
    # A change replaces the previous membership and invalidates its unused benefits.
    db.execute('UPDATE subscriptions SET cancelled_at=? WHERE user_id=? AND cancelled_at IS NULL', (now.isoformat(), user_id))
    db.execute("UPDATE credit_lots SET expires_at=? WHERE user_id=? AND source='membership' AND (expires_at>? OR expires_at IS NULL)", (now.isoformat(), user_id, now.isoformat()))
    credits.expire(db, user_id)
    if plan_id == 'ordinary':
        db.execute('UPDATE users SET membership_expires_at=NULL WHERE id=?', (user_id,))
        return None
    count = 3 if plan_id == 'quarterly' else 1
    end = now + timedelta(hours=plan['duration_hours']) if plan['duration_hours'] else (now + timedelta(days=7) if plan_id == 'weekly' else add_months(now, count))
    ident = uuid4().hex
    db.execute('INSERT INTO subscriptions VALUES (?,?,?,?,?,?,NULL,?)', (ident, user_id, plan_id, json.dumps(dict(plan)), now.isoformat(), end.isoformat(), now.isoformat()))
    # Membership benefits are granted in full immediately and expire with the membership.
    db.execute('INSERT INTO membership_periods VALUES (?,?,?,?,?,NULL)', (uuid4().hex, ident, now.isoformat(), end.isoformat(), plan['credits']))
    db.execute('UPDATE users SET membership_expires_at=? WHERE id=?', (end.isoformat(), user_id))
    sync(db, user_id)
    return end.isoformat()


def pricing(db, user_id, quantity):
    sub = sync(db, user_id)
    if not sub:
        cost = db.execute("SELECT cost FROM membership_plans WHERE id='ordinary'").fetchone()['cost']
        check_daily(db, user_id, quantity * cost)
        return cost, None, None
    plan = json.loads(sub['snapshot'])
    now = utc_now()
    period = db.execute('SELECT * FROM membership_periods WHERE subscription_id=? AND starts_at<=? AND expires_at>?', (sub['id'], now, now)).fetchone()
    check_daily(db, user_id, quantity * plan['cost'])
    return plan['cost'], sub['id'], period['id']


def check_daily(db, user_id, amount):
    setting = db.execute("SELECT value FROM system_settings WHERE key='risk_daily_limit'").fetchone()
    if setting and int(setting['value']) > 0:
        day = utc_now()[:10]
        consumed = db.execute("SELECT COALESCE(SUM(-frozen_delta),0) FROM credit_entries WHERE user_id=? AND event='settle' AND created_at LIKE ?", (user_id, day + '%')).fetchone()[0]
        frozen = db.execute('SELECT COALESCE(SUM(frozen),0) FROM credit_lots WHERE user_id=?', (user_id,)).fetchone()[0]
        if consumed + frozen + amount > int(setting['value']):
            raise HTTPException(409, '已达到今日风控消耗上限，请稍后再试')


def refund_quote(db, subscription_id):
    """Membership fee only; bonus credits have no cash redemption value."""
    sub = db.execute('SELECT * FROM subscriptions WHERE id=?', (subscription_id,)).fetchone()
    if not sub:
        raise HTTPException(404, '会员记录不存在')
    if sub['cancelled_at'] or sub['expires_at'] <= utc_now():
        return 0
    rows = db.execute('''SELECT l.id,l.original,l.available,l.frozen FROM credit_lots l
        JOIN membership_periods p ON p.lot_id=l.id WHERE p.subscription_id=?''', (subscription_id,)).fetchall()
    if any(r['frozen'] for r in rows):
        raise HTTPException(409, '请等待会员积分关联任务结算后计算退款')
    original = sum(r['original'] for r in rows)
    unused = sum(r['available'] for r in rows)
    return json.loads(sub['snapshot'])['price_cents'] * unused // original if original else 0
