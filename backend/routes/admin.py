import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.db.task_store import utc_now
from backend.services.access import require_admin
from backend.services.identity import auth_transaction

router = APIRouter(prefix='/api/admin', tags=['admin'])


@router.get('/users')
def users(request: Request, limit: int = 50, offset: int = 0):
    require_admin(request)
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, '分页参数不正确')
    with request.app.state.store.transaction() as db:
        return {'items': [dict(r) for r in db.execute('SELECT id,username,phone,role,disabled,membership_expires_at,created_at FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?', (limit, offset))]}


class UserStatus(BaseModel):
    disabled: bool
    reason: str = Field(min_length=1, max_length=500)


@router.post('/users/{user_id}/status')
def status(user_id: str, payload: UserStatus, request: Request):
    actor = require_admin(request)
    if not payload.reason.strip():
        raise HTTPException(422, '请填写操作原因')
    with request.app.state.store.transaction() as db:
        auth_transaction(db)
        user = db.execute('SELECT id,role,disabled FROM users WHERE id=?', (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, '用户不存在')
        if user['role'] == 'admin':
            raise HTTPException(403, '此入口不允许禁用管理员')
        db.execute('UPDATE users SET disabled=? WHERE id=?', (int(payload.disabled), user_id))
        if payload.disabled:
            db.execute('UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL', (utc_now(), user_id))
        db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)', (uuid4().hex, actor['id'], 'user_status', user_id, payload.reason.strip(), json.dumps({'before': user['disabled'], 'after': payload.disabled}), utc_now()))
    return {'ok': True}
