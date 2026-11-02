"""88API MiniMax H3 jobs. A committed create intent must never be replayed."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import mimetypes
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx


def image_data(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0]
    if mime not in ('image/png', 'image/jpeg', 'image/webp') or path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError('视频参考图需为 PNG、JPG 或 WebP，且每张不超过 10MB')
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def key_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


class VideoRunner:
    def __init__(self, manager):
        self.manager = manager
        self.store = manager.store
        self.capacities = {}

    async def run(self, task_id, source_jobs, rule):
        channels = self.manager.channel_pool.store.available(task_id, 'video') if self.manager.channel_pool else []
        jobs = [job for chain in source_jobs.values() for job in chain]
        await asyncio.gather(*(self.job(task_id, job, rule, channels[index % len(channels)] if channels else None)
                               for index, job in enumerate(jobs)))

    async def job(self, task_id, job, rule, channel):
        job_id = job['id']
        current = self.store.get_job(job_id)
        if not current or current['status'] != 'pending':
            return
        if current['cancel_requested']:
            self.store.update_job(job_id, status='cancelled')
            return
        try:
            with self.store.transaction() as db:
                saved = db.execute('SELECT * FROM video_jobs WHERE job_id=?', (job_id,)).fetchone()
            if saved:
                if not saved['upstream_id']:
                    raise ValueError('视频提交结果不明确，请先向服务商核对；系统不会自动重复提交')
                channel = next((c for c in self.manager.channel_pool.store.list()
                                if c['id'] == saved['channel_id'] and c['base_url'] == saved['base_url']
                                and key_hash(c['api_key']) == saved['key_hash']), None)
                if not channel:
                    raise ValueError('请恢复提交此视频时使用的渠道地址及 API Key 后重试查询')
            if not channel:
                raise ValueError('请先配置可用的 MiniMax H3 视频渠道')
            capacity = self.capacities.setdefault((channel['id'], channel['updated_at']), asyncio.Semaphore(channel['concurrency']))
            task = self.store.get_task(task_id)
            owner = task['owner_id'] if task['billable'] else None
            async with self.manager.admission.slot(owner, capacity):
                current = self.store.get_job(job_id)
                if current['cancel_requested']:
                    self.store.update_job(job_id, status='cancelled')
                    return
                if owner:
                    with self.store.transaction() as db:
                        user = db.execute('SELECT disabled FROM users WHERE id=?', (owner,)).fetchone()
                    if not user or user['disabled']:
                        self.store.update_job(job_id, status='cancelled', cancel_requested=1)
                        return
                self.store.update_job(job_id, status='processing', channel_name=channel['name'])
                async with httpx.AsyncClient(timeout=channel['timeout']) as client:
                    headers = {'Authorization': f"Bearer {channel['api_key']}"}
                    base = channel['base_url'].rstrip('/')
                    if not saved:
                        options = rule['video']
                        images = [image_data(Path(path)) for path in options['paths']]
                        metadata = {'referenceImages': images} if options['mode'] == 'omni_reference' else {'firstFrame': images[0]}
                        body = {k: options[k] for k in ('resolution', 'ratio', 'duration')}
                        body.update(model='minimax-h3', prompt=job['prompt'], metadata=metadata)
                        with self.store.transaction() as db:
                            db.execute("INSERT INTO video_jobs VALUES (?,?,?,?,NULL,'submitting')",
                                       (job_id, channel['id'], base, key_hash(channel['api_key'])))
                        response = await client.post(base + '/videos', headers=headers, json=body)
                        response.raise_for_status()
                        upstream_id = response.json().get('id')
                        if not isinstance(upstream_id, str) or not upstream_id:
                            raise ValueError('视频提交未返回任务编号，请向服务商核对后处理')
                        with self.store.transaction() as db:
                            db.execute("UPDATE video_jobs SET upstream_id=?,state='polling' WHERE job_id=?", (upstream_id, job_id))
                    else:
                        upstream_id = saved['upstream_id']
                    # Query failures never create another paid job. Manual retry also uses this ID.
                    for poll in range(1440):
                        if self.store.get_job(job_id)['cancel_requested']:
                            self.store.update_job(job_id, status='cancelled')
                            return
                        try:
                            response = await client.get(base + '/videos/' + quote(upstream_id, safe=''), headers=headers)
                            response.raise_for_status()
                            result = response.json()
                        except (httpx.HTTPError, ValueError):
                            await asyncio.sleep(min(15 + poll * 5, 60))
                            continue
                        if result.get('status') == 'failed':
                            raise ValueError('上游视频生成失败；重试只查询原任务，不会再次提交')
                        if result.get('status') == 'completed':
                            url = result.get('url') or result.get('video_url') or result.get('result_url')
                            if not isinstance(url, str) or urlsplit(url).scheme != 'https':
                                raise ValueError('上游未返回有效的 HTTPS 视频下载地址')
                            output = self.manager.data_dir / 'output' / f'{job_id}.mp4'
                            output.parent.mkdir(parents=True, exist_ok=True)
                            temporary = output.with_suffix('.part')
                            # No API credentials are sent to media hosts, including redirects.
                            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as media:
                                async with media.stream('GET', url) as download:
                                    download.raise_for_status()
                                    total = 0
                                    with temporary.open('wb') as target:
                                        async for chunk in download.aiter_bytes():
                                            total += len(chunk)
                                            if total > 1024**3:
                                                raise ValueError('视频文件超过 1GB 下载限制')
                                            target.write(chunk)
                            with temporary.open('rb') as video_file:
                                signature = video_file.read(32)
                            if total < 12 or b'ftyp' not in signature:
                                raise ValueError('上游返回的文件不是有效 MP4 视频')
                            temporary.replace(output)
                            from backend.services import credits
                            receipts = self.manager.data_dir / 'receipts'
                            receipts.mkdir(exist_ok=True)
                            receipt = receipts / f'{job_id}.json'
                            temp_receipt = receipt.with_suffix('.tmp')
                            temp_receipt.write_text(json.dumps({'job_id': job_id, 'output_path': str(output),
                                'execution_token': credits.execution_token(self.store, job_id)}), encoding='utf-8')
                            temp_receipt.replace(receipt)
                            self.store.update_job(job_id, status='done', output_path=str(output), error=None)
                            return
                        await asyncio.sleep(min(15 + poll * 5, 60))
                    raise ValueError('视频查询已暂停，请重试以继续查询原任务')
        except Exception:
            # Do not expose upstream bodies/URLs/keys. Durable intent protects every failure path.
            self.store.update_job(job_id, status='failed', error='视频未完成，请检查渠道后重试查询；已提交的任务不会重复创建')
