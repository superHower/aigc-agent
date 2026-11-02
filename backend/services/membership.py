"""Membership benefits are calculated at admission; renewals share the billing transaction."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from backend.db.task_store import utc_now


def active(expires_at, now=None):
    return bool(expires_at and datetime.fromisoformat(expires_at) > (now or datetime.now(timezone.utc)))


def renew(db, user_id, days, key):
    # Caller must hold credits.begin() lock, including when composing order settlement.
    if days <= 0:
        raise ValueError('会员天数必须为正整数')
    previous = db.execute('SELECT * FROM membership_entries WHERE business_key=?', (key,)).fetchone()
    if previous:
        if (previous['user_id'], previous['days']) != (user_id, days):
            raise HTTPException(409, '会员发放凭证参数冲突')
        return previous['expires_at']
    user = db.execute('SELECT membership_expires_at FROM users WHERE id=?', (user_id,)).fetchone()
    if not user:
        raise HTTPException(404, '用户不存在')
    old = user['membership_expires_at']
    now = datetime.now(timezone.utc)
    expires = (max(now, datetime.fromisoformat(old)) if old else now) + timedelta(days=days)
    result = expires.isoformat()
    db.execute('UPDATE users SET membership_expires_at=? WHERE id=?', (result, user_id))
    db.execute('INSERT INTO membership_entries VALUES (?,?,?,?,?,?)', (key, user_id, days, old, result, utc_now()))
    return result


def status(store, user_id, ordinary=1, member=3):
    with store.transaction() as db:
        row = db.execute('SELECT membership_expires_at FROM users WHERE id=?', (user_id,)).fetchone()
        risk = db.execute("SELECT value FROM system_settings WHERE key='risk_concurrency'").fetchone()
    expires = row['membership_expires_at'] if row else None
    is_member = active(expires)
    return {'active': is_member, 'expires_at': expires, 'concurrency': int(risk['value']) if risk and int(risk['value']) else (member if is_member else ordinary)}
