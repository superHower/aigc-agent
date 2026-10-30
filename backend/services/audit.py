import json
from uuid import uuid4
from backend.db.task_store import utc_now


def log(db, actor_id, action, target_id, details=None):
    if not db.execute('SELECT id FROM users WHERE id=?', (actor_id,)).fetchone():
        actor_id = None
    db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)', (uuid4().hex, actor_id, action, target_id, '管理配置变更', json.dumps(details or {}, ensure_ascii=False), utc_now()))
