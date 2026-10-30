from pathlib import Path


def columns(db, table):
    if db.postgres:
        return {r['column_name'] for r in db.execute(
            'SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?', (table,))}
    return {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}


def migrate(store):
    with store._connect() as db:
        if db.postgres:
            # Serializes simultaneous initializers across processes.
            db.execute('SELECT pg_advisory_xact_lock(401029)')
        else:
            db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
        applied = {r['version'] for r in db.execute('SELECT version FROM schema_migrations')}
        if 1 not in applied:
            db.executescript(Path(__file__).with_name('baseline.sql').read_text(encoding='utf-8'))
            for table, name, definition in (
                ('jobs', 'sequence', 'INTEGER NOT NULL DEFAULT 0'),
                ('jobs', 'channel_name', 'TEXT'),
                ('tasks', 'auto_retry_count', 'INTEGER NOT NULL DEFAULT 0'),
            ):
                if name not in columns(db, table):
                    db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
            stamp(db, 1)
        if 2 not in applied:
            db.executescript('''
                CREATE TABLE users (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, phone TEXT UNIQUE,
                    password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                    disabled INTEGER NOT NULL DEFAULT 0 CHECK(disabled IN (0,1)),
                    membership_expires_at TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    csrf_hash TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT
                );
                CREATE INDEX idx_sessions_user ON sessions(user_id);
                CREATE TABLE audit_logs (
                    id TEXT PRIMARY KEY, actor_id TEXT REFERENCES users(id), action TEXT NOT NULL,
                    target_id TEXT NOT NULL, reason TEXT NOT NULL, details TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            for table in ('files', 'analyses', 'tasks', 'prompt_templates', 'prompt_categories'):
                db.execute(f'ALTER TABLE {table} ADD COLUMN owner_id TEXT REFERENCES users(id)')
                db.execute(f'CREATE INDEX idx_{table}_owner ON {table}(owner_id)')
            db.execute("ALTER TABLE files ADD COLUMN purpose TEXT NOT NULL DEFAULT 'source'")
            for table in ('prompt_templates', 'prompt_categories'):
                db.execute(f"ALTER TABLE {table} ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','public'))")
            stamp(db, 2)
        if 3 not in applied:
            db.executescript('''
                CREATE TABLE sms_challenges (
                    id TEXT PRIMARY KEY, phone TEXT NOT NULL, purpose TEXT NOT NULL CHECK(purpose IN ('register','reset')),
                    code_hash TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, used_at TEXT,
                    status TEXT NOT NULL CHECK(status IN ('pending','sent','failed')),
                    ip_hash TEXT NOT NULL
                );
                CREATE INDEX idx_sms_phone ON sms_challenges(phone,created_at);
                CREATE INDEX idx_sms_ip ON sms_challenges(ip_hash,created_at);
                CREATE TABLE auth_limits (
                    key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires_at TEXT NOT NULL
                );
            ''')
            db.execute('ALTER TABLE prompt_categories ADD COLUMN display_name TEXT')
            db.execute('UPDATE prompt_categories SET display_name=name')
            db.execute('CREATE UNIQUE INDEX idx_category_owner_name ON prompt_categories(owner_id,display_name)')
            stamp(db, 3)


def stamp(db, version):
    from backend.db.task_store import utc_now
    db.execute('INSERT INTO schema_migrations VALUES (?, ?)', (version, utc_now()))
