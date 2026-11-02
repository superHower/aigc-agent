import json
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
    return [dict(r) for r in db.execute("SELECT id,name,cost,price_cents,credits,duration_hours FROM membership_plans ORDER BY cost DESC")]


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
        return {'plans': [p for p in plans(db) if p['id'] != 'newcomer'], 'current_plan': plan, 'expires_at': sub['expires_at'] if sub else None,
                'newcomer_offer': newcomer.offer(db, user['id']),
                'customer_service_url': '/api/payment-assets/' + setting['value'] if setting else None,
                'recharge_ratio': 100}


@router.post('/api/recharge/newcomer/reserve')
def reserve_newcomer(request: Request):
    user = current_user(request)
    with request.app.state.store.transaction() as db:
        credits.begin(db)
        return newcomer.reserve(db, user['id'])


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
    duration_hours: int = Field(default=0, strict=True, ge=0, le=8760)
    image_limit: int = Field(default=0, strict=True, ge=0, le=0)
    total_limit: int = Field(default=0, strict=True, ge=0, le=0)
    risk_limit: int = Field(default=0, strict=True, ge=0, le=0)


@router.put('/api/admin/membership-plans/{plan_id}')
def update_plan(plan_id: str, payload: PlanInput, request: Request):
    actor = require_admin(request)
    with request.app.state.store.transaction() as db:
        credits.begin(db)
        old = db.execute('SELECT * FROM membership_plans WHERE id=?', (plan_id,)).fetchone()
        if not old:
            raise HTTPException(404, '套餐不存在')
        if plan_id == 'newcomer' and (not payload.duration_hours or not payload.price_cents or not payload.credits):
            raise HTTPException(422, '新人体验卡的价格、积分和有效期必须大于0')
        values = payload.model_dump()
        db.execute('UPDATE membership_plans SET ' + ','.join(k+'=?' for k in values) + ' WHERE id=?', (*values.values(), plan_id))
        db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)', (uuid4().hex, actor['id'], 'membership_plan_save', plan_id, '套餐设置', json.dumps({'before': dict(old), 'after': values}), utc_now()))
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
