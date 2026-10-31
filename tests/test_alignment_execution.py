"""Import failures and worker liveness, using temporary media and isolated DB."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
import types

import pytest
from sqlalchemy import select, update

from tests.test_saas_isolation import sandbox as sandbox_fixture, headers, submit, install_pipeline
from src import api_server, alignment_execution as execution, worker
from src.models import AlignmentExecution, CreditReservation, Task, TaskStatus, User


sandbox = sandbox_fixture


def snapshot(sandbox):
    async def read():
        async with sandbox.sessions() as db:
            tasks = (await db.execute(select(Task))).scalars().all()
            holds = (await db.execute(select(CreditReservation))).scalars().all()
            return tasks, holds, (await db.get(User, 'alice')).credits
    return asyncio.run(read())


@pytest.mark.parametrize('source', ['upload', 'suno'])
def test_preparation_failure_has_durable_task_and_returns_credit(sandbox, monkeypatch, source):
    original = sandbox.storage.save
    calls = []
    async def save(key, path):
        tasks, holds, available = await asyncio.to_thread(snapshot, sandbox)
        assert len(tasks) == len(holds) == 1
        assert available == 4 and holds[0].state == 'held'
        calls.append(key)
        if len(calls) == 2:
            raise OSError('simulated storage failure')
        return await original(key, path)
    monkeypatch.setattr(sandbox.storage, 'save', save)
    monkeypatch.setattr(api_server, '_dispatch_task', lambda *a: pytest.fail('must not dispatch'))
    if source == 'upload':
        response = submit(sandbox, monkeypatch, source)
        assert response.status_code == 503
        assert 'Unable to save the uploaded files' in response.json()['detail']
        assert 'simulated storage failure' not in response.text
    else:
        with pytest.raises(OSError, match='simulated storage failure'):
            submit(sandbox, monkeypatch, source)
    tasks, holds, available = snapshot(sandbox)
    assert tasks[0].status == TaskStatus.FAILED
    assert available == 5 and holds[0].state == 'released'
    assert not any(sandbox.storage.get_local_path(key).exists() for key in calls)


def test_upload_storage_initialization_failure_does_not_reserve_credits(sandbox, monkeypatch):
    def fail():
        raise ValueError('invalid storage configuration')
    monkeypatch.setattr(api_server, 'get_storage', fail)
    monkeypatch.setattr(api_server, '_dispatch_task', lambda *a: pytest.fail('must not dispatch'))
    response = submit(sandbox, monkeypatch, 'upload')
    assert response.status_code == 503
    assert response.json()['detail'] == 'File storage is unavailable. Please try again later.'
    assert 'invalid storage configuration' not in response.text
    tasks, holds, available = snapshot(sandbox)
    assert tasks == [] and holds == [] and available == 5


def test_same_song_parallel_import_uses_one_credit_and_one_download(sandbox, monkeypatch):
    from src import suno_fetch
    started, release = threading.Event(), threading.Event()
    downloads = []
    monkeypatch.setattr(suno_fetch, 'fetch_song', lambda url: types.SimpleNamespace(
        id='parallel-song', title='test', lyrics='lyrics', raw_prompt='', audio_url='audio', video_url=''))
    def download(song, directory, **kwargs):
        downloads.append(song.id)
        started.set()
        assert release.wait(10)
        path = directory / 'source.mp3'
        path.write_bytes(b'audio')
        return path, None, None, song
    monkeypatch.setattr(suno_fetch, 'download_song', download)
    monkeypatch.setattr(api_server, '_dispatch_task', lambda *a: 'test-queue')
    async def last_credit():
        async with sandbox.sessions() as db:
            (await db.get(User, 'alice')).credits = 1
            await db.commit()
    asyncio.run(last_credit())
    def request():
        return sandbox.client.post('/api/tasks/from-suno', headers=headers(), json={'suno_url':'https://suno.com/s/parallel'})
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(request)
        try:
            assert started.wait(10)
            second = request()
            assert second.status_code == 200, second.text
        finally:
            release.set()
        first = first.result(timeout=10)
    assert first.status_code == 200, first.text
    assert first.json()['task_id'] == second.json()['task_id']
    assert downloads == ['parallel-song']
    tasks, holds, available = snapshot(sandbox)
    assert len(tasks) == len(holds) == 1 and available == 0


@pytest.mark.parametrize('phase', ['preparing', 'queued', 'running'])
def test_expired_managed_execution_refunds_once_without_restarting(sandbox, monkeypatch, phase):
    monkeypatch.setattr(api_server, '_dispatch_task', lambda *a: 'test-queue')
    task_id = submit(sandbox, monkeypatch, 'suno').json()['task_id']
    async def expire():
        async with sandbox.sessions() as db:
            await db.execute(update(AlignmentExecution).where(AlignmentExecution.task_id == task_id).values(
                phase=phase, lease_until=execution.now()-timedelta(seconds=1)))
            await db.commit()
    asyncio.run(expire())
    for _ in range(2):
        response = sandbox.client.get('/api/tasks/'+task_id, headers=headers())
        assert response.json()['status'] == 'failed'
    tasks, holds, available = snapshot(sandbox)
    assert available == 5 and holds[0].state == 'released'
    data = sandbox.client.get('/api/credits', headers=headers()).json()
    assert len([e for e in data['entries'] if e['event'] == 'release']) == 1
    worker._update_task_status(task_id, status='completed', progress=100)
    assert snapshot(sandbox)[0][0].status == TaskStatus.FAILED


def test_live_and_legacy_tasks_are_not_expired_or_visible_to_other_owner(sandbox, monkeypatch):
    monkeypatch.setattr(api_server, '_dispatch_task', lambda *a: 'test-queue')
    task_id = submit(sandbox, monkeypatch, 'suno').json()['task_id']
    async def seed():
        async with sandbox.sessions() as db:
            db.add(Task(id='legacy', user_id='alice', input_mp3_key='old.mp3', input_lyrics_key='old.txt'))
            await db.execute(update(AlignmentExecution).where(AlignmentExecution.task_id == task_id).values(
                lease_until=execution.now()-timedelta(seconds=1)))
            await execution.reconcile(db, 'bob')
            await db.commit()
    asyncio.run(seed())
    assert all(t.status == TaskStatus.PENDING for t in snapshot(sandbox)[0])
    sandbox.client.get('/api/tasks', headers=headers())
    tasks = {t.id:t for t in snapshot(sandbox)[0]}
    assert tasks['legacy'].status == TaskStatus.PENDING
    assert tasks[task_id].status == TaskStatus.FAILED


def test_worker_claim_runs_only_once_and_live_heartbeat_extends_without_progress(sandbox, monkeypatch):
    monkeypatch.setattr(api_server, '_dispatch_task', lambda *a: 'test-queue')
    task_id = submit(sandbox, monkeypatch, 'suno').json()['task_id']
    async def lease():
        async with sandbox.sessions() as db:
            return await db.get(AlignmentExecution, task_id)
    row = asyncio.run(lease())
    ticks = threading.Event()
    monkeypatch.setattr(execution, 'HEARTBEAT_SECONDS', 0.05)
    monkeypatch.setattr(execution, 'LEASE_SECONDS', 0.5)
    original = execution.sync_db
    def observe(action):
        result = original(action)
        if action.__name__ == 'renew' and result:
            ticks.set()
        return result
    monkeypatch.setattr(execution, 'sync_db', observe)
    calls = []
    @execution.managed_worker
    def fake(task_id, mp3_key, lyrics_key, config_dict):
        calls.append(task_id)
        assert ticks.wait(5)
        threading.Event().wait(0.6)  # Exceeds lease period without worker progress.
        live = asyncio.run(lease())
        assert live.lease_until.replace(tzinfo=execution.timezone.utc) > execution.now()
        assert sandbox.client.get('/api/tasks/'+task_id, headers=headers()).json()['status'] == 'pending'
        worker._update_task_status(task_id, status='completed', progress=100)
    config = {'_execution_token':row.token}
    fake(task_id, '', '', config)
    assert asyncio.run(lease()).phase == 'running'
    fake(task_id, '', '', config)
    fake(task_id, '', '', {})
    assert calls == [task_id]
    tasks, holds, available = snapshot(sandbox)
    assert tasks[0].status == TaskStatus.COMPLETED
    assert holds[0].state == 'settled' and available == 4


def test_deleted_preparing_task_cannot_be_dispatched_or_charged_again(sandbox, monkeypatch):
    async def prepare():
        async with sandbox.sessions() as db:
            task = Task(id='deleted', user_id='alice', input_mp3_key='audio', input_lyrics_key='lyrics')
            await api_server._reserve_import(db, task)
            return task
    task = asyncio.run(prepare())
    assert sandbox.client.delete('/api/tasks/deleted', headers=headers()).status_code == 200
    async def dispatch():
        async with sandbox.sessions() as db:
            with pytest.raises(Exception) as error:
                await api_server._commit_and_dispatch(db, task)
            assert error.value.status_code == 409
    asyncio.run(dispatch())
    assert snapshot(sandbox)[2] == 5


def test_expired_worker_cannot_publish_before_owner_reconciliation(sandbox, monkeypatch):
    monkeypatch.setattr(api_server, '_dispatch_task', lambda *a: 'test-queue')
    task_id = submit(sandbox, monkeypatch, 'suno').json()['task_id']
    async def expire():
        async with sandbox.sessions() as db:
            row = await db.get(AlignmentExecution, task_id)
            row.phase = 'running'
            row.lease_until = execution.now()-timedelta(seconds=1)
            await db.commit()
            return row.token
    token = asyncio.run(expire())
    context = execution._token.set(token)
    try:
        with pytest.raises(RuntimeError, match='no longer active'):
            worker._update_task_status(task_id, status='completed', progress=100)
    finally:
        execution._token.reset(context)
    assert snapshot(sandbox)[0][0].status == TaskStatus.PENDING
    sandbox.client.get('/api/credits', headers=headers())
    assert snapshot(sandbox)[2] == 5


def test_shared_source_is_retained_when_changed_lyrics_upload_fails(sandbox, monkeypatch):
    install_pipeline(sandbox, monkeypatch, False)
    first = submit(sandbox, monkeypatch, 'suno').json()
    original = sandbox.storage.save
    async def fail_lyrics(key, path):
        if key.endswith('/source.txt'):
            raise OSError('lyrics upload unavailable')
        return await original(key, path)
    monkeypatch.setattr(sandbox.storage, 'save', fail_lyrics)
    from src import suno_fetch
    monkeypatch.setattr(suno_fetch, 'download_song', lambda *a, **k: pytest.fail('reuse original audio'))
    with pytest.raises(OSError, match='lyrics upload unavailable'):
        sandbox.client.post('/api/tasks/from-suno', headers=headers(), json={
            'suno_url':'https://suno.com/song/test-song-id', 'lyrics_text':'edited lyrics',
        })
    assert sandbox.storage.get_local_path(first['mp3_key']).read_bytes() == b'audio'
    tasks, holds, available = snapshot(sandbox)
    assert sorted(t.status.value for t in tasks) == ['completed', 'failed']
    assert sorted(h.state for h in holds) == ['released', 'settled']
    assert available == 4


def test_cancelled_preparation_releases_held_credit(sandbox):
    async def cancel():
        async with sandbox.sessions() as db:
            task = Task(id='cancelled', user_id='alice', input_mp3_key='audio', input_lyrics_key='lyrics')
            await api_server._reserve_import(db, task)
            with pytest.raises(asyncio.CancelledError):
                async with api_server._prepare_import(db, task, sandbox.storage, []):
                    raise asyncio.CancelledError()
    asyncio.run(cancel())
    tasks, holds, available = snapshot(sandbox)
    assert tasks[0].status == TaskStatus.FAILED
    assert available == 5 and holds[0].state == 'released'


def test_retry_failed_task_reuses_media_and_dispatches(sandbox, monkeypatch):
    install_pipeline(sandbox, monkeypatch, False)
    dispatched = []
    monkeypatch.setattr(api_server, '_dispatch_task', lambda *a: dispatched.append(a) or 'celery-123')

    async def setup_failed_task():
        async with sandbox.sessions() as db:
            task = Task(id='task-retry-test', user_id='alice', status=TaskStatus.FAILED,
                        input_mp3_key='uploads/alice/task-retry-test/audio.mp3',
                        input_lyrics_key='uploads/alice/task-retry-test/lyrics.txt')
            db.add(task)
            await db.commit()
    asyncio.run(setup_failed_task())

    p1 = sandbox.storage.get_local_path('uploads/alice/task-retry-test/audio.mp3')
    p1.parent.mkdir(parents=True, exist_ok=True)
    p1.write_bytes(b'audio-bytes')
    p2 = sandbox.storage.get_local_path('uploads/alice/task-retry-test/lyrics.txt')
    p2.parent.mkdir(parents=True, exist_ok=True)
    p2.write_bytes(b'lyrics-bytes')

    res = sandbox.client.post('/api/tasks/task-retry-test/retry', headers=headers())
    assert res.status_code == 200, res.text
    data = res.json()
    assert data['status'] == 'pending'
    assert data['task_id'] == 'task-retry-test'
    assert len(dispatched) == 1
    assert dispatched[0][0] == 'task-retry-test'

    tasks, holds, available = snapshot(sandbox)
    retry_task = next(t for t in tasks if t.id == 'task-retry-test')
    assert retry_task.status == TaskStatus.PENDING
    assert any(h.operation_id == 'task-retry-test' and h.state == 'held' for h in holds)

    # 4. Attempting to retry a task that is already pending raises 409
    res_conflict = sandbox.client.post('/api/tasks/task-retry-test/retry', headers=headers())
    assert res_conflict.status_code == 409

    # 5. Missing storage files raises 410
    async def make_missing_files_task():
        async with sandbox.sessions() as db:
            t = Task(id='task-missing-files', user_id='alice', status=TaskStatus.FAILED,
                     input_mp3_key='uploads/alice/missing/audio.mp3',
                     input_lyrics_key='uploads/alice/missing/lyrics.txt')
            db.add(t)
            await db.commit()
    asyncio.run(make_missing_files_task())
    res_missing = sandbox.client.post('/api/tasks/task-missing-files/retry', headers=headers())
    assert res_missing.status_code == 410
