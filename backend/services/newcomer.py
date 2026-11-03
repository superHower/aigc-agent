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


def offer(db, user_id, plan_id=None):
    user = db.execute('SELECT role,created_at FROM users WHERE id=?', (user_id,)).fetchone()
    deadline = datetime.fromisoformat(user['created_at']) + timedelta(hours=24)
    if plan_id is None:
        selected = db.execute('SELECT id FROM membership_plans WHERE newcomer_only=1 ORDER BY price_cents,id LIMIT 1').fetchone()
        if not selected:
            return None
        plan_id = selected['id']
    selected = db.execute('SELECT * FROM membership_plans WHERE id=?', (plan_id,)).fetchone()
    if not selected:
        return None
    claim = db.execute('SELECT * FROM newcomer_plan_claims WHERE user_id=? AND plan_id=?', (user_id, plan_id)).fetchone()
    eligible = user['role'] == 'user' and datetime.now(timezone.utc) < deadline and first_purchase(db, user_id) and not (claim and claim['activated_at'])
    eligible = eligible and bool(selected['newcomer_only'] or claim)
    plan = json.loads(claim['snapshot']) if claim else dict(selected)
    return {'eligible': eligible, 'deadline': deadline.isoformat(), 'server_now': utc_now(),
            'reserved': bool(claim), 'plan': plan, 'original_price_cents': selected['price_cents']}


def reserve(db, user_id, plan_id=None):
    result = offer(db, user_id, plan_id)
    if not result or not result['eligible']:
        raise HTTPException(409, '新人优惠已过期或不符合首单限购条件')
    plan_id = result['plan']['id']
    db.execute('INSERT INTO newcomer_plan_claims (user_id,plan_id,snapshot,created_at) VALUES (?,?,?,?) ON CONFLICT(user_id,plan_id) DO NOTHING',
               (user_id, plan_id, json.dumps(result['plan']), utc_now()))
    return offer(db, user_id, plan_id)


def activate(db, user_id, plan_id='newcomer'):
    claim = db.execute('SELECT * FROM newcomer_plan_claims WHERE user_id=? AND plan_id=?', (user_id, plan_id)).fetchone()
    if not claim or claim['activated_at'] or not first_purchase(db, user_id):
        raise HTTPException(409, '请先在注册24小时内锁定新人首单资格；每个账户终身限购一次')
    db.execute('UPDATE newcomer_plan_claims SET activated_at=? WHERE user_id=? AND plan_id=?', (utc_now(), user_id, plan_id))
    return json.loads(claim['snapshot'])
