from fastapi import APIRouter, HTTPException, Request

from backend.services.access import current_user
from backend.services.credits import balance
from backend.services.membership import status

router = APIRouter(prefix='/api/account', tags=['account'])


@router.get('/membership')
def membership(request: Request):
    settings = request.app.state.settings
    return status(request.app.state.store, current_user(request)['id'], getattr(settings, 'ordinary_concurrency', 1), getattr(settings, 'member_concurrency', 3))


@router.get('/credits')
def credits(request: Request):
    return balance(request.app.state.store, current_user(request)['id'])


@router.get('/credit-entries')
def entries(request: Request, limit: int = 50, offset: int = 0):
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, '分页参数无效')
    user_id = current_user(request)['id']
    balance(request.app.state.store, user_id)
    with request.app.state.store.transaction() as db:
        return {'items': [dict(r) for r in db.execute('SELECT id,event,available_delta,frozen_delta,created_at FROM credit_entries WHERE user_id=? ORDER BY created_at DESC,id LIMIT ? OFFSET ?', (user_id, limit, offset))]}
