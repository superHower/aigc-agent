import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image

from backend.services import credits
from backend.services.refinement import prepare
from backend.services.task_manager import TaskManager
from tests.test_v4_credits import ledger
from tests.test_v4_migrations import postgres_store


def test_refinement_keeps_task_and_other_results_and_uses_generated_image(ledger, tmp_path):
    result = tmp_path / 'result.png'
    Image.new('RGB', (16, 12), 'blue').save(result)
    jobs = [dict(id='good', source_id='source', step='custom_original', prompt='old', mask_path='', input_path='missing', status='done', output_path=str(result)),
            dict(id='failed', source_id='source', step='custom_original', prompt='old', mask_path='', input_path='missing', status='failed')]
    rule = {'multi_image': True, 'size': 'auto', 'quality': 'high', 'output_format': 'png', 'reference_paths': ['must-not-be-used'], 'outputs': {'good': {'variant': True}}}
    ledger.create_batch('task', ['source'], rule, jobs, owner_id='user')
    with ledger.transaction() as db:
        db.execute("UPDATE tasks SET status='partial_failed',billable=1 WHERE id='task'")
    assert prepare(ledger, 'task', 'good', 'fix edge', 'refine-key', tmp_path)
    assert not prepare(ledger, 'task', 'good', 'fix edge', 'refine-key', tmp_path)
    assert credits.balance(ledger, 'user')['frozen'] == 1
    with pytest.raises(HTTPException):
        prepare(ledger, 'task', 'good', 'another', 'another-key', tmp_path)
    assert ledger.count_tasks('user') == 1
    calls = []
    class Editor:
        async def edit(self, **kwargs):
            calls.append(kwargs)
            return result, None
    async def run():
        manager = TaskManager(ledger, Editor(), tmp_path, 3, 3, 0)
        chains = {'source': [dict(job) for job in ledger.get_jobs('task')]}
        await manager.create_batch('task', chains, json.loads(ledger.get_task('task')['edit_rule']))
        await manager.running_tasks['task']
    asyncio.run(run())
    assert len(calls) == 1
    assert calls[0]['input_path'] == result
    assert calls[0]['prompt'] == 'fix edge'
    assert calls[0]['reference_paths'] == []
    assert ledger.get_job('good')['output_path'] == str(result)
    assert ledger.get_job('failed')['status'] == 'failed'
    assert ledger.get_job('failed')['retry_count'] == 0
    assert credits.balance(ledger, 'user')['available'] == 2
    assert credits.balance(ledger, 'user')['frozen'] == 0
