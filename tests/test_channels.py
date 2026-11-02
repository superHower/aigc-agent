import asyncio
import httpx
import pytest
from openai import APIStatusError
from collections import Counter

from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.db.task_store import TaskStore, utc_now
from backend.routes.channels import router
from backend.services.channels import ChannelInput, ChannelPool, ChannelRuntime, ChannelStore, ChannelUnavailable
from backend.services.task_manager import TaskManager


def test_channel_crud_and_masked_keys(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.channels = ChannelStore(TaskStore(tmp_path / 'tasks.db'))
    @app.middleware('http')
    async def admin_context(request, call_next):
        request.state.user = {'id': 'admin', 'role': 'admin'}
        return await call_next(request)
    client = TestClient(app)
    payload = dict(name='渠道 A', model='image-model', base_url='https://example.com/v1', api_key='secret')
    created = client.post('/api/channels', json=payload)
    assert created.status_code == 200
    channel_id = created.json()['id']
    assert 'secret' not in created.text
    assert 'secret' not in client.get('/api/channels').text
    assert client.put(f'/api/channels/{channel_id}', json=payload | {'api_key': '', 'concurrency': 2}).status_code == 200
    assert app.state.channels.list()[0]['api_key'] == 'secret'
    assert client.post('/api/channels', json=payload | {'concurrency': 0}).status_code == 422
    assert client.post('/api/channels', json=payload | {'name': '  '}).status_code == 422
    assert client.delete(f'/api/channels/{channel_id}').status_code == 200
    assert client.get('/api/channels').json() == {'items': []}
    assert client.delete(f'/api/channels/{channel_id}').status_code == 404


class FakeEditor:
    def __init__(self, root, fail=False):
        self.root = root
        self.fail = fail
        self.calls = 0
        self.active = 0
        self.peak = 0
        self.cancelled = 0

    async def edit(self, **kwargs):
        self.calls += 1
        call = self.calls
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep((0.01 if call == 1 else 10) if self.fail else 0.04)
            if self.fail:
                raise ConnectionError('secret must never appear')
            path = self.root / f"{kwargs['job_id']}.png"
            Image.new('RGB', (10, 10)).save(path)
            return path, {}
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1


def test_channel_types_default_and_routing(tmp_path):
    store = TaskStore(tmp_path / 'typed.db')
    channels = ChannelStore(store)
    payload = dict(name='图片', model='image', base_url='https://example.com/v1', api_key='secret')
    image = channels.save(ChannelInput(**payload))
    video = channels.save(ChannelInput(**{**payload, 'name': '视频', 'model': 'minimax-h3', 'channel_type': 'video'}))
    assert image['channel_type'] == 'image'
    assert video['channel_type'] == 'video'
    assert [row['id'] for row in channels.available()] == [image['id']]
    assert [row['id'] for row in channels.available(channel_type='video')] == [video['id']]
    with pytest.raises(ValueError):
        ChannelInput(**{**payload, 'channel_type': 'unknown'})


def make_pool(tmp_path, count=4, fail=False, concurrency=3):
    store = TaskStore(tmp_path / 'tasks.db')
    channels = ChannelStore(store)
    pool = ChannelPool(channels, tmp_path)
    editors = []
    for i in range(count):
        public = channels.save(ChannelInput(name=f'渠道{i}', model='image', base_url='https://example.com/v1', api_key='secret', concurrency=concurrency))
        row = next(row for row in channels.list() if row['id'] == public['id'])
        editor = FakeEditor(tmp_path, fail=fail and i == 0)
        editors.append(editor)
        pool.runtimes[(row['id'], row['updated_at'])] = ChannelRuntime(row, editor, asyncio.Semaphore(concurrency))
    return store, pool, editors


def test_round_robin_and_failed_channel_isolated(tmp_path):
    async def run():
        store, pool, editors = make_pool(tmp_path, fail=True)
        source = tmp_path / 'source.png'
        Image.new('RGBA', (10, 10)).save(source)
        store.register_file(dict(id='src', original_name='source.png', path=str(source), mime_type='image/png', width=10, height=10, size=1, created_at=utc_now()))
        jobs = [dict(id=f'j{i}', source_id='src', step=f'custom_{i}', prompt='edit', input_path=str(source), mask_path=str(source)) for i in range(10)]
        rule = dict(multi_image=True, size='auto', quality='high', output_format='png', outputs={job['id']: {'variant': True} for job in jobs})
        store.create_batch('task', ['src'], rule, jobs)
        manager = TaskManager(store, None, tmp_path, 1, 1, 5, channel_pool=pool)
        await manager.create_batch('task', {'src': jobs}, rule)
        await manager.running_tasks['task']
        result = store.get_jobs('task')
        assert Counter(row['channel_name'] for row in result) == {'渠道1': 4, '渠道2': 3, '渠道3': 3}
        assert [row['status'] for row in result].count('done') == 10
        assert store.get_task('task')['status'] == 'completed'
        assert store.get_task('task')['auto_retry_count'] == 1
        assert [editor.calls for editor in editors] == [3, 4, 3, 3]
        assert [row['retry_count'] for row in result] == [1, 0, 0, 0, 1, 0, 0, 0, 1, 0]
        assert editors[0].calls == 3
        assert editors[0].cancelled == 2
        assert all('渠道0' in row['error'] and 'secret' not in row['error'] for row in result if row['status'] == 'failed')
        assert len(pool.store.available()) == 4
        assert len(pool.store.available('task')) == 3
        pool.store.reset(pool.store.list()[0]['id'])
        assert len(pool.store.available()) == 4
    asyncio.run(run())


def test_automatic_retry_limit_and_cancel(tmp_path):
    async def run():
        store, pool, editors = make_pool(tmp_path, count=1)
        source = tmp_path / 'source.png'
        Image.new('RGBA', (10, 10)).save(source)
        store.register_file(dict(id='src', original_name='source.png', path=str(source), mime_type='image/png', width=10, height=10, size=1, created_at=utc_now()))
        jobs = [dict(id='j', source_id='src', step='custom_1', prompt='edit', input_path=str(source), mask_path=str(source))]
        rule = dict(multi_image=True, size='auto', quality='high', output_format='png', outputs={'j': {'variant': True}})
        store.create_batch('task', ['src'], rule, jobs)
        manager = TaskManager(store, None, tmp_path, 1, 1, 5, channel_pool=pool)
        # Local postprocessing/input failures leave the channel available, so exercise
        # all retry rounds without reactivating a broken upstream channel.
        calls = []
        def fail_mask(*args):
            calls.append(1)
            raise ValueError('invalid local mask')
        manager._scaled_mask = fail_mask
        await manager.create_batch('task', {'src': jobs}, rule)
        await manager.running_tasks['task']
        assert len(calls) == 3  # Initial attempt plus configured two retries.
        assert store.get_task('task')['auto_retry_count'] == 2
        assert store.get_job('j')['retry_count'] == 2
        assert store.get_task('task')['status'] == 'failed'
        assert editors[0].calls == 0
        store.reset_task_for_retry('task')
        store.set_task_status('task', 'running')
        store.request_cancel('task')
        assert not store.prepare_auto_retry('task')
        assert store.get_job('j')['status'] == 'failed'
    asyncio.run(run())


def test_no_available_channel_does_not_retry(tmp_path):
    async def run():
        store, pool, editors = make_pool(tmp_path, count=1, fail=True)
        source = tmp_path / 'source.png'
        Image.new('RGBA', (10, 10)).save(source)
        store.register_file(dict(id='src', original_name='source.png', path=str(source), mime_type='image/png', width=10, height=10, size=1, created_at=utc_now()))
        jobs = [dict(id='j', source_id='src', step='custom_1', prompt='edit', input_path=str(source), mask_path=str(source))]
        rule = dict(multi_image=True, size='auto', quality='high', output_format='png', outputs={'j': {'variant': True}})
        store.create_batch('task', ['src'], rule, jobs)
        manager = TaskManager(store, None, tmp_path, 1, 1, 5, channel_pool=pool)
        await manager.create_batch('task', {'src': jobs}, rule)
        await manager.running_tasks['task']
        assert editors[0].calls == 1
        assert store.get_task('task')['status'] == 'failed'
        assert store.get_task('task')['auto_retry_count'] == 0
        assert '渠道0' in store.get_job('j')['error']
        await manager.retry('task')
        await manager.running_tasks['task']
        assert editors[0].calls == 1
        assert store.get_task('task')['status'] == 'failed'
        editors[0].fail = False
        new_jobs = [dict(jobs[0], id='new-job')]
        new_rule = dict(rule, outputs={'new-job': {'variant': True}})
        store.create_batch('new-task', ['src'], new_rule, new_jobs)
        await manager.create_batch('new-task', {'src': new_jobs}, new_rule)
        await manager.running_tasks['new-task']
        assert editors[0].calls == 2
        assert store.get_task('new-task')['status'] == 'completed'
    asyncio.run(run())


def test_auto_retry_rebuilds_ocr_dependency_chain(tmp_path):
    async def run():
        store, pool, editors = make_pool(tmp_path, count=2, fail=True)
        source = tmp_path / 'source.png'
        Image.new('RGBA', (10, 10)).save(source)
        store.register_file(dict(id='src', original_name='source.png', path=str(source), mime_type='image/png', width=10, height=10, size=1, created_at=utc_now()))
        jobs = [dict(id='ocr', source_id='src', step='text_1', prompt='edit text', input_path=str(source), mask_path=str(source)),
                dict(id='output', source_id='src', step='custom_1', prompt='edit background', input_path=str(source), mask_path=str(source))]
        rule = dict(multi_image=True, size='auto', quality='high', output_format='png', outputs={'output': {'variant': True}})
        store.create_batch('task', ['src'], rule, jobs)
        seen_inputs = []
        original_edit = editors[1].edit
        async def capture(**kwargs):
            seen_inputs.append((kwargs['job_id'], kwargs['input_path']))
            return await original_edit(**kwargs)
        editors[1].edit = capture
        manager = TaskManager(store, None, tmp_path, 1, 1, 5, channel_pool=pool)
        await manager.create_batch('task', {'src': jobs}, rule)
        await manager.running_tasks['task']
        assert store.get_task('task')['status'] == 'completed'
        assert seen_inputs == [('ocr', source), ('output', tmp_path / 'ocr.png')]
        assert [editor.calls for editor in editors] == [1, 2]
        assert store.get_task('task')['auto_retry_count'] == 1
    asyncio.run(run())


def test_channel_concurrency_shared_between_batches(tmp_path):
    async def run():
        _, pool, editors = make_pool(tmp_path, count=1, concurrency=2)
        runtime = pool.snapshot()[0]
        # Independent callers (including different batch tasks) share this semaphore.
        await asyncio.gather(*(pool.edit(runtime, job_id=f'job{i}') for i in range(9)))
        assert editors[0].peak == 2
        assert editors[0].calls == 9
    asyncio.run(run())


def test_channel_timeout_stops_queued_calls(tmp_path):
    async def run():
        _, pool, editors = make_pool(tmp_path, count=1, concurrency=1)
        runtime = pool.snapshot('timeout-task')[0]
        runtime.config['timeout'] = 0.001
        results = await asyncio.gather(*(pool.edit(runtime, job_id=f'job{i}') for i in range(4)), return_exceptions=True)
        assert all(isinstance(result, ChannelUnavailable) for result in results)
        assert editors[0].calls == 1
        assert editors[0].cancelled == 1
        assert pool.store.available()
        assert not pool.store.available('timeout-task')
    asyncio.run(run())


def test_network_failure_is_task_scoped_and_durable(tmp_path):
    async def run():
        store, pool, editors = make_pool(tmp_path, count=1, concurrency=1)
        first = pool.snapshot('old-task')[0]
        other = pool.snapshot('concurrent-task')[0]
        assert first.semaphore is other.semaphore
        pool.trip(first, ConnectionError('secret network error'))
        assert first.broken.is_set()
        assert not other.broken.is_set()
        assert pool.snapshot('old-task') == []
        assert len(pool.snapshot('new-task')) == 1
        assert not pool.store.list()[0]['last_error']
        reopened = ChannelStore(TaskStore(tmp_path / 'tasks.db'))
        assert not reopened.available('old-task')
        assert len(reopened.available('new-task')) == 1
        await pool.edit(other, job_id='other')
        assert editors[0].calls == 1
    asyncio.run(run())


@pytest.mark.parametrize('status,body', [(402, {}), (403, {'message': '余额不足 secret'}), (429, {'code': 'insufficient_quota'})])
def test_insufficient_balance_pauses_every_task(tmp_path, status, body):
    store, pool, _ = make_pool(tmp_path, count=1)
    first = pool.snapshot('first')[0]
    other = pool.snapshot('other')[0]
    exc = APIStatusError('upstream secret', response=httpx.Response(status, request=httpx.Request('POST', 'https://example.com')), body=body)
    pool.trip(first, exc)
    assert first.broken.is_set() and other.broken.is_set()
    assert not pool.store.available()
    assert not pool.snapshot('new-task')
    assert '余额不足' in pool.store.list()[0]['last_error']
    assert 'secret' not in pool.store.list()[0]['last_error']
    pool.store.reset(first.config['id'])
    assert len(pool.snapshot('new-task')) == 1
