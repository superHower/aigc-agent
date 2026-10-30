"""Offline migration operations. Never run concurrently with the application."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

from backend.db.task_store import TaskStore, utc_now
from backend.services.passwords import hash_password

OWNED = ('files', 'analyses', 'tasks', 'prompt_categories', 'prompt_templates')


def require_idle(db):
    if db.execute("SELECT 1 FROM tasks WHERE status IN ('queued','running','cancelling') LIMIT 1").fetchone():
        raise ValueError('仍有活动任务；请先等待完成或明确取消，并停止后端进程')


def bootstrap_admin(store, username, password):
    username = username.strip().lower()
    if not re.fullmatch(r'[\u4e00-\u9fffA-Za-z0-9_]{3,24}', username) or username.isdecimal():
        raise ValueError('用户名须为 3–24 位中文、字母、数字或下划线，不能为纯数字')
    password_hash = hash_password(password)
    with store.transaction() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.postgres:
            db.execute('LOCK TABLE users IN EXCLUSIVE MODE')
        if db.execute("SELECT 1 FROM users WHERE role = 'admin'").fetchone():
            raise ValueError('超管已初始化，不允许重复执行或覆盖密码')
        require_idle(db)
        user_id = uuid4().hex
        db.execute('INSERT INTO users (id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)',
                   (user_id, username, password_hash, 'admin', utc_now()))
        for table in OWNED:
            db.execute(f'UPDATE {table} SET owner_id = ? WHERE owner_id IS NULL', (user_id,))
        db.execute("UPDATE files SET purpose = 'mask' WHERE id LIKE 'mask_%'")
        db.execute("UPDATE files SET purpose = 'thumbnail' WHERE id LIKE 'thumb_%'")
        db.execute('INSERT INTO audit_logs VALUES (?,?,?,?,?,?,?)',
                   (uuid4().hex, user_id, 'bootstrap_admin', user_id, '初始化超管与历史归属', '{}', utc_now()))
    return user_id


def validate(store, media_dir=None):
    report = {'counts': {}, 'unowned': {}, 'missing_files': [], 'foreign_key_errors': []}
    with store.transaction() as db:
        db.execute('BEGIN')
        for table in OWNED:
            report['counts'][table] = db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            report['unowned'][table] = db.execute(f'SELECT COUNT(*) FROM {table} WHERE owner_id IS NULL').fetchone()[0]
        if not db.postgres:
            report['foreign_key_errors'] = [tuple(r) for r in db.execute('PRAGMA foreign_key_check')]
        if media_dir is not None:
            paths = [r['path'] for r in db.execute('SELECT path FROM files')]
            paths += [r['input_path'] for r in db.execute("SELECT input_path FROM jobs WHERE input_path != ''")]
            paths += [r['output_path'] for r in db.execute("SELECT output_path FROM jobs WHERE output_path != ''")]
            paths += [r['mask_path'] for r in db.execute("SELECT mask_path FROM jobs WHERE mask_path IS NOT NULL AND mask_path != ''")]
            for path in set(paths):
                if not Path(path).is_file():
                    report['missing_files'].append(path)
    report['ok'] = not (any(report['unowned'].values()) or report['missing_files'] or report['foreign_key_errors'])
    return report


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def backup(database: Path, media: Path, destination: Path):
    if destination.exists():
        raise ValueError('备份目标已存在；请选择新的目录')
    if not database.is_file() or not media.is_dir():
        raise ValueError('数据库或媒体目录不存在')
    if destination.resolve().is_relative_to(media.resolve()):
        raise ValueError('备份目录不能位于媒体目录内')
    # Check the original schema without modifying it.
    with sqlite3.connect(f'{database.resolve().as_uri()}?mode=ro', uri=True) as db:
        require_idle(db)
        destination.mkdir(parents=True)
        with sqlite3.connect(destination / 'database.sqlite') as target:
            db.backup(target)
    shutil.copytree(media, destination / 'media')
    hashes = {p.relative_to(destination).as_posix(): digest(p) for p in destination.rglob('*') if p.is_file()}
    (destination / 'manifest.json').write_text(json.dumps({'created_at': utc_now(), 'media_root': str(media.resolve()), 'sha256': hashes}, indent=2), encoding='utf-8')


def restore(source: Path, database: Path, media: Path):
    # Restore only into new locations; no recursive deletion or silent overwrite.
    if database.exists() or media.exists():
        raise ValueError('恢复目标必须不存在，防止覆盖现有账目或媒体')
    if database.resolve().is_relative_to(media.resolve()) or media.resolve().is_relative_to(database.resolve()):
        raise ValueError('数据库与媒体恢复目标不能互相包含')
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    actual = {p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    if set(manifest['sha256']) != actual or 'database.sqlite' not in actual:
        raise ValueError('备份文件清单校验失败')
    for name, expected in manifest['sha256'].items():
        path = (source / name).resolve()
        if not path.is_relative_to(source.resolve()) or not path.is_file() or digest(path) != expected:
            raise ValueError('备份校验失败')
    database.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / 'database.sqlite', database)
    shutil.copytree(source / 'media', media)
    old_root = Path(manifest['media_root'])

    def relocate(value):
        if isinstance(value, dict):
            return {k: relocate(v) for k, v in value.items()}
        if isinstance(value, list):
            return [relocate(v) for v in value]
        if isinstance(value, str):
            try:
                relative = Path(value).relative_to(old_root)
                return str(media.resolve() / relative)
            except ValueError:
                pass
        return value

    with sqlite3.connect(database) as db:
        for table, key, fields in (
            ('files', 'id', ('path',)),
            ('jobs', 'id', ('input_path', 'output_path', 'mask_path')),
        ):
            for row in db.execute(f"SELECT {key},{','.join(fields)} FROM {table}").fetchall():
                db.execute(f"UPDATE {table} SET {','.join(f'{field}=?' for field in fields)} WHERE {key}=?",
                           tuple(relocate(v) for v in row[1:]) + (row[0],))
        for task_id, rule in db.execute('SELECT id,edit_rule FROM tasks').fetchall():
            db.execute('UPDATE tasks SET edit_rule=? WHERE id=?', (json.dumps(relocate(json.loads(rule))), task_id))


def import_sqlite(source: Path, target: TaskStore):
    if not target.postgres:
        raise ValueError('目标必须为 PostgreSQL')
    # Read-only source: migrate a restored staging copy before importing.
    with sqlite3.connect(f'{source.resolve().as_uri()}?mode=ro', uri=True) as original:
        original.row_factory = sqlite3.Row
        require_idle(original)
        if not original.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone():
            raise ValueError('请先对 SQLite 演练副本执行 migrate 和 init-admin')
        versions = [r[0] for r in original.execute('SELECT version FROM schema_migrations ORDER BY version')]
        tables = ['users', 'sessions', 'system_settings', 'sms_challenges', 'auth_limits', 'files', 'prompt_categories', 'prompt_templates', 'analyses', 'tasks', 'jobs', 'audit_logs', 'channels', 'channel_metadata']
        available = {r[0] for r in original.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        with target.transaction() as db:
            db.execute('BEGIN')
            db.execute('SELECT pg_advisory_xact_lock(401029)')
            if versions != [r[0] for r in db.execute('SELECT version FROM schema_migrations ORDER BY version')]:
                raise ValueError('源库与目标库迁移版本不一致')
            for table in tables:
                if table not in available:
                    continue
                for row in original.execute(f'SELECT * FROM {table}'):
                    values = dict(row)
                    names = list(values)
                    db.execute(f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)}) ON CONFLICT DO NOTHING", tuple(values.values()))
                # Verify all rows, including conflicts. A mismatch rolls back the entire import.
                source_rows = {json.dumps(dict(r), sort_keys=True) for r in original.execute(f'SELECT * FROM {table}')}
                names = [r[1] for r in original.execute(f'PRAGMA table_info({table})')]
                target_rows = {json.dumps(dict(r), sort_keys=True) for r in db.execute(f"SELECT {','.join(names)} FROM {table}")}
                count = db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                if source_rows != target_rows or count != len(source_rows):
                    raise ValueError(f'{table} 记录校验失败；目标数据库必须为空或与源数据完全相同')
