import asyncio
import json

import httpx
import pytest
from PIL import Image

from backend.db.task_store import TaskStore, utc_now
from backend.models.schemas import MultiImageRequest
from backend.services.channels import ChannelInput, ChannelPool, ChannelStore
from backend.services.multi_image import plan_multi_image
from backend.services.task_manager import TaskManager


def payload(**updates):
    return MultiImageRequest(**(dict(source_ids=['src'], mode='prompt_group', prompt_group_id='group',
        generation_kind='video') | updates))


@pytest.mark.parametrize('updates', [dict(video_resolution='4k'), dict(video_duration=3),
    dict(video_duration=5.5), dict(video_resolution='2k', video_aspect_ratio='1:1'),
    dict(video_resolution='1080p', video_mode='first_last_frame'), dict(mode='shared'),
    dict(video_last_frame_file_id='tail')])
def test_invalid_video_settings(updates):
    with pytest.raises(ValueError):
        payload(**updates)


@pytest.mark.parametrize('ambiguous', [False, True])
def test_video_durable_create_and_resume(tmp_path, monkeypatch, ambiguous):
    store = TaskStore(tmp_path / 'db.sqlite')
    path = tmp_path / 'source.png'
    Image.new('RGB', (16, 16)).save(path)
    source = dict(id='src', original_name='source.png', path=str(path), mime_type='image/png',
                  width=16, height=16, size=path.stat().st_size, created_at=utc_now())
    store.register_file(source)
    channels = ChannelStore(store)
    channels.save(ChannelInput(name='video', model='minimax-h3', channel_type='video',
        api_key='secret', base_url='https://api.example/v1'))
    channels.save(ChannelInput(name='image', model='image', api_key='other', base_url='https://image.example/v1'))
    _, jobs, chains, rule = plan_multi_image(payload(), {'src': source}, {}, tmp_path,
        {'templates': [dict(id='template', name='pan', content='pan left')]})
    assert jobs[0]['prompt'] == 'pan left'
    assert next(iter(rule['outputs'].values()))['filename'].endswith('.mp4')
    store.create_batch('task', ['src'], rule, jobs)
    requests = []
    fail_poll = True

    def handler(request):
        requests.append(request)
        if request.method == 'POST':
            data = json.loads(request.content)
            assert data['model'] == 'minimax-h3'
            assert data['prompt'] == 'pan left'
            assert len(data['metadata']['referenceImages']) == 1
            assert data['metadata']['referenceImages'][0].startswith('data:image/png;base64,')
            assert data['resolution'] == '768p' and data['ratio'] == '16:9'
            if ambiguous:
                raise httpx.ReadTimeout('secret', request=request)
            return httpx.Response(200, json={'id': 'upstream', 'status': 'queued'})
        if request.url.host == 'media.example':
            assert 'authorization' not in request.headers
            return httpx.Response(200, content=b'\x00\x00\x00\x18ftypisom' + b'0' * 32)
        if fail_poll:
            raise httpx.ReadTimeout('query timeout', request=request)
        return httpx.Response(200, json={'status': 'completed', 'url': 'https://media.example/output.mp4'})

    real_client = httpx.AsyncClient
    monkeypatch.setattr('backend.services.video.httpx.AsyncClient',
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))

    async def interrupt_sleep(_):
        raise RuntimeError('simulate process interruption')

    monkeypatch.setattr('backend.services.video.asyncio.sleep', interrupt_sleep)

    async def run():
        nonlocal fail_poll
        manager = TaskManager(store, None, tmp_path, 1, 1, 1, channel_pool=ChannelPool(channels, tmp_path))
        await manager.create_batch('task', chains, rule)
        await manager.running_tasks['task']
        assert store.get_jobs('task')[0]['status'] == 'failed'
        assert 'secret' not in store.get_jobs('task')[0]['error']
        # Recovery and manual retry both preserve the durable upstream identity.
        store.update_job(jobs[0]['id'], status='processing')
        store.recover_processing()
        assert store.get_jobs('task')[0]['status'] == 'pending'
        store.update_job(jobs[0]['id'], status='failed')
        fail_poll = False
        await manager.retry('task')
        await manager.running_tasks['task']
        assert store.get_jobs('task')[0]['status'] == ('failed' if ambiguous else 'done')
        assert len([r for r in requests if r.method == 'POST']) == 1
        assert all(r.url.host != 'image.example' for r in requests)
    asyncio.run(run())
