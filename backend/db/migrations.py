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
        if 4 not in applied:
            db.executescript('''
                CREATE TABLE credit_accounts (
                    user_id TEXT PRIMARY KEY REFERENCES users(id),
                    available INTEGER NOT NULL DEFAULT 0 CHECK(available>=0),
                    frozen INTEGER NOT NULL DEFAULT 0 CHECK(frozen>=0)
                );
                CREATE TABLE credit_lots (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    source TEXT NOT NULL, original INTEGER NOT NULL CHECK(original>0),
                    available INTEGER NOT NULL CHECK(available>=0), frozen INTEGER NOT NULL DEFAULT 0 CHECK(frozen>=0),
                    expires_at TEXT, created_at TEXT NOT NULL, business_key TEXT NOT NULL UNIQUE
                );
                CREATE INDEX idx_credit_lots_owner ON credit_lots(user_id,expires_at);
                CREATE TABLE trial_claims (
                    phone TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
                    lot_id TEXT NOT NULL UNIQUE REFERENCES credit_lots(id)
                );
                CREATE TABLE credit_entries (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), lot_id TEXT REFERENCES credit_lots(id),
                    event TEXT NOT NULL, available_delta INTEGER NOT NULL, frozen_delta INTEGER NOT NULL,
                    business_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
                );
                CREATE INDEX idx_credit_entries_owner ON credit_entries(user_id,created_at);
                CREATE TABLE credit_reservations (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                    user_id TEXT NOT NULL REFERENCES users(id), round INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('frozen','settled','released')),
                    created_at TEXT NOT NULL, UNIQUE(job_id,round)
                );
                CREATE TABLE credit_allocations (
                    reservation_id TEXT PRIMARY KEY REFERENCES credit_reservations(id),
                    lot_id TEXT NOT NULL REFERENCES credit_lots(id), amount INTEGER NOT NULL CHECK(amount=1)
                );
                CREATE TABLE business_requests (
                    user_id TEXT NOT NULL REFERENCES users(id), operation TEXT NOT NULL, key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES tasks(id),
                    created_at TEXT NOT NULL, PRIMARY KEY(user_id,operation,key)
                );
                CREATE TABLE generation_attempts (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                    started_at TEXT NOT NULL, ended_at TEXT, status TEXT NOT NULL,
                    cost_source TEXT NOT NULL DEFAULT 'unknown', cost_value INTEGER,
                    response_after_cancel INTEGER NOT NULL DEFAULT 0
                );
            ''')
            db.execute('ALTER TABLE tasks ADD COLUMN billable INTEGER NOT NULL DEFAULT 0')
            # Do not retrospectively grant or charge existing accounts/tasks.
            db.execute('INSERT INTO credit_accounts (user_id) SELECT id FROM users')
            if db.postgres:
                db.execute("""CREATE FUNCTION reject_credit_entry_change() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'credit entries are append only'; END; $$""")
                db.execute('CREATE TRIGGER credit_entries_immutable BEFORE UPDATE OR DELETE ON credit_entries FOR EACH ROW EXECUTE FUNCTION reject_credit_entry_change()')
            else:
                for operation in ('UPDATE', 'DELETE'):
                    db.execute(f"CREATE TRIGGER credit_entries_no_{operation.lower()} BEFORE {operation} ON credit_entries BEGIN SELECT RAISE(ABORT, 'credit entries are append only'); END")
            stamp(db, 4)
        if 5 not in applied:
            db.executescript('''
                CREATE TABLE packages (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('credits','membership')),
                    price_cents INTEGER NOT NULL CHECK(price_cents>0),
                    credits INTEGER NOT NULL CHECK(credits>0),
                    membership_days INTEGER NOT NULL CHECK(membership_days>=0),
                    status TEXT NOT NULL CHECK(status IN ('draft','active','inactive')),
                    sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    CHECK((kind='credits' AND membership_days=0) OR (kind='membership' AND membership_days>0))
                );
                CREATE TABLE membership_entries (
                    business_key TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    days INTEGER NOT NULL CHECK(days>0), previous_expires_at TEXT,
                    expires_at TEXT NOT NULL, created_at TEXT NOT NULL
                );
            ''')
            from backend.db.task_store import utc_now
            # Stable seed snapshots allow verification during SQLite -> PostgreSQL import.
            now = '2026-10-29T00:00:00+00:00'
            for ident, name, kind, price, amount, days, order in (
                ('credits30', '30 积分包', 'credits', 600, 30, 0, 0),
                ('credits120', '120 积分包', 'credits', 1800, 120, 0, 1),
                ('weekly', '会员周卡', 'membership', 1200, 100, 7, 2),
                ('monthly', '会员月卡', 'membership', 3600, 360, 30, 3),
            ):
                db.execute("INSERT INTO packages VALUES (?,?,?,?,?,?, 'draft',?,?,?)", (ident, name, kind, price, amount, days, order, now, now))
            stamp(db, 5)
        if 6 not in applied:
            db.executescript('''
                CREATE TABLE payment_assets (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
                    purpose TEXT NOT NULL CHECK(purpose IN ('payment_code','evidence')),
                    path TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE payment_codes (
                    id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES payment_assets(id),
                    channel TEXT NOT NULL, instructions TEXT NOT NULL,
                    active INTEGER NOT NULL CHECK(active IN (0,1)), created_at TEXT NOT NULL, disabled_at TEXT
                );
                CREATE UNIQUE INDEX idx_payment_code_active ON payment_codes(active) WHERE active=1;
                CREATE TABLE orders (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    package_id TEXT NOT NULL REFERENCES packages(id), package_name TEXT NOT NULL,
                    price_cents INTEGER NOT NULL CHECK(price_cents>0), credits INTEGER NOT NULL CHECK(credits>0),
                    membership_days INTEGER NOT NULL CHECK(membership_days>=0),
                    payment_code_id TEXT NOT NULL REFERENCES payment_codes(id),
                    status TEXT NOT NULL CHECK(status IN ('pending','review','needs_info','cancelled','credited')),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, credited_at TEXT
                );
                CREATE INDEX idx_orders_owner ON orders(user_id,created_at);
                CREATE INDEX idx_orders_review ON orders(status,created_at);
                CREATE TABLE order_evidence (
                    id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
                    declared_transaction TEXT NOT NULL, paid_at TEXT NOT NULL,
                    asset_id TEXT REFERENCES payment_assets(id), note TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE payment_receipts (
                    id TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
                    channel TEXT NOT NULL, verified_transaction TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
                    actor_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
                    UNIQUE(channel,verified_transaction)
                );
                CREATE TABLE order_reviews (
                    id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
                    actor_id TEXT NOT NULL REFERENCES users(id), action TEXT NOT NULL,
                    reason TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE financial_requests (
                    actor_id TEXT NOT NULL REFERENCES users(id), operation TEXT NOT NULL, key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, result_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(actor_id,operation,key)
                );
                CREATE TABLE credit_adjustments (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    actor_id TEXT NOT NULL REFERENCES users(id), amount INTEGER NOT NULL CHECK(amount<>0),
                    reason TEXT NOT NULL, created_at TEXT NOT NULL
                );
            ''')
            stamp(db, 6)
        if 7 not in applied:
            for name, definition in (
                ('channel_id', 'TEXT'), ('channel_name', 'TEXT'), ('model', 'TEXT'),
                ('retry_round', 'INTEGER NOT NULL DEFAULT 0'),
                ('dispatched', 'INTEGER'),
                ('estimated_cost_cents', 'INTEGER'),
                ('error_code', 'TEXT'),
            ):
                db.execute(f'ALTER TABLE generation_attempts ADD COLUMN {name} {definition}')
            channel_columns = columns(db, 'channels')
            if channel_columns and 'estimated_cost_cents' not in channel_columns:
                db.execute('ALTER TABLE channels ADD COLUMN estimated_cost_cents INTEGER')
            stamp(db, 7)
        if 8 not in applied:
            db.execute('''CREATE TABLE captcha_challenges (
                id TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires_at TEXT NOT NULL
            )''')
            stamp(db, 8)
        if 9 not in applied:
            db.executescript('''
                CREATE TABLE prompt_groups (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
                    name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(owner_id, name)
                );
                CREATE TABLE prompt_group_members (
                    group_id TEXT NOT NULL REFERENCES prompt_groups(id) ON DELETE CASCADE,
                    template_id TEXT NOT NULL REFERENCES prompt_templates(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    PRIMARY KEY(group_id, template_id), UNIQUE(group_id, position)
                );
            ''')
            stamp(db, 9)


def stamp(db, version):
    from backend.db.task_store import utc_now
    db.execute('INSERT INTO schema_migrations VALUES (?, ?)', (version, utc_now()))
