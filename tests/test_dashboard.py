from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.db.task_store import TaskStore
from backend.routes.dashboard import router
from backend.services.dashboard import dashboard_stats


def seed(store, task_id, created, statuses, steps=None):
    jobs = [dict(id=f'{task_id}_{index}', source_id='src', step=(steps or ['custom_1'] * len(statuses))[index],
                 prompt='private prompt', input_path='private path', mask_path='mask', status=status)
            for index, status in enumerate(statuses)]
    store.create_batch(task_id, ['src'], {}, jobs)
    with store._connect() as connection:
        connection.execute('UPDATE tasks SET created_at = ?, status = ? WHERE id = ?', (created, 'partial_failed', task_id))
        connection.execute('UPDATE jobs SET channel_name = ? WHERE task_id = ?', ('渠道 A', task_id))


def test_dashboard_counts_results_and_excludes_intermediate_steps(tmp_path):
    store = TaskStore(tmp_path / 'tasks.db')
    seed(store, 'today', '2026-10-29T12:00:00+00:00', ['done', 'failed', 'pending', 'cancelled', 'done', 'done'],
         ['custom_1', 'custom_2', 'custom_3', 'custom_4', 'text_T1', 'logo_1'])
    seed(store, 'previous', '2026-10-28T12:00:00+00:00', ['done'])
    stats = dashboard_stats(store, 'day', date(2026, 10, 29), 0)
    assert stats['summary'] == dict(tasks=1, images=4, done=1, failed=1, active=1, cancelled=1,
                                   steps=6, active_tasks=0, retried_tasks=0, success_rate=50.0, estimated_cost=0.3)
    assert stats['previous']['done'] == 1
    assert len(stats['trend']) == 24
    assert stats['trend'][12]['done'] == 1
    assert stats['channels'] == [dict(name='渠道 A', total=4, done=1, failed=1)]
    assert len(stats['recent_tasks']) == 1
    assert 'private' not in str(stats)


def test_dashboard_timezone_and_calendar_boundaries(tmp_path):
    store = TaskStore(tmp_path / 'tasks.db')
    seed(store, 'before', '2026-10-29T06:59:59+00:00', ['done'])
    seed(store, 'start', '2026-10-29T07:00:00+00:00', ['done'])
    seed(store, 'end', '2026-10-30T07:00:00+00:00', ['done'])
    stats = dashboard_stats(store, 'day', date(2026, 10, 29), 420)
    assert stats['summary']['tasks'] == 1
    assert stats['previous']['tasks'] == 1
    assert stats['trend'][0]['done'] == 1
    week = dashboard_stats(store, 'week', date(2026, 10, 29), 0)
    assert (week['start_date'], week['end_date'], len(week['trend'])) == ('2026-10-26', '2026-11-01', 7)
    month = dashboard_stats(store, 'month', date(2024, 2, 20), 0)
    assert len(month['trend']) == 29
    assert month['summary']['success_rate'] is None
    assert month['summary']['tasks'] == 0
    assert month['channels'] == []


def test_dashboard_api_validation_and_full_history(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.state.store = TaskStore(tmp_path / 'tasks.db')
    for index in range(55):
        seed(app.state.store, f't{index}', '2026-10-29T12:00:00+00:00', ['done'])
    with TestClient(app) as client:
        response = client.get('/api/dashboard', params={'period': 'month', 'selected_date': '2026-10-29'})
        assert response.status_code == 200
        assert response.json()['summary']['tasks'] == 55
        assert len(response.json()['recent_tasks']) == 6
        assert client.get('/api/dashboard', params={'period': 'year'}).status_code == 422
        assert client.get('/api/dashboard', params={'selected_date': 'invalid'}).status_code == 422
        assert client.get('/api/dashboard', params={'timezone_offset': 9999}).status_code == 422
