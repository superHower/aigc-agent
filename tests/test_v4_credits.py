import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image

from backend.db.task_store import TaskStore, utc_now
from backend.services import credits
from backend.services.task_manager import TaskManager
from tests.test_v4_migrations import postgres_store
from tests.test_v4_identity import identity_app, signup, image_upload


@pytest.fixture(params=['sqlite', 'postgres'])
def ledger(tmp_path, request):
    store = request.getfixturevalue('postgres_store') if request.param == 'postgres' else TaskStore(tmp_path/'ledger.db')
    with store.transaction() as db:
        credits.begin(db)
        db.execute('INSERT INTO users (id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)', ('user', 'user', 'unused', 'user', utc_now()))
        credits.grant(db, 'user', 3, 'trial', 'initial', (datetime.now(timezone.utc)+timedelta(days=7)).isoformat())
    return store


def create(store, task_id, count, key=None):
    jobs = [dict(id=f'{task_id}_{i}', source_id='source', step='custom_original', prompt='test', mask_path=None, input_path='unused') for i in range(count)]
    rule = {'outputs': {job['id']: {'variant': True} for job in jobs}}
    return store.create_batch(task_id, ['source'], rule, jobs, owner_id='user', billable=True, key=key or task_id, digest='same')


def amounts(store):
    value = credits.balance(store, 'user')
    return value['available'], value['frozen']


def test_concurrent_freeze_no_overdraft_and_idempotency(ledger):
    def submit(task):
        try:
            return create(ledger, task, 2)
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ['first', 'second']))
    assert sum(isinstance(v, tuple) for v in results) == 1
    assert 402 in results and amounts(ledger) == (1, 2)
    winner = next(v[0] for v in results if isinstance(v, tuple))
    assert create(ledger, 'duplicate', 2, winner) == (winner, False)
    with ledger.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM credit_reservations').fetchone()[0] == 2
        with pytest.raises(HTTPException) as error:
            credits.previous(db, 'user', 'create', winner, 'changed')
        assert error.value.status_code == 409


def test_partial_success_auto_retry_manual_retry_and_late_response(ledger):
    create(ledger, 'task', 3)
    ledger.set_task_status('task', 'running')
    ledger.update_job('task_0', status='done', output_path='result.png')
    ledger.update_job('task_0', status='done', output_path='result.png')
    for job in ('task_1', 'task_2'):
        ledger.update_job(job, status='failed')
    assert amounts(ledger) == (0, 2)
    assert ledger.prepare_auto_retry('task')
    assert amounts(ledger) == (0, 2)
    ledger.update_job('task_1', status='done', output_path='result1.png')
    ledger.update_job('task_2', status='failed')
    ledger.finalize_task('task')
    ledger.finalize_task('task')
    assert amounts(ledger) == (1, 0)
    assert credits.retry(ledger, 'user', 'task', None, 'retry-key')
    assert not credits.retry(ledger, 'user', 'task', None, 'retry-key')
    assert amounts(ledger) == (0, 1)
    ledger.request_cancel('task')
    ledger.update_job('task_2', status='done', output_path='late.png')
    assert ledger.get_job('task_2')['status'] == 'cancelled'
    ledger.finalize_task('task')
    assert amounts(ledger) == (1, 0)
    with ledger.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM credit_entries WHERE event='settle'").fetchone()[0] == 2
        assert db.execute('SELECT MAX(round) FROM credit_reservations WHERE job_id=?', ('task_2',)).fetchone()[0] == 2


def test_expired_frozen_trial_and_paid_lots(ledger):
    with ledger.transaction() as db:
        credits.begin(db)
        credits.grant(db, 'user', 5, 'paid', 'paid')
    create(ledger, 'task', 2)
    with ledger.transaction() as db:
        db.execute("UPDATE credit_lots SET expires_at=? WHERE source='trial'", ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
    assert amounts(ledger) == (5, 2)
    ledger.update_job('task_0', status='done', output_path='result.png')
    ledger.update_job('task_1', status='failed')
    ledger.finalize_task('task')
    assert amounts(ledger) == (5, 0)
    with ledger.transaction() as db:
        account = db.execute('SELECT * FROM credit_accounts WHERE user_id=?', ('user',)).fetchone()
        total = db.execute('SELECT SUM(available_delta) AS available,SUM(frozen_delta) AS frozen FROM credit_entries WHERE user_id=?', ('user',)).fetchone()
        assert (total[0], total[1]) == (account['available'], account['frozen'])


def test_recovery_receipt_and_queued_task(ledger, tmp_path):
    create(ledger, 'task', 1)
    output = tmp_path/'result.png'
    Image.new('RGB', (10, 10)).save(output)
    (tmp_path/'receipts').mkdir()
    (tmp_path/'receipts/task_0.json').write_text(json.dumps({'job_id': 'task_0', 'output_path': str(output), 'execution_token': credits.execution_token(ledger, 'task_0')}))
    manager = TaskManager(ledger, None, tmp_path, 1, 1, 0)
    async def run():
        await manager.resume_active_tasks()
        await asyncio.gather(*list(manager.running_tasks.values()))
    asyncio.run(run())
    assert ledger.get_task('task')['status'] == 'completed'
    assert amounts(ledger) == (2, 0)
    asyncio.run(run())
    assert amounts(ledger) == (2, 0)


def test_registration_grant_atomic_and_billed_api(identity_app, monkeypatch):
    from backend.main import app
    store, codes, _ = identity_app
    client, user_id = signup(codes, '13800000009', 'credit_user')
    assert client.get('/api/account/credits').json()['available'] == 3
    source = image_upload(client)
    class FakeManager:
        async def create_batch(self, task_id, chains, rule):
            for chain in chains.values():
                for job in chain:
                    store.update_job(job['id'], status='done', output_path=job['input_path'])
            store.finalize_task(task_id)
    monkeypatch.setattr(app.state, 'manager', FakeManager(), raising=False)
    payload = {'source_ids': [source], 'prompt': 'test', 'aspect_ratios': ['original', '1:1']}
    assert client.post('/api/generate/preview', json=payload).json()['required_credits'] == 2
    headers = {'Idempotency-Key': 'create-key'}
    response = client.post('/api/generate/multi-image', json=payload, headers=headers)
    assert response.status_code == 200, response.text
    assert client.post('/api/generate/multi-image', json=payload, headers=headers).json()['task_id'] == response.json()['task_id']
    assert client.get('/api/account/credits').json()['available'] == 1
    assert client.post('/api/generate/multi-image', json={**payload, 'prompt': 'changed'}, headers=headers).status_code == 409
    assert client.post('/api/generate/multi-image', json=payload, headers={'Idempotency-Key': 'new-request'}).status_code == 402
    with store.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM trial_claims WHERE user_id=?', (user_id,)).fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM tasks WHERE owner_id=?', (user_id,)).fetchone()[0] == 1


def test_same_active_generation_reuses_task_with_new_idempotency_key(identity_app, monkeypatch):
    from backend.main import app
    store, codes, _ = identity_app
    client, user_id = signup(codes, '13800000011', 'active_user')
    source = image_upload(client)
    class ActiveManager:
        async def create_batch(self, task_id, chains, rule):
            return None
    monkeypatch.setattr(app.state, 'manager', ActiveManager(), raising=False)
    payload = {'source_ids': [source], 'prompt': 'same', 'aspect_ratios': ['original']}
    first = client.post('/api/generate/multi-image', json=payload, headers={'Idempotency-Key': 'active-one'})
    second = client.post('/api/generate/multi-image', json=payload, headers={'Idempotency-Key': 'active-two'})
    assert first.status_code == second.status_code == 200
    assert first.json()['task_id'] == second.json()['task_id']
    with store.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM tasks WHERE owner_id=?', (user_id,)).fetchone()[0] == 1


def test_prompt_group_generation_billing_and_snapshot(identity_app, monkeypatch):
    from backend.main import app
    store, codes, _ = identity_app
    client, _ = signup(codes, '13800000019', 'group_user')
    source = image_upload(client)
    templates = [client.post('/api/prompt-templates', json={'name': name, 'content': content}).json()
                 for name, content in [('白底', '改成白底'), ('场景', '改成客厅')]]
    group_payload = {'name': '套图', 'template_ids': [item['id'] for item in templates]}
    group = client.post('/api/prompt-groups', json=group_payload).json()
    class FakeManager:
        async def create_batch(self, task_id, chains, rule):
            for chain in chains.values():
                for job in chain:
                    store.update_job(job['id'], status='done', output_path=job['input_path'])
            store.finalize_task(task_id)
    monkeypatch.setattr(app.state, 'manager', FakeManager(), raising=False)
    payload = {'mode': 'prompt_group', 'source_ids': [source], 'prompt_group_id': group['id']}
    preview = client.post('/api/generate/preview', json=payload)
    assert preview.status_code == 200
    assert preview.json()['images'] == preview.json()['required_credits'] == 2
    response = client.post('/api/generate/multi-image', json=payload, headers={'Idempotency-Key': 'group-create'})
    assert response.status_code == 200, response.text
    task_id = response.json()['task_id']
    assert response.json()['total_jobs'] == response.json()['required_credits'] == 2
    assert client.get('/api/account/credits').json()['available'] == 1
    assert client.post('/api/generate/multi-image', json=payload, headers={'Idempotency-Key': 'group-create'}).json()['task_id'] == task_id
    detail = client.get(f'/api/task/{task_id}').json()
    assert detail['mode'] == 'prompt_group'
    assert [job['target_id'] for job in detail['jobs']] == group_payload['template_ids']
    assert detail['jobs'][0]['prompt'].startswith('改成白底')
    assert detail['jobs'][1]['prompt'].startswith('改成客厅')
    assert client.put(f"/api/prompt-templates/{templates[0]['id']}", json={'name': '新版', 'content': '已修改'}).status_code == 200
    assert client.delete(f"/api/prompt-groups/{group['id']}").status_code == 204
    saved = json.loads(store.get_task(task_id)['edit_rule'])
    assert saved['prompt_group']['templates'][0]['content'] == '改成白底'
    assert client.get(f'/api/task/{task_id}').json()['jobs'][0]['prompt'] == detail['jobs'][0]['prompt']
    assert client.post('/api/generate/preview', json=payload).status_code == 404
    empty = client.post('/api/prompt-groups', json={'name': '空组'}).json()
    assert client.post('/api/generate/preview', json={**payload, 'prompt_group_id': empty['id']}).status_code == 422


def test_executor_cancellation_late_response_and_recovery_release(ledger, tmp_path):
    create(ledger, 'task', 2)
    image = tmp_path/'input.png'
    Image.new('RGB', (10, 10)).save(image)
    with ledger.transaction() as db:
        db.execute('UPDATE jobs SET input_path=?,mask_path=?', (str(image), str(image)))
    class Editor:
        calls = 0
        async def edit(self, **kwargs):
            self.calls += 1
            ledger.request_cancel('task')
            return image, {}
    editor = Editor()
    manager = TaskManager(ledger, editor, tmp_path, 1, 1, 0)
    async def run():
        jobs = [dict(j) for j in ledger.get_jobs('task')]
        await manager.create_batch('task', {'source': jobs}, {'multi_image': True, 'size': 'auto', 'quality': 'high', 'output_format': 'png', 'outputs': {j['id']: {'variant': True} for j in jobs}})
        await asyncio.gather(*list(manager.running_tasks.values()))
    asyncio.run(run())
    assert amounts(ledger) == (3, 0)
    assert editor.calls == 1
    with ledger.transaction() as db:
        assert db.execute('SELECT response_after_cancel FROM generation_attempts').fetchone()[0] == 1
    # Simulate a legacy crash after terminal job states but before release commit.
    create(ledger, 'crash', 1)
    with ledger.transaction() as db:
        db.execute("UPDATE jobs SET status='failed' WHERE task_id='crash'")
        db.execute("UPDATE tasks SET status='failed' WHERE id='crash'")
    assert amounts(ledger) == (2, 1)
    asyncio.run(manager.resume_active_tasks())
    assert amounts(ledger) == (3, 0)


def test_unexpected_failure_drains_siblings_before_release(ledger, tmp_path, monkeypatch):
    create(ledger, 'task', 2)
    manager = TaskManager(ledger, None, tmp_path, 1, 1, 0)
    async def execute(task_id, job, rule):
        if job['id'] == 'task_0':
            raise RuntimeError('unexpected worker error')
        await asyncio.sleep(0.02)
        assert amounts(ledger) == (1, 2)
        ledger.update_job(job['id'], status='done', output_path='result.png')
    monkeypatch.setattr(manager, '_run_job_with_retries', execute)
    jobs = [dict(job) for job in ledger.get_jobs('task')]
    rule = {'multi_image': True, 'outputs': {job['id']: {'variant': True} for job in jobs}}
    async def run():
        with pytest.raises(RuntimeError, match='unexpected worker error'):
            await manager._run_batch('task', {'source': jobs}, rule)
    asyncio.run(run())
    assert ledger.get_task('task')['status'] == 'partial_failed'
    assert ledger.get_job('task_1')['status'] == 'done'
    assert amounts(ledger) == (2, 0)


def test_register_grant_failure_rolls_back_account_and_code(identity_app, monkeypatch):
    from backend.services import identity
    store, codes, _ = identity_app
    identity.issue_sms(store, '13800000010', 'register', 'local')
    original = credits.trial
    def broken(*args):
        original(*args)
        raise RuntimeError('simulated crash')
    monkeypatch.setattr(credits, 'trial', broken)
    with pytest.raises(RuntimeError):
        identity.register(store, 'rollback_user', '13800000010', 'password-123', codes[('13800000010', 'register')])
    with store.transaction() as db:
        assert db.execute("SELECT 1 FROM users WHERE username='rollback_user'").fetchone() is None
        assert db.execute("SELECT 1 FROM trial_claims WHERE phone='13800000010'").fetchone() is None
        assert db.execute("SELECT used_at FROM sms_challenges WHERE phone='13800000010'").fetchone()[0] is None
