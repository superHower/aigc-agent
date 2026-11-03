import json
import re
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from backend.db.task_store import utc_now
from backend.services import credits, subscriptions, newcomer
from backend.services.access import current_user, require_admin
from backend.routes.orders import save_asset, insert_asset

router = APIRouter(tags=['recharge'])


class RiskInput(BaseModel):
    daily_limit: int = Field(ge=0, le=100000000)
    concurrency: int = Field(ge=0, le=100)
    retry_limit: int = Field(ge=0, le=100)


@router.get('/api/admin/risk-settings')
def risk_settings(request: Request):
    require_admin(request)
    with request.app.state.store.transaction() as db:
        return {name: int(db.execute('SELECT value FROM system_settings WHERE key=?', ('risk_'+name,)).fetchone()['value']) for name in ('daily_limit', 'concurrency', 'retry_limit')}


@router.put('/api/admin/risk-settings')
def save_risk(payload: RiskInput, request: Request):
    actor = require_admin(request)
    with request.app.state.store.transaction() as db:
        credits.begin(db)
        for name, value in payload.model_dump().items():
            db.execute('INSERT INTO system_settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', ('risk_'+name, str(value)))
        db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)', (uuid4().hex, actor['id'], 'risk_settings_save', 'risk', '调整防滥用风控', payload.model_dump_json(), utc_now()))
    return {'ok': True}


def plans(db):
    return [dict(r) for r in db.execute("SELECT id,name,cost,price_cents,credits,duration_days,newcomer_only FROM membership_plans ORDER BY cost DESC")]


@router.get('/api/recharge')
def recharge(request: Request):
    user = current_user(request)
    with request.app.state.store.transaction() as db:
        credits.begin(db)
        sub = subscriptions.sync(db, user['id'])
        setting = db.execute("SELECT value FROM system_settings WHERE key='customer_service_asset'").fetchone()
        plan = json.loads(sub['snapshot']) if sub else dict(db.execute("SELECT * FROM membership_plans WHERE id='ordinary'").fetchone())
        plan = {key: plan[key] for key in ('id', 'name', 'cost', 'price_cents', 'credits')}
        if sub:
            plan['credits'] = db.execute('SELECT COALESCE(SUM(credits),0) FROM membership_periods WHERE subscription_id=?', (sub['id'],)).fetchone()[0]
        offers = [newcomer.offer(db, user['id'], p['id']) for p in plans(db) if p['newcomer_only']]
        return {'plans': [p for p in plans(db) if not p['newcomer_only']], 'current_plan': plan, 'expires_at': sub['expires_at'] if sub else None,
                'newcomer_offer': newcomer.offer(db, user['id']),
                'newcomer_offers': offers,
                'customer_service_url': '/api/payment-assets/' + setting['value'] if setting else None,
                'recharge_ratio': 100}


@router.post('/api/recharge/newcomer/reserve')
def reserve_newcomer(request: Request, plan_id: str | None = None):
    user = current_user(request)
    with request.app.state.store.transaction() as db:
        credits.begin(db)
        return newcomer.reserve(db, user['id'], plan_id)


@router.get('/api/admin/membership-plans')
def admin_plans(request: Request):
    require_admin(request)
    with request.app.state.store.transaction() as db:
        return {'items': plans(db)}


class PlanInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=50)
    cost: int = Field(strict=True, ge=1, le=100000)
    price_cents: int = Field(strict=True, ge=0, le=100000000)
    credits: int = Field(strict=True, ge=0, le=10000000)
    duration_days: int = Field(default=0, strict=True, ge=0, le=3650)
    newcomer_only: bool = False
    image_limit: int = Field(default=0, strict=True, ge=0, le=0)
    total_limit: int = Field(default=0, strict=True, ge=0, le=0)
    risk_limit: int = Field(default=0, strict=True, ge=0, le=0)


def validate_plan(plan_id: str, payload: PlanInput):
    if not re.fullmatch(r'[a-z][a-z0-9_-]{1,49}', plan_id):
        raise HTTPException(422, '套餐标识只能使用小写字母、数字、下划线或短横线')
    if payload.newcomer_only and (not payload.duration_days or not payload.price_cents or not payload.credits):
        raise HTTPException(422, '新人体验卡的价格、积分和有效期必须大于0')


@router.put('/api/admin/membership-plans/{plan_id}')
def update_plan(plan_id: str, payload: PlanInput, request: Request):
    actor = require_admin(request)
    with request.app.state.store.transaction() as db:
        credits.begin(db)
        old = db.execute('SELECT * FROM membership_plans WHERE id=?', (plan_id,)).fetchone()
        if not old:
            raise HTTPException(404, '套餐不存在')
        validate_plan(plan_id, payload)
        if plan_id == 'ordinary' and payload.newcomer_only:
            raise HTTPException(422, '普通套餐不能设置为新人专享')
        if plan_id != 'ordinary' and not payload.duration_days:
            raise HTTPException(422, '请设置套餐有效期')
        values = payload.model_dump()
        values['newcomer_only'] = int(payload.newcomer_only)
        db.execute('UPDATE membership_plans SET ' + ','.join(k+'=?' for k in values) + ' WHERE id=?', (*values.values(), plan_id))
        db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)', (uuid4().hex, actor['id'], 'membership_plan_save', plan_id, '套餐设置', json.dumps({'before': dict(old), 'after': values}), utc_now()))
    return {'ok': True}


@router.post('/api/admin/membership-plans/{plan_id}', status_code=201)
def create_plan(plan_id: str, payload: PlanInput, request: Request):
    actor = require_admin(request)
    validate_plan(plan_id, payload)
    if not payload.duration_days:
        raise HTTPException(422, '请设置套餐有效期')
    with request.app.state.store.transaction() as db:
        credits.begin(db)
        if db.execute('SELECT 1 FROM membership_plans WHERE id=?', (plan_id,)).fetchone():
            raise HTTPException(409, '套餐标识已存在')
        values = payload.model_dump()
        values['newcomer_only'] = int(payload.newcomer_only)
        db.execute('INSERT INTO membership_plans (id,' + ','.join(values) + ') VALUES (?, ' + ','.join('?' for _ in values) + ')', (plan_id, *values.values()))
        db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)', (uuid4().hex, actor['id'], 'membership_plan_create', plan_id, '新增套餐', json.dumps(values), utc_now()))
    return {'id': plan_id}


@router.delete('/api/admin/membership-plans/{plan_id}')
def delete_plan(plan_id: str, request: Request):
    actor = require_admin(request)
    with request.app.state.store.transaction() as db:
        credits.begin(db)
        old = db.execute('SELECT * FROM membership_plans WHERE id=?', (plan_id,)).fetchone()
        if not old:
            raise HTTPException(404, '套餐不存在')
        if plan_id == 'ordinary':
            raise HTTPException(409, '普通套餐是系统默认扣费规则，不能删除')
        if db.execute('SELECT 1 FROM subscriptions WHERE plan_id=? LIMIT 1', (plan_id,)).fetchone():
            raise HTTPException(409, '套餐已有会员使用记录，不能删除；请编辑参数或停用')
        if db.execute('SELECT 1 FROM newcomer_plan_claims WHERE plan_id=? LIMIT 1', (plan_id,)).fetchone():
            raise HTTPException(409, '套餐已有新人资格记录，不能删除；请编辑参数')
        db.execute('DELETE FROM membership_plans WHERE id=?', (plan_id,))
        db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)', (uuid4().hex, actor['id'], 'membership_plan_delete', plan_id, '删除套餐', json.dumps(dict(old)), utc_now()))
    return {'ok': True}


@router.post('/api/admin/customer-service', status_code=201)
async def upload_customer_service(request: Request, file: UploadFile = File(...)):
    actor = require_admin(request)
    row = await save_asset(request, file, 'payment_code')
    with request.app.state.store.transaction() as db:
        credits.begin(db)
        insert_asset(db, row)
        db.execute("INSERT INTO system_settings (key,value) VALUES ('customer_service_asset',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (row['id'],))
        db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)', (uuid4().hex, actor['id'], 'customer_service_save', row['id'], '更新客服微信图片', '{}', utc_now()))
    return {'url': '/api/payment-assets/' + row['id']}
