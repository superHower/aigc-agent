"""New-account offer reservation and once-per-account activation."""
import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from backend.db.task_store import utc_now


def first_purchase(db, user_id):
    return not (
        db.execute('SELECT 1 FROM subscriptions WHERE user_id=?', (user_id,)).fetchone()
        or db.execute("SELECT 1 FROM credit_lots WHERE user_id=? AND source IN ('paid','adjustment')", (user_id,)).fetchone()
        or db.execute("SELECT 1 FROM orders WHERE user_id=? AND status='credited'", (user_id,)).fetchone()
    )


def offer(db, user_id):
    user = db.execute('SELECT role,created_at FROM users WHERE id=?', (user_id,)).fetchone()
    deadline = datetime.fromisoformat(user['created_at']) + timedelta(hours=24)
    claim = db.execute('SELECT * FROM newcomer_claims WHERE user_id=?', (user_id,)).fetchone()
    eligible = user['role'] == 'user' and datetime.now(timezone.utc) < deadline and first_purchase(db, user_id) and not (claim and claim['activated_at'])
    plan = json.loads(claim['snapshot']) if claim else dict(db.execute("SELECT * FROM membership_plans WHERE id='newcomer'").fetchone())
    monthly = db.execute("SELECT price_cents FROM membership_plans WHERE id='monthly'").fetchone()
    return {'eligible': eligible, 'deadline': deadline.isoformat(), 'server_now': utc_now(),
            'reserved': bool(claim), 'plan': plan, 'original_price_cents': monthly['price_cents']}


def reserve(db, user_id):
    result = offer(db, user_id)
    if not result['eligible']:
        raise HTTPException(409, '新人优惠已过期或不符合首单限购条件')
    db.execute('INSERT INTO newcomer_claims (user_id,snapshot,created_at) VALUES (?,?,?) ON CONFLICT(user_id) DO NOTHING',
               (user_id, json.dumps(result['plan']), utc_now()))
    return offer(db, user_id)


def activate(db, user_id):
    claim = db.execute('SELECT * FROM newcomer_claims WHERE user_id=?', (user_id,)).fetchone()
    if not claim or claim['activated_at'] or not first_purchase(db, user_id):
        raise HTTPException(409, '请先在注册24小时内锁定新人首单资格；每个账户终身限购一次')
    db.execute('UPDATE newcomer_claims SET activated_at=? WHERE user_id=?', (utc_now(), user_id))
    return json.loads(claim['snapshot'])
