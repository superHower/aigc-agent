from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import attempts, credits
from backend.services.operations_dashboard import metrics, window
from backend.services.channels import ChannelStore
from tests.test_v4_orders import payments, code, post, submit, verified
from tests.test_v4_identity import identity_app
from tests.test_v4_migrations import postgres_store
from tests.test_v4_credits import ledger, create


def test_event_time_stats_timezone_and_user_isolation(payments):
    store, admin, user, other, actor, buyer = payments
    code(admin)
    ident = post(user, '/api/orders', {'package_id': 'weekly'}).json()['id']
    assert submit(user, ident).status_code == 200
    assert post(admin, f'/api/admin/orders/{ident}/verify', verified()).status_code == 200
    jobs = [dict(id='operation-job', source_id='source', step='custom_1', prompt='hidden', mask_path=None, input_path='hidden')]
    store.create_batch('operation-task', ['source'], {}, jobs, owner_id=buyer['id'], billable=True, key='operation-key', digest='test')
    store.update_job('operation-job', status='done', output_path='hidden.png')
    # Orders/tasks created before selected day, while receipt and settlement occur in it.
    with store.transaction() as db:
        db.execute("UPDATE orders SET created_at='2026-10-28T12:00:00+00:00',credited_at='2026-10-29T07:00:00+00:00'")
        db.execute("UPDATE payment_receipts SET created_at='2026-10-29T07:00:00+00:00'")
        db.execute("UPDATE tasks SET created_at='2026-10-28T12:00:00+00:00'")
        # Ledger immutability is preserved: append a new dated grant, never rewrite existing entries.
        db.execute("INSERT INTO credit_entries VALUES ('boundary-before',?,?, 'settle',0,-1,'boundary-before','2026-10-29T06:59:59+00:00')", (buyer['id'], None))
        db.execute("INSERT INTO credit_entries VALUES ('boundary-start',?,?, 'settle',0,-1,'boundary-start','2026-10-29T07:00:00+00:00')", (buyer['id'], None))
        db.execute("INSERT INTO credit_entries VALUES ('boundary-end',?,?, 'settle',0,-1,'boundary-end','2026-10-30T07:00:00+00:00')", (buyer['id'], None))
    runtime = SimpleNamespace(config={'id': 'channel', 'name': 'snapshot-channel', 'model': 'snapshot-model', 'estimated_cost_cents': 7})
    request_id = attempts.start(store, 'operation-job', runtime, retry_round=1)
    attempts.dispatched(store, request_id); attempts.finish(store, request_id, 'failed', 'channel_unavailable')
    with store.transaction() as db:
        db.execute("UPDATE generation_attempts SET started_at='2026-10-29T08:00:00+00:00' WHERE id=?", (request_id,))
    result = metrics(store, 'day', date(2026, 10, 29), 420)
    assert result['summary']['verified_cents'] == 1200
    assert result['summary']['consumed'] == 1
    assert result['trend'][0]['verified_cents'] == 1200
    assert result['summary']['estimated_cost_cents'] == 7
    assert result['summary']['unknown_cost_attempts'] == 1
    assert result['summary']['retry_attempts'] == 1
    params = {'period': 'day', 'selected_date': '2026-10-29', 'timezone_offset': 420}
    own = user.get('/api/account/usage', params=params)
    assert own.status_code == 200 and own.json()['summary']['consumed'] == 1
    assert 'verified_cents' not in own.text and 'channel' not in own.text
    assert other.get('/api/account/usage', params=params).json()['summary']['consumed'] == 0
    assert admin.get('/api/admin/dashboard', params=params).json()['tasks']['summary']['tasks'] == 0
    for endpoint in ('dashboard', 'audit', 'attempts', 'readiness'):
        assert user.get('/api/admin/'+endpoint).status_code == 403
    record = admin.get('/api/admin/attempts', params={'target_id': 'operation-job'}).json()['items'][0]
    assert record['channel_name'] == 'snapshot-channel' and record['dispatched'] == 1
    assert 'hidden' not in str(record)
    assert admin.get('/api/admin/attempts', params={'limit': 101}).status_code == 422
    assert admin.get('/api/admin/dashboard', params={'period': 'year'}).status_code == 422
    assert window('week', date(2026, 10, 29), 0)[0].date() == date(2026, 10, 26)
    assert (window('month', date(2024, 2, 20), 0)[1]-window('month', date(2024, 2, 20), 0)[0]).days == 29


def test_audit_secrets_user_management_and_public_templates(payments, monkeypatch):
    store, admin, user, _, actor, buyer = payments
    monkeypatch.setattr(app.state, 'channels', ChannelStore(store), raising=False)
    payload = {'name': 'audit-channel', 'model': 'image-model', 'base_url': 'https://example.com/v1', 'api_key': 'NEVER-EXPOSE-THIS-KEY', 'estimated_cost_cents': 5}
    response = admin.post('/api/channels', json=payload)
    assert response.status_code == 200
    channel = response.json()['id']
    assert admin.post(f'/api/channels/{channel}/reset').status_code == 200
    category = admin.post('/api/prompt-categories', json={'name': 'public ops', 'visibility': 'public'}).json()['id']
    template = admin.post('/api/prompt-templates', json={'name': 'public template', 'content': 'template body', 'visibility': 'public', 'category_id': category})
    assert template.status_code == 201
    assert any(r['id'] == template.json()['id'] for r in user.get('/api/prompt-templates').json()['items'])
    assert user.put('/api/prompt-templates/'+template.json()['id'], json={'name': 'bad', 'content': 'bad', 'visibility': 'public'}).status_code == 403
    assert admin.delete('/api/channels/'+channel).status_code == 200
    logs = admin.get('/api/admin/audit').json()['items']
    actions = {r['action'] for r in logs}
    assert {'channel_save', 'channel_delete', 'channel_reset', 'template_create', 'category_create'} <= actions
    assert 'NEVER-EXPOSE-THIS-KEY' not in str(logs)
    assert 'https://example.com' not in str(logs)
    users = admin.get('/api/admin/users').json()
    assert users['total'] == 3
    person = next(r for r in users['items'] if r['id'] == buyer['id'])
    assert person['available'] == 3 and 'password_hash' not in person
    assert admin.post('/api/admin/users/'+buyer['id']+'/status', json={'disabled': True, 'reason': 'operational test'}).status_code == 200
    assert user.get('/api/account/usage').status_code == 401
    assert TestClient(app).get('/api/health').json() == {'status': 'ok'}
    assert TestClient(app).get('/api/admin/readiness').status_code == 401


def test_worker_request_observations_and_estimate_snapshot(ledger, tmp_path):
    import asyncio
    import base64
    from PIL import Image
    from backend.services.channels import ChannelRuntime, FixedModel
    from backend.services.image_editor import ImageEditor
    from backend.services.task_manager import TaskManager
    from backend.services.mask_generator import create_mask
    from tests.test_v4_orders import png
    source, mask = tmp_path/'source.png', tmp_path/'mask.png'
    Image.new('RGB', (30, 30)).save(source)
    create_mask(30, 30, (0, 0, 30, 30), mask)
    calls = []
    async def edit(**kwargs):
        calls.append(kwargs['model'])
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(png()).decode())])
    editor = ImageEditor(SimpleNamespace(images=SimpleNamespace(edit=edit)), FixedModel('observed-model'), tmp_path/'snapshots', tmp_path/'output')
    create(ledger, 'observed-task', 1)
    job = dict(ledger.get_job('observed-task_0')) | {'input_path': str(source), 'mask_path': str(mask)}
    runtime = ChannelRuntime({'id': 'observed-channel', 'name': 'observed', 'model': 'observed-model', 'estimated_cost_cents': 9}, editor, asyncio.Semaphore(1))
    from backend.services.channels import ChannelPool
    pool = ChannelPool(ChannelStore(ledger), tmp_path)
    manager = TaskManager(ledger, editor, tmp_path, 2, 3, 0, channel_pool=pool)
    runtime.config['timeout'] = 2
    manager.assignments['observed-task'] = {'observed-task_0': runtime}
    asyncio.run(manager._run_job_with_retries('observed-task', job, {'size': 'auto', 'quality': 'auto', 'output_format': 'png'}))
    with ledger.transaction() as db:
        row = db.execute('SELECT * FROM generation_attempts').fetchone()
        assert row['dispatched'] == 1 and row['status'] == 'done'
        assert row['model'] == 'observed-model' and row['estimated_cost_cents'] == 9
        assert row['cost_source'] == 'unknown' and row['ended_at']
    assert calls == ['observed-model']
    # Failure before calling the SDK must retain dispatched=0.
    create(ledger, 'not-sent-task', 1)
    job2 = dict(ledger.get_job('not-sent-task_0')) | {'input_path': str(tmp_path/'missing.png'), 'mask_path': str(mask)}
    manager2 = TaskManager(ledger, editor, tmp_path, 2, 3, 0)
    asyncio.run(manager2._run_job_with_retries('not-sent-task', job2, {'size': 'auto', 'quality': 'auto', 'output_format': 'png'}))
    with ledger.transaction() as db:
        row = db.execute("SELECT * FROM generation_attempts WHERE job_id='not-sent-task_0'").fetchone()
        assert row['dispatched'] == 0 and row['status'] == 'failed'
    assert calls == ['observed-model']
