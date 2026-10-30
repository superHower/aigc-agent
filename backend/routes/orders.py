import io
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.db.task_store import utc_now
from backend.services import credits, orders
from backend.services.access import current_user, require_admin
from backend.services.file_storage import validate_image_bytes

router = APIRouter(tags=['manual payments'])


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class CreateOrder(Input):
    package_id: str = Field(min_length=1, max_length=100)


class Evidence(Input):
    declared_transaction: str = Field(min_length=1, max_length=200)
    paid_at: datetime
    asset_id: str | None = Field(default=None, max_length=100)
    note: str = Field(default='', max_length=1000)

    @field_validator('paid_at')
    @classmethod
    def valid_time(cls, value):
        if value.tzinfo is None:
            raise ValueError('付款时间须包含时区')
        if value > datetime.now(timezone.utc):
            raise ValueError('付款时间不能晚于当前时间')
        return value.astimezone(timezone.utc)


class Reason(Input):
    reason: str = Field(min_length=1, max_length=1000)


class Verification(Reason):
    channel: str = Field(min_length=1, max_length=100)
    verified_transaction: str = Field(min_length=1, max_length=200)
    amount_cents: int = Field(strict=True, ge=1, le=100000000)


class Adjustment(Reason):
    amount: int = Field(strict=True, ge=-10000000, le=10000000)

    @field_validator('amount')
    @classmethod
    def nonzero(cls, value):
        if value == 0:
            raise ValueError('调整数量不能为零')
        return value


@router.get('/api/payment-availability')
def availability(request: Request):
    current_user(request)
    with request.app.state.store.transaction() as db:
        return {'available': bool(db.execute('SELECT id FROM payment_codes WHERE active=1').fetchone())}


@router.post('/api/orders', status_code=201)
def create(payload: CreateOrder, request: Request):
    return orders.create(request.app.state.store, current_user(request), payload.package_id, credits.require_key(request))


@router.get('/api/orders')
@router.get('/api/admin/orders')
def listing(request: Request, status: Literal['pending', 'review', 'needs_info', 'cancelled', 'credited'] | None = None, limit: int = 50, offset: int = 0):
    actor = current_user(request)
    is_admin = request.url.path.startswith('/api/admin/')
    if is_admin:
        require_admin(request)
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, '分页参数无效')
    conditions, params = [], []
    if not is_admin:
        conditions.append('user_id=?'); params.append(actor['id'])
    if status:
        conditions.append('status=?'); params.append(status)
    where = ' WHERE '+' AND '.join(conditions) if conditions else ''
    with request.app.state.store.transaction() as db:
        total = db.execute('SELECT COUNT(*) FROM orders'+where, params).fetchone()[0]
        rows = db.execute('SELECT * FROM orders'+where+' ORDER BY created_at DESC,id LIMIT ? OFFSET ?', (*params, limit, offset))
        return {'items': [dict(r) for r in rows], 'total': total}


@router.get('/api/orders/{order_id}')
def detail(order_id: str, request: Request):
    with request.app.state.store.transaction() as db:
        result = orders.owned(db, order_id, current_user(request))
        result['payment_code'] = dict(db.execute('SELECT id,asset_id,channel,instructions FROM payment_codes WHERE id=?', (result['payment_code_id'],)).fetchone())
        result['evidence'] = [dict(r) for r in db.execute('SELECT * FROM order_evidence WHERE order_id=? ORDER BY created_at,id', (order_id,))]
        result['reviews'] = [dict(r) for r in db.execute('SELECT * FROM order_reviews WHERE order_id=? ORDER BY created_at,id', (order_id,))]
        receipt = db.execute('SELECT channel,verified_transaction,amount_cents,created_at FROM payment_receipts WHERE order_id=?', (order_id,)).fetchone()
        result['receipt'] = dict(receipt) if receipt else None
        return result


@router.post('/api/orders/{order_id}/evidence')
def evidence(order_id: str, payload: Evidence, request: Request):
    return orders.evidence(request.app.state.store, current_user(request), order_id, payload.model_dump(mode='json'), credits.require_key(request))


@router.post('/api/orders/{order_id}/cancel')
def cancel(order_id: str, request: Request):
    return orders.transition(request.app.state.store, current_user(request), order_id, 'cancel', '用户取消未提交凭据的订单', credits.require_key(request))


@router.post('/api/admin/orders/{order_id}/needs-info')
def needs_info(order_id: str, payload: Reason, request: Request):
    return orders.transition(request.app.state.store, require_admin(request), order_id, 'needs_info', payload.reason, credits.require_key(request))


@router.post('/api/admin/orders/{order_id}/verify')
def verify(order_id: str, payload: Verification, request: Request):
    return orders.verify(request.app.state.store, require_admin(request), order_id, payload.model_dump(), credits.require_key(request))


@router.post('/api/admin/orders/{order_id}/supplement-verify')
def supplement(order_id: str, payload: Verification, request: Request):
    return orders.verify(request.app.state.store, require_admin(request), order_id, payload.model_dump(), credits.require_key(request), supplement=True)


@router.post('/api/admin/users/{user_id}/credit-adjustments')
def adjustment(user_id: str, payload: Adjustment, request: Request):
    return orders.adjust(request.app.state.store, require_admin(request), user_id, payload.amount, payload.reason, credits.require_key(request))


async def save_asset(request, upload, purpose):
    actor = current_user(request)
    data = await upload.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, '图片不能超过 10 MB')
    try:
        image, _ = validate_image_bytes(data, upload.filename or 'image.png')
        if image.width * image.height > 25000000:
            raise ValueError('image dimensions too large')
        # Re-encode as PNG to discard metadata and untrusted original names.
        buffer = io.BytesIO()
        image.convert('RGB').save(buffer, format='PNG')
    except Exception:
        raise HTTPException(422, '请上传有效的 PNG、JPEG 或 WebP 图片（不超过 2500 万像素）') from None
    ident = uuid4().hex
    root = request.app.state.settings.data_dir / 'payments'
    root.mkdir(parents=True, exist_ok=True)
    target = root / (ident+'.png')
    temporary = target.with_suffix('.tmp')
    temporary.write_bytes(buffer.getvalue())
    temporary.replace(target)
    return {'id': ident, 'owner_id': actor['id'], 'purpose': purpose, 'path': str(target), 'created_at': utc_now()}


def insert_asset(db, row):
    db.execute('INSERT INTO payment_assets VALUES (?,?,?,?,?)', tuple(row.values()))


@router.post('/api/order-evidence-assets', status_code=201)
async def upload_evidence(request: Request, file: UploadFile = File(...)):
    row = await save_asset(request, file, 'evidence')
    with request.app.state.store.transaction() as db:
        insert_asset(db, row)
    return {'id': row['id'], 'url': '/api/payment-assets/'+row['id']}


@router.get('/api/payment-assets/{asset_id}')
def asset(asset_id: str, request: Request):
    actor = current_user(request)
    with request.app.state.store.transaction() as db:
        row = db.execute('SELECT * FROM payment_assets WHERE id=?', (asset_id,)).fetchone()
        allowed = row and (actor['role'] == 'admin' or row['owner_id'] == actor['id'])
        if row and not allowed and row['purpose'] == 'payment_code':
            allowed = db.execute('SELECT o.id FROM orders o JOIN payment_codes p ON p.id=o.payment_code_id WHERE o.user_id=? AND p.asset_id=? LIMIT 1', (actor['id'], asset_id)).fetchone()
        if not allowed:
            raise HTTPException(404, '资源不存在')
        if not Path(row['path']).is_file():
            raise HTTPException(404, '资源文件不存在')
    return FileResponse(row['path'], media_type='image/png', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/api/admin/payment-codes')
def codes(request: Request):
    require_admin(request)
    with request.app.state.store.transaction() as db:
        return {'items': [dict(r) for r in db.execute('SELECT * FROM payment_codes ORDER BY created_at DESC,id')]}


@router.post('/api/admin/payment-codes', status_code=201)
async def upload_code(request: Request, file: UploadFile = File(...)):
    actor = require_admin(request)
    channel = request.query_params.get('channel', '').strip()
    instructions = request.query_params.get('instructions', '').strip()
    if not channel or len(channel) > 100 or not instructions or len(instructions) > 1000:
        raise HTTPException(422, '请填写收款渠道（1–100 字）和付款说明（1–1000 字）')
    row = await save_asset(request, file, 'payment_code')
    with request.app.state.store.transaction() as db:
        credits.begin(db)
        insert_asset(db, row)
        ident, now = uuid4().hex, utc_now()
        # New versions remain inactive until explicitly enabled.
        db.execute('INSERT INTO payment_codes VALUES (?,?,?,?,0,?,NULL)', (ident, row['id'], channel, instructions, now))
        db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)', (uuid4().hex, actor['id'], 'payment_code_upload', ident, '上传新版本（尚未启用）', '{}', now))
    return {'id': ident}


class CodeStatus(Reason):
    active: bool


@router.post('/api/admin/payment-codes/{code_id}/status')
def code_status(code_id: str, payload: CodeStatus, request: Request):
    actor = require_admin(request)
    with request.app.state.store.transaction() as db:
        credits.begin(db)
        if not db.execute('SELECT id FROM payment_codes WHERE id=?', (code_id,)).fetchone():
            raise HTTPException(404, '收款码不存在')
        now = utc_now()
        if payload.active:
            db.execute('UPDATE payment_codes SET active=0,disabled_at=? WHERE active=1', (now,))
        db.execute('UPDATE payment_codes SET active=?,disabled_at=? WHERE id=?', (int(payload.active), None if payload.active else now, code_id))
        db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)', (uuid4().hex, actor['id'], 'payment_code_enable' if payload.active else 'payment_code_disable', code_id, payload.reason, '{}', now))
    return {'ok': True}
