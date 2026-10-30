"""All ledger changes share the caller's transaction; balances are never negative."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from backend.db.task_store import utc_now


def begin(db):
    db.execute('BEGIN IMMEDIATE')
    if db.postgres:
        # Single executor release: database lock also serializes independent API threads.
        db.execute('SELECT pg_advisory_xact_lock(401031)')


def ensure_account(db, user_id):
    db.execute('INSERT INTO credit_accounts (user_id) VALUES (?) ON CONFLICT (user_id) DO NOTHING', (user_id,))


def entry(db, user_id, lot_id, event, available, frozen, key):
    db.execute('INSERT INTO credit_entries VALUES (?,?,?,?,?,?,?,?)', (uuid4().hex, user_id, lot_id, event, available, frozen, key, utc_now()))
    db.execute('UPDATE credit_accounts SET available=available+?,frozen=frozen+? WHERE user_id=?', (available, frozen, user_id))


def grant(db, user_id, amount, source, key, expires_at=None):
    if amount <= 0:
        raise ValueError('积分数必须大于零')
    ensure_account(db, user_id)
    old = db.execute('SELECT * FROM credit_lots WHERE business_key=?', (key,)).fetchone()
    if old:
        if (old['user_id'], old['original'], old['source'], old['expires_at']) != (user_id, amount, source, expires_at):
            raise HTTPException(409, '业务凭证与原发放参数不一致')
        return old['id']
    lot_id = uuid4().hex
    db.execute('INSERT INTO credit_lots VALUES (?,?,?,?,?,0,?,?,?)', (lot_id, user_id, source, amount, amount, expires_at, utc_now(), key))
    entry(db, user_id, lot_id, 'grant', amount, 0, 'grant:'+key)
    return lot_id


def trial(db, user_id, phone):
    expires = (datetime.now(timezone.utc)+timedelta(days=7)).isoformat()
    if db.postgres:
        db.execute('SELECT pg_advisory_xact_lock(401031)')
    lot = grant(db, user_id, 3, 'trial', 'trial:'+phone, expires)
    db.execute('INSERT INTO trial_claims VALUES (?,?,?)', (phone, user_id, lot))


def expire(db, user_id):
    ensure_account(db, user_id)
    for lot in db.execute('SELECT * FROM credit_lots WHERE user_id=? AND expires_at<=? AND available>0 ORDER BY expires_at,id', (user_id, utc_now())).fetchall():
        amount = lot['available']
        db.execute('UPDATE credit_lots SET available=0 WHERE id=?', (lot['id'],))
        entry(db, user_id, lot['id'], 'expire', -amount, 0, 'expire:'+lot['id'])


def balance(store, user_id):
    with store.transaction() as db:
        begin(db)
        expire(db, user_id)
        result = dict(db.execute('SELECT * FROM credit_accounts WHERE user_id=?', (user_id,)).fetchone())
        result['lots'] = [dict(r) for r in db.execute('SELECT id,source,available,frozen,expires_at FROM credit_lots WHERE user_id=? ORDER BY created_at DESC', (user_id,))]
        return result


def reserve(db, user_id, job_ids):
    expire(db, user_id)
    account = db.execute('SELECT * FROM credit_accounts WHERE user_id=?', (user_id,)).fetchone()
    if account['available'] < len(job_ids):
        raise HTTPException(402, '可用积分不足，未创建任务或冻结积分，请充值后重试')
    lots = [dict(r) for r in db.execute('''SELECT * FROM credit_lots WHERE user_id=? AND available>0
        ORDER BY CASE WHEN expires_at IS NULL THEN 1 ELSE 0 END,expires_at,created_at,id''', (user_id,))]
    for job_id in job_ids:
        lot = next(lot for lot in lots if lot['available'] > 0)
        lot['available'] -= 1
        round_number = db.execute('SELECT COALESCE(MAX(round),0)+1 FROM credit_reservations WHERE job_id=?', (job_id,)).fetchone()[0]
        reservation = uuid4().hex
        db.execute("INSERT INTO credit_reservations VALUES (?,?,?,?,'frozen',?)", (reservation, job_id, user_id, round_number, utc_now()))
        db.execute('INSERT INTO credit_allocations VALUES (?,?,1)', (reservation, lot['id']))
        db.execute('UPDATE credit_lots SET available=available-1,frozen=frozen+1 WHERE id=?', (lot['id'],))
        entry(db, user_id, lot['id'], 'freeze', -1, 1, 'freeze:'+reservation)


def finish(db, job_id, success):
    rows = db.execute('''SELECT r.*,a.lot_id,l.expires_at FROM credit_reservations r
        JOIN credit_allocations a ON a.reservation_id=r.id JOIN credit_lots l ON l.id=a.lot_id
        WHERE r.job_id=? AND r.state='frozen' ''', (job_id,)).fetchall()
    for row in rows:
        expired = row['expires_at'] and row['expires_at'] <= utc_now()
        returned = 0 if success or expired else 1
        state = 'settled' if success else 'released'
        db.execute('UPDATE credit_reservations SET state=? WHERE id=?', (state, row['id']))
        db.execute('UPDATE credit_lots SET available=available+?,frozen=frozen-1 WHERE id=?', (returned, row['lot_id']))
        entry(db, row['user_id'], row['lot_id'], 'settle' if success else 'release', 0 if success else 1, -1, state+':'+row['id'])
        if not success and expired:
            entry(db, row['user_id'], row['lot_id'], 'expire', -1, 0, 'release-expire:'+row['id'])


def reconcile_task(db, task_id, terminal=False):
    for job in db.execute('SELECT id,status FROM jobs WHERE task_id=?', (task_id,)).fetchall():
        if job['status'] == 'done':
            finish(db, job['id'], True)
        elif terminal and job['status'] in ('failed', 'cancelled'):
            finish(db, job['id'], False)


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def previous(db, user_id, operation, key, digest):
    row = db.execute('SELECT * FROM business_requests WHERE user_id=? AND operation=? AND key=?', (user_id, operation, key)).fetchone()
    if row and row['fingerprint'] != digest:
        raise HTTPException(409, '同一幂等键不能更换业务参数')
    return row['task_id'] if row else None


def record_request(db, user_id, operation, key, digest, task_id):
    db.execute('INSERT INTO business_requests VALUES (?,?,?,?,?,?)', (user_id, operation, key, digest, task_id, utc_now()))


def require_key(request):
    key = request.headers.get('Idempotency-Key', '')
    if not 8 <= len(key) <= 128:
        raise HTTPException(422, '请提供 8–128 位 Idempotency-Key')
    return key


def retry(store, user_id, task_id, job_id, key):
    digest = fingerprint({'task_id': task_id, 'job_id': job_id})
    with store.transaction() as db:
        begin(db)
        if previous(db, user_id, 'retry', key, digest):
            return False
        task = db.execute('SELECT * FROM tasks WHERE id=? AND owner_id=?', (task_id, user_id)).fetchone()
        if not task:
            raise HTTPException(404, '任务不存在')
        if task['status'] not in ('completed', 'partial_failed', 'failed', 'cancelled'):
            raise HTTPException(409, '任务尚未结束，请等待自动重试完成')
        jobs = db.execute('SELECT * FROM jobs WHERE task_id=? ORDER BY sequence,id', (task_id,)).fetchall()
        selected = [j for j in jobs if j['status'] in ('failed', 'cancelled') and (not job_id or j['id'] == job_id)]
        if not selected:
            raise HTTPException(409, '没有可重试的失败或取消图片')
        # Normal users only use the multi-image path with no paid OCR edits.
        if not task['billable']:
            raise HTTPException(403, '历史任务不支持此计费入口')
        reconcile_task(db, task_id, True)
        reserve(db, user_id, [j['id'] for j in selected])
        for job in selected:
            db.execute("UPDATE jobs SET status='pending',cancel_requested=0,error=NULL,output_path='',updated_at=? WHERE id=?", (utc_now(), job['id']))
        db.execute("UPDATE tasks SET status='queued',error=NULL,auto_retry_count=0,updated_at=? WHERE id=?", (utc_now(), task_id))
        record_request(db, user_id, 'retry', key, digest, task_id)
    return True


def execution_token(store, job_id):
    with store.transaction() as db:
        row = db.execute('SELECT id FROM credit_reservations WHERE job_id=? ORDER BY round DESC LIMIT 1', (job_id,)).fetchone()
        return row['id'] if row else None


def audit_balances(store):
    problems = []
    with store.transaction() as db:
        begin(db)
        for account in db.execute('SELECT * FROM credit_accounts').fetchall():
            lots = db.execute('SELECT COALESCE(SUM(available),0) AS available,COALESCE(SUM(frozen),0) AS frozen FROM credit_lots WHERE user_id=?', (account['user_id'],)).fetchone()
            entries = db.execute('SELECT COALESCE(SUM(available_delta),0) AS available,COALESCE(SUM(frozen_delta),0) AS frozen FROM credit_entries WHERE user_id=?', (account['user_id'],)).fetchone()
            expected = (account['available'], account['frozen'])
            if expected != (lots['available'], lots['frozen']) or expected != (entries['available'], entries['frozen']):
                problems.append(account['user_id'])
    return problems
