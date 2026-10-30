"""Append an isolated refinement to an existing task, retaining previous outputs."""
import json
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image

from backend.db.task_store import utc_now
from backend.services import credits
from backend.services.mask_generator import create_mask


def prepare(store, task_id, job_id, prompt, key, data_dir):
    digest = credits.fingerprint({'task_id': task_id, 'job_id': job_id, 'prompt': prompt})
    with store.transaction() as db:
        credits.begin(db)
        task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if credits.previous(db, task['owner_id'], 'refine', key, digest):
            return False
        if task['status'] not in ('completed', 'partial_failed', 'failed', 'cancelled'):
            raise HTTPException(409, '请等待当前任务结束后再优化')
        original = db.execute("SELECT * FROM jobs WHERE id=? AND task_id=? AND status='done'", (job_id, task_id)).fetchone()
        if not original or not original['output_path'] or not Path(original['output_path']).is_file():
            raise HTTPException(409, '只能优化已完成且结果文件存在的图片')
        rule = json.loads(task['edit_rule'])
        if not rule.get('multi_image'):
            raise HTTPException(409, '此历史任务暂不支持进一步优化')
        ident = 'refine_' + uuid4().hex
        with Image.open(original['output_path']) as image:
            width, height = image.size
        mask = data_dir / 'masks' / (ident + '.png')
        create_mask(width, height, (0, 0, width, height), mask)
        output = dict(rule.get('outputs', {}).get(job_id, {}))
        output.update(variant=True, refinement=True, parent_job_id=job_id,
                      filename=f"{Path(output.get('filename', job_id)).stem}-优化-{ident[-6:]}.png", width=width, height=height)
        rule.setdefault('outputs', {})[ident] = output
        rule['execution_job_ids'] = [ident]
        now = utc_now()
        sequence = db.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM jobs WHERE task_id=?', (task_id,)).fetchone()[0]
        db.execute('''INSERT INTO jobs (id,task_id,source_id,step,status,prompt,mask_path,input_path,output_path,sequence,created_at,updated_at)
            VALUES (?,?,?,'custom_refine','pending',?,?,?,'',?,?,?)''',
            (ident, task_id, original['source_id'], prompt, str(mask), original['output_path'], sequence, now, now))
        if task['billable']:
            credits.reserve(db, task['owner_id'], [ident])
        db.execute("UPDATE tasks SET status='queued',error=NULL,auto_retry_count=0,edit_rule=?,updated_at=? WHERE id=?", (json.dumps(rule), now, task_id))
        credits.record_request(db, task['owner_id'], 'refine', key, digest, task_id)
    return True
