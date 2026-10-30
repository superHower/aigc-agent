"""Request observations, never inferred provider charges or raw upstream errors."""
from uuid import uuid4
from datetime import datetime, timezone

from backend.db.task_store import utc_now
from backend.services.image_editor import ImageEditor


def task_durations(store, task_id):
    """Sum observed execution time, including retries but excluding queue time."""
    now = datetime.now(timezone.utc)
    result = {}
    with store.transaction() as db:
        rows = db.execute('''SELECT a.job_id,a.started_at,a.ended_at FROM generation_attempts a
            JOIN jobs j ON j.id=a.job_id WHERE j.task_id=?''', (task_id,)).fetchall()
    for row in rows:
        start = datetime.fromisoformat(row['started_at'])
        end = datetime.fromisoformat(row['ended_at']) if row['ended_at'] else now
        result[row['job_id']] = result.get(row['job_id'], 0) + max(0, (end-start).total_seconds())
    return {job_id: round(seconds, 1) for job_id, seconds in result.items()}


def start(store, job_id, runtime=None, editor=None, retry_round=0):
    config = runtime.config if runtime else {}
    model = config.get('model')
    if not model and editor and hasattr(editor, 'model_registry'):
        model = editor.model_registry.resolved_model('edit')
    ident = uuid4().hex
    with store.transaction() as db:
        db.execute('''INSERT INTO generation_attempts
            (id,job_id,started_at,status,channel_id,channel_name,model,retry_round,dispatched,estimated_cost_cents)
            VALUES (?,?,?,'started',?,?,?,?,?,?)''',
            (ident, job_id, utc_now(), config.get('id'), config.get('name'), model, retry_round, 0 if isinstance(editor, ImageEditor) else None, config.get('estimated_cost_cents')))
    return ident


def dispatched(store, ident):
    with store.transaction() as db:
        db.execute('UPDATE generation_attempts SET dispatched=1 WHERE id=?', (ident,))


def finish(store, ident, status, error=None):
    with store.transaction() as db:
        db.execute('UPDATE generation_attempts SET ended_at=?,status=?,error_code=? WHERE id=? AND ended_at IS NULL', (utc_now(), status, error, ident))
