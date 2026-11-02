import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from backend.db.task_store import utc_now
from backend.services.passwords import hash_password
from backend.services.sms import send_sms


def username(value):
    value = value.strip().lower()
    if not re.fullmatch(r'[\u4e00-\u9fffA-Za-z0-9_]{3,24}', value) or value.isdecimal():
        raise ValueError('用户名须为 3–24 位中文、字母、数字或下划线，不能为纯数字')
    return value


def email(value):
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
        raise ValueError('请输入有效的邮箱地址')
    return value


def register_email(store, name, address, password, ip):
    password_hash = hash_password(password)
    with store.transaction() as db:
        auth_transaction(db)
        allowed = throttle(db, 'register:' + keyed(secret(db), ip), limit=10, minutes=60)
    if not allowed:
        raise HTTPException(429, '注册过于频繁，请稍后重试')
    with store.transaction() as db:
        auth_transaction(db)
        if db.execute('SELECT id FROM users WHERE username=? OR email=?', (name, address)).fetchone():
            raise HTTPException(409, '用户名或邮箱已被使用')
        ident = uuid4().hex
        db.execute('INSERT INTO users (id,username,email,password_hash,role,created_at) VALUES (?,?,?,?,?,?)',
                   (ident, name, address, password_hash, 'user', utc_now()))
        from backend.services.credits import ensure_account, grant
        ensure_account(db, ident)
        grant(db, ident, 500, 'trial', 'registration:' + ident)
    return {'id': ident, 'username': name, 'role': 'user'}


def change_password(store, address, old_password, password, ip):
    from backend.services.passwords import verify_password, DUMMY_HASH
    with store.transaction() as db:
        auth_transaction(db)
        pepper = secret(db)
        allowed = throttle(db, 'password-ip:' + keyed(pepper, ip), limit=40)
        account_allowed = throttle(db, 'password-account:' + keyed(pepper, address))
    if not allowed or not account_allowed:
        raise HTTPException(429, '尝试过多，请稍后重试')
    with store.transaction() as db:
        auth_transaction(db)
        user = db.execute('SELECT * FROM users WHERE email=?', (address,)).fetchone()
        valid = verify_password(old_password, user['password_hash'] if user else DUMMY_HASH)
        if not user or user['disabled'] or not valid:
            raise HTTPException(401, '邮箱或原密码错误')
        db.execute('UPDATE users SET password_hash=? WHERE id=?', (hash_password(password), user['id']))
        db.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL', (utc_now(), user['id']))
    return {'ok': True}


def phone(value):
    value = value.strip()
    if not re.fullmatch(r'1[3-9][0-9]{9}', value):
        raise ValueError('请输入有效的中国大陆手机号')
    return value


def auth_transaction(db):
    db.execute('BEGIN IMMEDIATE')
    if db.postgres:
        db.execute('SELECT pg_advisory_xact_lock(401030)')


def secret(db):
    db.execute("INSERT INTO system_settings (key,value) VALUES ('auth_pepper',?) ON CONFLICT (key) DO NOTHING", (secrets.token_hex(32),))
    return db.execute("SELECT value FROM system_settings WHERE key='auth_pepper'").fetchone()[0]


def keyed(key, value):
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def throttle(db, key, limit=10, minutes=15):
    now = datetime.now(timezone.utc)
    db.execute('DELETE FROM auth_limits WHERE expires_at <= ?', (now.isoformat(),))
    row = db.execute('SELECT * FROM auth_limits WHERE key=?', (key,)).fetchone()
    if row and row['attempts'] >= limit:
        return False
    db.execute('''INSERT INTO auth_limits (key,attempts,expires_at) VALUES (?,1,?)
        ON CONFLICT (key) DO UPDATE SET attempts=auth_limits.attempts+1''', (key, (now + timedelta(minutes=minutes)).isoformat()))
    return True


def issue_sms(store, number, purpose, ip):
    now = datetime.now(timezone.utc)
    challenge_id, code = uuid4().hex, f'{secrets.randbelow(1000000):06d}'
    with store.transaction() as db:
        auth_transaction(db)
        pepper = secret(db)
        ip_hash = keyed(pepper, ip)
        latest = db.execute('SELECT created_at FROM sms_challenges WHERE phone=? ORDER BY created_at DESC LIMIT 1', (number,)).fetchone()
        recent = db.execute('SELECT COUNT(*) FROM sms_challenges WHERE phone=? AND created_at>?', (number, (now-timedelta(days=1)).isoformat())).fetchone()[0]
        ip_count = db.execute('SELECT COUNT(*) FROM sms_challenges WHERE ip_hash=? AND created_at>?', (ip_hash, (now-timedelta(hours=1)).isoformat())).fetchone()[0]
        if (latest and (now-datetime.fromisoformat(latest['created_at'])).total_seconds() < 60) or recent >= 10 or ip_count >= 20:
            raise HTTPException(429, '验证码发送过于频繁，请稍后重试')
        db.execute("UPDATE sms_challenges SET used_at=? WHERE phone=? AND purpose=? AND used_at IS NULL", (now.isoformat(), number, purpose))
        db.execute('INSERT INTO sms_challenges (id,phone,purpose,code_hash,created_at,expires_at,status,ip_hash) VALUES (?,?,?,?,?,?,?,?)',
                   (challenge_id, number, purpose, keyed(pepper, challenge_id+':'+code), now.isoformat(), (now+timedelta(minutes=5)).isoformat(), 'pending', ip_hash))
    try:
        send_sms(number, purpose, code, challenge_id)
    except Exception:
        with store.transaction() as db:
            db.execute("UPDATE sms_challenges SET status='failed' WHERE id=?", (challenge_id,))
        raise HTTPException(503, '短信发送服务未配置或暂不可用，请稍后重试') from None
    with store.transaction() as db:
        db.execute("UPDATE sms_challenges SET status='sent' WHERE id=?", (challenge_id,))


def consume(db, number, purpose, code):
    row = db.execute('SELECT * FROM sms_challenges WHERE phone=? AND purpose=? ORDER BY created_at DESC LIMIT 1', (number, purpose)).fetchone()
    if not row or row['status'] != 'sent' or row['used_at'] or row['attempts'] >= 5 or row['expires_at'] <= utc_now():
        return False
    db.execute('UPDATE sms_challenges SET attempts=attempts+1 WHERE id=?', (row['id'],))
    if not hmac.compare_digest(row['code_hash'], keyed(secret(db), row['id']+':'+code)):
        return False
    db.execute('UPDATE sms_challenges SET used_at=? WHERE id=?', (utc_now(), row['id']))
    return True


def register(store, name, number, password, code):
    password_hash = hash_password(password)
    error = None
    user_id = uuid4().hex
    with store.transaction() as db:
        auth_transaction(db)
        # Failed code attempts must commit before returning an error.
        if not consume(db, number, 'register', code):
            error = '验证码错误、已使用或已过期'
        elif db.execute('SELECT 1 FROM users WHERE username=? OR phone=?', (name, number)).fetchone():
            error = '用户名或手机号已被使用'
        else:
            db.execute('INSERT INTO users (id,username,phone,password_hash,role,created_at) VALUES (?,?,?,?,?,?)', (user_id, name, number, password_hash, 'user', utc_now()))
            from backend.services.credits import trial
            trial(db, user_id, number)
    if error:
        raise HTTPException(400, error)
    return {'id': user_id, 'username': name, 'role': 'user'}


def reset_password(store, number, password, code):
    password_hash = hash_password(password)
    with store.transaction() as db:
        auth_transaction(db)
        valid = consume(db, number, 'reset', code)
        if valid:
            user = db.execute('SELECT id FROM users WHERE phone=?', (number,)).fetchone()
            if user:
                db.execute('UPDATE users SET password_hash=? WHERE id=?', (password_hash, user['id']))
                db.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL', (utc_now(), user['id']))
    if not valid:
        raise HTTPException(400, '验证码错误、已使用或已过期')
    return {'ok': True}
