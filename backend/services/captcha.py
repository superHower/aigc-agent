"""Short-lived, single-attempt image challenges backed by the shared database."""
import base64
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from captcha.image import ImageCaptcha
from fastapi import HTTPException

from backend.db.task_store import utc_now
from backend.services import identity


def issue(store, ip):
    code = ''.join(secrets.choice('23456789ABCDEFGHJKLMNPQRSTUVWXYZ') for _ in range(5))
    challenge_id = secrets.token_urlsafe(32)
    with store.transaction() as db:
        identity.auth_transaction(db)
        pepper = identity.secret(db)
        allowed = identity.throttle(db, 'captcha:' + identity.keyed(pepper, ip), limit=60, minutes=5)
        db.execute('DELETE FROM captcha_challenges WHERE expires_at<=?', (utc_now(),))
        if allowed:
            db.execute('INSERT INTO captcha_challenges VALUES (?,?,?)', (
                challenge_id, identity.keyed(pepper, challenge_id + ':' + code),
                (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()))
    if not allowed:
        raise HTTPException(429, '验证码获取过于频繁，请稍后再试')
    image = ImageCaptcha(width=180, height=64).generate(code).getvalue()
    return {'captcha_id': challenge_id, 'image': 'data:image/png;base64,' + base64.b64encode(image).decode(), 'expires_in': 300}


def consume(db, challenge_id, code):
    row = db.execute('SELECT * FROM captcha_challenges WHERE id=?', (challenge_id,)).fetchone()
    db.execute('DELETE FROM captcha_challenges WHERE id=?', (challenge_id,))
    return bool(row and row['expires_at'] > utc_now() and hmac.compare_digest(
        row['code_hash'], identity.keyed(identity.secret(db), challenge_id + ':' + code.strip().upper())))


def register(store, name, number, password, challenge_id, code):
    from backend.services.passwords import hash_password
    password_hash = hash_password(password)
    user_id = secrets.token_hex(16)
    error = None
    with store.transaction() as db:
        identity.auth_transaction(db)
        if not consume(db, challenge_id, code):
            error = '图形验证码错误或已过期，请刷新后重试'
        elif db.execute('SELECT 1 FROM users WHERE username=? OR phone=?', (name, number)).fetchone():
            error = '用户名或手机号已被使用'
        else:
            db.execute('INSERT INTO users (id,username,phone,password_hash,role,created_at) VALUES (?,?,?,?,?,?)',
                       (user_id, name, number, password_hash, 'user', utc_now()))
            from backend.services.credits import trial
            trial(db, user_id, number)
    if error:
        raise HTTPException(400, error)
    return {'id': user_id, 'username': name, 'role': 'user'}
