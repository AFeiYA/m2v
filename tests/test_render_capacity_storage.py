"""Concurrency across independent loops/connections, quota parity and route separation."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading

from fastapi import HTTPException
import pytest
from sqlalchemy import select

from tests.test_saas_isolation import sandbox as sandbox_fixture, headers
from src.models import MotionRenderLease, Task, User, UserPlan, VersionTrash
from src.queue_limiter import reserve_motion, heartbeat_motion, release_motion, now
from src.settings import get_settings

sandbox = sandbox_fixture


def test_parallel_motion_admission_reserves_one_slot_across_event_loops(sandbox, monkeypatch):
    monkeypatch.setattr(get_settings(), 'MAX_CONCURRENT_RENDERS_PER_USER', 1)
    monkeypatch.setattr(get_settings(), 'MAX_GLOBAL_CONCURRENT_RENDERS', 1)
    barrier = threading.Barrier(2)
    def submit(index):
        barrier.wait(timeout=10)
        async def reserve():
            async with sandbox.sessions() as db:
                try:
                    await reserve_motion(db, 'alice', f'job-{index}')
                    await db.commit()
                    return 200
                except HTTPException as exc:
                    await db.rollback()
                    return exc.status_code
        return asyncio.run(reserve())
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, (1, 2))) == [200, 429]
    async def check():
        async with sandbox.sessions() as db:
            assert len((await db.execute(select(MotionRenderLease))).scalars().all()) == 1
    asyncio.run(check())


def test_global_capacity_and_rollback_do_not_leak_slots(sandbox, monkeypatch):
    monkeypatch.setattr(get_settings(), 'MAX_GLOBAL_CONCURRENT_RENDERS', 1)
    async def check():
        async with sandbox.sessions() as db:
            await reserve_motion(db, 'alice', 'rolled-back')
            await db.rollback()
            await reserve_motion(db, 'bob', 'committed')
            await db.commit()
        async with sandbox.sessions() as db:
            with pytest.raises(HTTPException) as exc:
                await reserve_motion(db, 'alice', 'blocked')
            assert exc.value.status_code == 503
            await db.rollback()
            await release_motion(db, 'alice', 'committed')  # not the owner
            await db.commit()
            assert await db.get(MotionRenderLease, 'committed')
            await release_motion(db, 'bob', 'committed')
            await db.commit()
            await reserve_motion(db, 'alice', 'next')
            await db.commit()
    asyncio.run(check())


def test_expired_motion_cannot_renew_and_capacity_can_be_reused(sandbox, monkeypatch):
    monkeypatch.setattr(get_settings(), 'MAX_GLOBAL_CONCURRENT_RENDERS', 1)
    async def check():
        async with sandbox.sessions() as db:
            await reserve_motion(db, 'alice', 'expired')
            await db.commit()
            row = await db.get(MotionRenderLease, 'expired')
            row.lease_until = now() - timedelta(seconds=1)
            await db.commit()
            assert not await heartbeat_motion(db, 'alice', 'expired')
            await db.commit()
            await reserve_motion(db, 'bob', 'replacement')
            await db.commit()
            assert not await heartbeat_motion(db, 'alice', 'expired')
    asyncio.run(check())


def test_trash_and_shared_audio_use_same_quota_accounting(sandbox, monkeypatch):
    from src.storage_accounting import get_storage_accounting, check_storage_quota, PLAN_QUOTAS_BYTES
    monkeypatch.setitem(PLAN_QUOTAS_BYTES, UserPlan.FREE, 4 * 1024 * 1024)
    async def check():
        async with sandbox.sessions() as db:
            for name in ('old', 'new'):
                db.add(Task(id=name, user_id='alice', input_mp3_key='shared.mp3', input_lyrics_key=name+'.txt'))
            await db.flush()
            db.add(VersionTrash(task_id='old', user_id='alice'))
            db.add(VersionTrash(task_id='new', user_id='alice'))
            await db.commit()
            user = await db.get(User, 'alice')
            report = await get_storage_accounting(user, db)
            assert report['usage']['trash_bytes'] == 5 * 1024 * 1024
            assert report['usage']['audio_bytes'] == 0
            assert report['usage']['estimated'] is True
            with pytest.raises(HTTPException) as exc:
                await check_storage_quota(db, user)
            assert exc.value.status_code == 413
    asyncio.run(check())


def test_main_service_does_not_expose_payment_routes(sandbox):
    for path in ('/api/payments/packages', '/api/payments/orders'):
        assert sandbox.client.get(path, headers=headers()).status_code == 404
    assert sandbox.client.post('/api/payments/webhook/mock', json={}).status_code == 404
    assert sandbox.client.post('/api/admin/backup', headers=headers()).status_code == 403


def test_motion_admission_rejection_does_not_leave_queued_job(sandbox, monkeypatch, tmp_path):
    from tests.test_saas_isolation import seed_cloud_motion
    from src.motion_cloud import Workspace
    from src import motion_api
    from src.settings import get_settings
    monkeypatch.setattr(get_settings(), 'MOTION_EXPORT_CREDITS', 0)
    monkeypatch.setattr(get_settings(), 'MOTION_WEBCODECS_CREDITS', 0)
    seed_cloud_motion(sandbox)
    def reject(*args):
        raise HTTPException(403, 'No render allowance')
    monkeypatch.setattr(Workspace, 'before_render', reject)
    root = tmp_path / 'runtime'
    entry = root / 'frontend/local/remotion/index.html'
    entry.parent.mkdir(parents=True)
    entry.write_text('render-test')
    monkeypatch.setattr(motion_api, 'ROOT', root)
    monkeypatch.setattr(motion_api.shutil, 'which', lambda name: '/usr/bin/true')
    assert sandbox.client.post('/api/cloud-motion/director/rules',
        headers=headers(), json={'project_id':'alice_motion'}).status_code == 200
    for _ in range(2):
        response = sandbox.client.post('/api/cloud-motion/render', headers=headers(),
                                      json={'project_id':'alice_motion','height':360,'length':.5})
        assert response.status_code == 403, response.text


def test_postgres_backup_password_not_in_arguments_and_missing_tool_is_honest(tmp_path, monkeypatch):
    from src import backup
    import types
    monkeypatch.setattr('shutil.which', lambda name: None)
    with pytest.raises(NotImplementedError):
        backup.create_database_backup('postgresql+asyncpg://user:dummy@localhost/db', tmp_path)
    monkeypatch.setattr('shutil.which', lambda name: '/usr/bin/'+name)
    def dump(args, **kwargs):
        assert 'dummy' not in str(args)
        assert kwargs['env']['PGPASSWORD'] == 'dummy'
        assert kwargs['timeout'] == 120
        from pathlib import Path
        Path(args[-1]).write_bytes(b'PGDMP test archive')
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr('subprocess.run', dump)
    manifest = backup.create_database_backup('postgresql+asyncpg://user:dummy@localhost/db', tmp_path)
    assert manifest['engine'] == 'postgresql' and manifest['size_bytes'] > 0


def test_lyric_endpoint_respects_motion_slot_and_parallel_submission(sandbox, monkeypatch):
    from tests.test_saas_isolation import seed_editor_song
    from src import export_jobs
    import uuid
    seed_editor_song(sandbox)
    monkeypatch.setattr(get_settings(), 'MAX_CONCURRENT_RENDERS_PER_USER', 1)
    async def no_worker(*args):
        pass
    monkeypatch.setattr(export_jobs, 'run', no_worker)
    async def motion(reserve):
        async with sandbox.sessions() as db:
            if reserve:
                await reserve_motion(db, 'alice', 'motion-capacity')
            else:
                await release_motion(db, 'alice', 'motion-capacity')
            await db.commit()
    asyncio.run(motion(True))
    endpoint = '/api/editor/tasks/editor/lyric-video'
    assert sandbox.client.post(endpoint, json={'request_id':str(uuid.uuid4())}, headers=headers()).status_code == 429
    asyncio.run(motion(False))
    barrier = threading.Barrier(2)
    def submit(index):
        barrier.wait(timeout=10)
        return sandbox.client.post(endpoint, json={'request_id':str(uuid.uuid4())}, headers=headers()).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, (1, 2))) == [200, 429]
