from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from backend.services.access import current_user, require_admin
from backend.services.operations_dashboard import metrics
from backend.services.dashboard import dashboard_stats
from backend.services import membership

router = APIRouter(tags=['operations'])


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
    return {'database': 'postgresql' if request.app.state.store.postgres else 'sqlite', 'sms_mode': os.getenv('SMS_MODE', 'disabled'), 'secure_cookie': os.getenv('COOKIE_SECURE', 'false').lower() == 'true', 'active_packages': active_packages, 'payment_code_active': code, 'executor': 'single_process', 'external_acceptance': '真实短信、收款账户核对、HTTPS 和备份恢复演练需操作者验收；配置状态不代表验收通过。'}
