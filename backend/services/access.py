from fastapi import HTTPException, Request


def current_user(request: Request):
    user = getattr(request.state, 'user', None)
    if user is None:
        from backend.routes.auth import account
        user = account(request)
    if user is None:
        raise HTTPException(401, '请先登录')
    return user


def require_admin(request: Request):
    user = current_user(request)
    if user['role'] != 'admin':
        raise HTTPException(403, '需要管理员权限')
    return user


def require_owned(request: Request, row, *, purposes=None):
    user = current_user(request)
    if row is None or (user['role'] != 'admin' and row['owner_id'] != user['id']):
        raise HTTPException(404, '资源不存在')
    if purposes is not None and row['purpose'] not in purposes:
        raise HTTPException(404, '资源不存在')
    return row


def require_file(request: Request, file_id: str, *, purposes=None):
    return require_owned(request, request.app.state.store.get_file(file_id), purposes=purposes)


def require_task(request: Request, task_id: str):
    return require_owned(request, request.app.state.store.get_task(task_id))


def visible_job(request: Request, job):
    if job is None:
        raise HTTPException(404, '资源不存在')
    require_task(request, job['task_id'])
    return job
