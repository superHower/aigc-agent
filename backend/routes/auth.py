"""Cookie sessions and phone verification."""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from pydantic import field_validator

from backend.services.passwords import verify_password, DUMMY_HASH
from backend.services import identity

router = APIRouter(prefix='/api/auth', tags=['authentication'])


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def account(request):
    store = getattr(request.app.state, 'store', None)
    if store is None:
        return None
    with store.transaction() as db:
        row = db.execute('''SELECT u.id,u.username,u.role,u.disabled,u.membership_expires_at,s.csrf_hash,s.expires_at
            FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.revoked_at IS NULL''', (digest(request.cookies.get('session', '')),)).fetchone()
    if not row or row['disabled'] or datetime.fromisoformat(row['expires_at']) <= datetime.now(timezone.utc):
        return None
    return dict(row)


class Login(BaseModel):
    account: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=64)


@router.post('/login')
def login(payload: Login, request: Request, response: Response):
    now = datetime.now(timezone.utc)
    store = getattr(request.app.state, 'store', None)
    if store is None:
        raise HTTPException(503, '服务尚未初始化')
    ip = request.client.host if request.client else 'unknown'
    with store.transaction() as db:
        identity.auth_transaction(db)
        pepper = identity.secret(db)
        allowed = identity.throttle(db, 'login-ip:' + identity.keyed(pepper, ip), limit=40)
        allowed_account = identity.throttle(db, 'login-account:' + identity.keyed(pepper, payload.account.strip().lower()))
    if not allowed or not allowed_account:
        raise HTTPException(429, '尝试过多，请稍后重试')
    with store.transaction() as db:
        identity.auth_transaction(db)
        user = db.execute('SELECT * FROM users WHERE username=? OR phone=?', (payload.account.strip().lower(), payload.account.strip())).fetchone()
        valid = verify_password(payload.password, user['password_hash'] if user else DUMMY_HASH)
        if not user or user['disabled'] or not valid:
            raise HTTPException(401, '账号或密码错误')
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.execute('INSERT INTO sessions (token_hash,user_id,csrf_hash,expires_at) VALUES (?,?,?,?)',
                   (digest(token), user['id'], digest(csrf), (now + timedelta(hours=12)).isoformat()))
    secure = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
    response.set_cookie('session', token, httponly=True, secure=secure, samesite='lax', max_age=43200)
    response.set_cookie('csrf', csrf, secure=secure, samesite='lax', max_age=43200)
    return {'id': user['id'], 'username': user['username'], 'role': user['role']}


class SmsInput(BaseModel):
    phone: str
    purpose: str

    @field_validator('phone')
    @classmethod
    def valid_phone(cls, value):
        return identity.phone(value)

    @field_validator('purpose')
    @classmethod
    def valid_purpose(cls, value):
        if value not in ('register', 'reset'):
            raise ValueError('验证码用途不正确')
        return value


class Registration(BaseModel):
    username: str
    phone: str
    password: str = Field(min_length=8, max_length=64)
    code: str = Field(pattern=r'^[0-9]{6}$')

    @field_validator('username')
    @classmethod
    def valid_name(cls, value):
        return identity.username(value)

    @field_validator('phone')
    @classmethod
    def valid_phone(cls, value):
        return identity.phone(value)


class Reset(BaseModel):
    phone: str
    password: str = Field(min_length=8, max_length=64)
    code: str = Field(pattern=r'^[0-9]{6}$')

    @field_validator('phone')
    @classmethod
    def valid_phone(cls, value):
        return identity.phone(value)


@router.post('/sms')
def sms(payload: SmsInput, request: Request):
    identity.issue_sms(request.app.state.store, payload.phone, payload.purpose, request.client.host if request.client else 'unknown')
    return {'ok': True, 'retry_after': 60, 'expires_in': 300}


@router.post('/register', status_code=201)
def register(payload: Registration, request: Request):
    return identity.register(request.app.state.store, payload.username, payload.phone, payload.password, payload.code)


@router.post('/reset-password')
def reset_password(payload: Reset, request: Request):
    return identity.reset_password(request.app.state.store, payload.phone, payload.password, payload.code)


@router.get('/me')
def me(request: Request):
    user = account(request)
    if user is None:
        raise HTTPException(401, '请先登录')
    return {k: user[k] for k in ('id', 'username', 'role')}


@router.post('/logout')
def logout(request: Request, response: Response):
    with request.app.state.store.transaction() as db:
        identity.auth_transaction(db)
        db.execute('UPDATE sessions SET revoked_at=? WHERE token_hash=?',
                   (datetime.now(timezone.utc).isoformat(), digest(request.cookies.get('session', ''))))
    response.delete_cookie('session')
    response.delete_cookie('csrf')
    return {'ok': True}


def csrf_valid(request, user):
    return hmac.compare_digest(digest(request.headers.get('x-csrf-token', '')), user['csrf_hash'])
