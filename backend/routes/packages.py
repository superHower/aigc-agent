import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.db.task_store import utc_now
from backend.services.access import require_admin
from backend.services import credits

router = APIRouter(tags=['packages'])


class PackageInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    kind: Literal['credits', 'membership']
    price_cents: int = Field(strict=True, ge=1, le=100000000)
    credits: int = Field(strict=True, ge=1, le=10000000)
    membership_days: int = Field(strict=True, ge=0, le=3650)
    status: Literal['draft', 'active', 'inactive'] = 'draft'
    sort_order: int = Field(default=0, strict=True, ge=0, le=100000)

    @model_validator(mode='after')
    def valid_days(self):
        if (self.kind == 'membership') != (self.membership_days > 0):
            raise ValueError('积分包天数必须为零，会员卡天数必须大于零')
        return self


@router.get('/api/packages')
def public_packages(request: Request):
    with request.app.state.store.transaction() as db:
        return {'items': [dict(r) for r in db.execute("SELECT * FROM packages WHERE status='active' ORDER BY sort_order,id")]}


@router.get('/api/admin/packages')
def packages(request: Request):
    require_admin(request)
    with request.app.state.store.transaction() as db:
        return {'items': [dict(r) for r in db.execute('SELECT * FROM packages ORDER BY sort_order,id')]}


def save(request, payload, package_id=None):
    actor = require_admin(request)
    with request.app.state.store.transaction() as db:
        credits.begin(db)
        old = db.execute('SELECT * FROM packages WHERE id=?', (package_id,)).fetchone() if package_id else None
        if package_id and not old:
            raise HTTPException(404, '套餐不存在')
        now = utc_now()
        row = {'id': package_id or uuid4().hex, **payload.model_dump(), 'created_at': old['created_at'] if old else now, 'updated_at': now}
        names = list(row)
        db.execute(f"INSERT INTO packages ({','.join(names)}) VALUES ({','.join('?' for _ in names)}) ON CONFLICT(id) DO UPDATE SET " + ','.join(f'{n}=excluded.{n}' for n in names if n != 'id'), tuple(row.values()))
        db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)', (uuid4().hex, actor['id'], 'package_save', row['id'], '套餐设置', json.dumps({'before': dict(old) if old else None, 'after': row}, ensure_ascii=False), now))
        return row


@router.post('/api/admin/packages', status_code=201)
def create(payload: PackageInput, request: Request):
    return save(request, payload)


@router.put('/api/admin/packages/{package_id}')
def update(package_id: str, payload: PackageInput, request: Request):
    return save(request, payload, package_id)
