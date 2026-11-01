from datetime import date, datetime, time, timezone
import json
from uuid import uuid4
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.services.access import current_user, require_admin
from backend.db.task_store import utc_now
from backend.services.operations_dashboard import metrics
from backend.services.dashboard import dashboard_stats
from backend.services import membership

router = APIRouter(tags=['operations'])

IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff'}


class StorageCleanupRequest(BaseModel):
    before: date
    confirm: bool = False


def _storage_cleanup_scan(request: Request, cutoff: date) -> dict:
    root = request.app.state.settings.data_dir.resolve()
    boundary = datetime.combine(cutoff, time.min, tzinfo=timezone.utc).timestamp()
    protected: set[Path] = set()
    with request.app.state.store.transaction() as db:
        for row in db.execute("SELECT input_path,output_path,mask_path FROM jobs WHERE status IN ('pending','processing','cancelling')"):
            for key in ('input_path', 'output_path', 'mask_path'):
                if row[key]:
                    try:
                        protected.add(Path(row[key]).resolve())
                    except OSError:
                        pass
    candidates: list[Path] = []
    protected_count = 0
    for path in root.rglob('*'):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        resolved = path.resolve()
        if root not in resolved.parents:
            continue
        if resolved in protected:
            protected_count += 1
            continue
        try:
            if path.stat().st_mtime < boundary:
                candidates.append(path)
        except OSError:
            continue
    size = 0
    for path in candidates:
        try:
            size += path.stat().st_size
        except OSError:
            pass
    return {'before': cutoff.isoformat(), 'count': len(candidates), 'bytes': size, 'protected': protected_count,
            'sample': [str(path.relative_to(root)) for path in candidates[:20]], 'paths': candidates}


@router.get('/api/admin/storage/cleanup-preview')
def storage_cleanup_preview(request: Request, before: date = Query(...)):
    require_admin(request)
    result = _storage_cleanup_scan(request, before)
    result.pop('paths', None)
    return result


@router.post('/api/admin/storage/cleanup')
def storage_cleanup(payload: StorageCleanupRequest, request: Request):
    actor = require_admin(request)
    if not payload.confirm:
        raise HTTPException(422, '请先预览并确认清理范围')
    result = _storage_cleanup_scan(request, payload.before)
    deleted, bytes_deleted = 0, 0
    for path in result['paths']:
        try:
            size = path.stat().st_size
            path.unlink()
            deleted += 1
            bytes_deleted += size
        except FileNotFoundError:
            continue
        except OSError:
            continue
    with request.app.state.store.transaction() as db:
        db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)',
                   (uuid4().hex, actor['id'], 'storage_cleanup', 'media',
                    f'清理 {payload.before.isoformat()} 以前的图片',
                    json.dumps({'before': payload.before.isoformat(), 'deleted': deleted, 'bytes': bytes_deleted}, ensure_ascii=False),
                    utc_now()))
    return {'before': payload.before.isoformat(), 'deleted': deleted, 'bytes': bytes_deleted, 'protected': result['protected']}


@router.get('/api/admin/dashboard')
def dashboard(request: Request, period: Literal['day', 'week', 'month'] = 'week', selected_date: date = Query(default_factory=date.today), timezone_offset: int = Query(default=0, ge=-840, le=840)):
    require_admin(request)
    store = request.app.state.store
    result = metrics(store, period, selected_date, timezone_offset)
    result['tasks'] = dashboard_stats(store, period, selected_date, timezone_offset)
    for key in ('summary', 'previous'):
        result['tasks'][key]['estimated_cost'] = 0
    return result


@router.get('/api/account/usage')
def usage(request: Request, period: Literal['day', 'week', 'month'] = 'week', selected_date: date = Query(default_factory=date.today), timezone_offset: int = Query(default=0, ge=-840, le=840)):
    actor = current_user(request)
    result = metrics(request.app.state.store, period, selected_date, timezone_offset, actor['id'])
    settings = request.app.state.settings
    result['membership'] = membership.status(request.app.state.store, actor['id'], getattr(settings, 'ordinary_concurrency', 1), getattr(settings, 'member_concurrency', 3))
    return result


@router.get('/api/admin/audit')
@router.get('/api/admin/attempts')
def records(request: Request, limit: int = 50, offset: int = 0, target_id: str | None = Query(default=None, max_length=128)):
    require_admin(request)
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, '分页参数无效')
    audit = request.url.path.endswith('/audit')
    table, field = ('audit_logs', 'target_id') if audit else ('generation_attempts', 'job_id')
    where = f' WHERE {field}=?' if target_id else ''
    params = (target_id,) if target_id else ()
    with request.app.state.store.transaction() as db:
        total = db.execute('SELECT COUNT(*) FROM '+table+where, params).fetchone()[0]
        rows = db.execute('SELECT * FROM '+table+where+' ORDER BY '+('created_at' if audit else 'started_at')+' DESC,id LIMIT ? OFFSET ?', (*params, limit, offset))
        return {'items': [dict(r) for r in rows], 'total': total}


@router.get('/api/admin/readiness')
def readiness(request: Request):
    import os
    require_admin(request)
    with request.app.state.store.transaction() as db:
        active_packages = db.execute("SELECT COUNT(*) FROM packages WHERE status='active'").fetchone()[0]
        code = bool(db.execute('SELECT id FROM payment_codes WHERE active=1').fetchone())
    return {'database': 'postgresql' if request.app.state.store.postgres else 'sqlite', 'verification_mode': '图形 CAPTCHA', 'secure_cookie': os.getenv('COOKIE_SECURE', 'false').lower() == 'true', 'active_packages': active_packages, 'payment_code_active': code, 'executor': 'single_process', 'external_acceptance': '收款账户核对、HTTPS 和备份恢复演练需操作者验收；配置状态不代表验收通过。'}
