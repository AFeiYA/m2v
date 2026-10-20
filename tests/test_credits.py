"""Credit accounting on the isolated SaaS stack; no real accounts/payments."""
import asyncio
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

# Reuse the existing temporary DB/storage and actual Gradio API mount fixture.
from tests.test_saas_isolation import sandbox, headers, seed_editor_song, install_pipeline, submit  # noqa: F401
from src import api_server, credits, editor_operations, export_jobs, worker
from src.models import CreditEntry, CreditReservation, ExportJob, Task, TaskStatus, User


def history(sandbox, uid='alice'):
    response = sandbox.client.get('/api/credits', headers=headers(uid))
    assert response.status_code == 200, response.text
    return response.json()


def test_alignment_records_opening_reservation_and_delivery_once(sandbox, monkeypatch):
    install_pipeline(sandbox, monkeypatch, False)
    first = submit(sandbox, monkeypatch, 'suno').json()
    data = history(sandbox)
    assert (data['available'], data['reserved']) == (4, 0)
    assert sorted(e['event'] for e in data['entries']) == ['opening', 'reserve', 'settle']
    assert sum(e['amount'] for e in data['entries']) == 4
    repeated = sandbox.client.post('/api/tasks/from-suno', headers=headers(), json={'suno_url':'https://suno.com/song/test-song-id'}).json()
    assert repeated['task_id'] == first['task_id']
    assert history(sandbox)['total'] == 3
    other = history(sandbox, 'bob')
    assert other['available'] == 5 and other['total'] == 1
    assert sandbox.client.get('/api/credits').status_code == 401
    assert sandbox.client.post('/api/credits', headers=headers(), json={'amount':999}).status_code == 405
    assert sandbox.client.delete('/api/tasks/'+first['task_id'], headers=headers()).status_code == 200
    assert history(sandbox)['total'] == 3  # Accounting survives task deletion.


def test_failed_alignment_returns_reserved_credits_once(sandbox, monkeypatch):
    install_pipeline(sandbox, monkeypatch, True)
    task_id = submit(sandbox, monkeypatch, 'suno').json()['task_id']
    worker._update_task_status(task_id, status='completed', progress=100)  # Late stale worker.
    worker_result = sandbox.client.get('/api/tasks/'+task_id, headers=headers()).json()
    assert worker_result['status'] == 'failed'
    from src.task_lifecycle import fail_task_and_refund
    async def repeated():
        async with sandbox.sessions() as db:
            assert await fail_task_and_refund(db, task_id, 'repeated') is False
            await db.commit()
    asyncio.run(repeated())
    data = history(sandbox)
    assert data['available'] == 5 and data['reserved'] == 0
    assert sorted(e['event'] for e in data['entries']) == ['opening', 'release', 'reserve']
    assert sum(e['amount'] for e in data['entries']) == 5


def test_parallel_reservations_cannot_spend_last_credit_twice(sandbox):
    async def exercise():
        async with sandbox.sessions() as db:
            (await db.get(User,'alice')).credits = 1
            await db.commit()
        async def attempt(operation):
            async with sandbox.sessions() as db:
                try:
                    await credits.reserve(db,'alice',operation,'alignment',1)
                    await db.commit()
                    return 'held'
                except HTTPException as exc:
                    await db.rollback()
                    assert exc.status_code == 403
                    return 'rejected'
        assert sorted(await asyncio.gather(attempt('one'),attempt('two'))) == ['held','rejected']
    asyncio.run(exercise())
    data = history(sandbox)
    assert data['available'] == 0 and data['reserved'] == 1
    assert data['total'] == 2
    assert sum(e['amount'] for e in data['entries']) == 0


def render_success(alignment, audio, output, options, progress):
    output.write_bytes(b'credit-video')
    return {'duration':2}


def test_export_is_free_by_default_and_paid_requests_require_price_acceptance(sandbox, monkeypatch):
    seed_editor_song(sandbox)
    monkeypatch.setattr(editor_operations,'render_video',render_success)
    endpoint = '/api/editor/tasks/editor/lyric-video'
    assert sandbox.client.post(endpoint, headers=headers(), json={}).status_code == 200
    assert history(sandbox)['available'] == 5
    assert history(sandbox)['total'] == 1
    monkeypatch.setattr(api_server.settings,'LYRIC_EXPORT_CREDITS',2)
    assert sandbox.client.post(endpoint, headers=headers(), json={}).status_code == 409
    assert sandbox.client.post(endpoint, headers=headers(), json={'accepted_cost':1}).status_code == 409
    assert history(sandbox)['available'] == 5
    body = {'request_id':str(uuid.uuid4()),'accepted_cost':2}
    first = sandbox.client.post(endpoint, headers=headers(), json=body)
    assert first.status_code == 200, first.text
    repeat = sandbox.client.post(endpoint, headers=headers(), json=body)
    assert repeat.json()['task_id'] == first.json()['task_id']
    data = history(sandbox)
    assert data['available'] == 3 and data['reserved'] == 0
    assert data['total'] == 3
    # Insufficient balance rejects before scheduling a render or persisting a job.
    async def count_jobs():
        async with sandbox.sessions() as db:
            return len((await db.execute(select(ExportJob))).scalars().all())
    before = asyncio.run(count_jobs())
    assert sandbox.client.post(endpoint, headers=headers(), json={'accepted_cost':2,'request_id':str(uuid.uuid4())}).status_code == 200
    before += 1
    assert sandbox.client.post(endpoint, headers=headers(), json={'accepted_cost':2,'request_id':str(uuid.uuid4())}).status_code == 403
    assert asyncio.run(count_jobs()) == before
    assert history(sandbox)['available'] == 1


def test_failed_paid_retry_refunds_and_reuses_original_price(sandbox, monkeypatch):
    seed_editor_song(sandbox)
    monkeypatch.setattr(api_server.settings,'LYRIC_EXPORT_CREDITS',2)
    def fail(*args):
        raise RuntimeError('render unavailable')
    monkeypatch.setattr(editor_operations,'render_video',fail)
    job_id = sandbox.client.post('/api/editor/tasks/editor/lyric-video', headers=headers(), json={'accepted_cost':2,'request_id':str(uuid.uuid4())}).json()['task_id']
    data = history(sandbox)
    assert data['available'] == 5 and data['reserved'] == 0
    assert data['total'] == 3
    monkeypatch.setattr(api_server.settings,'LYRIC_EXPORT_CREDITS',3)
    rows = sandbox.client.get('/api/editor/render-jobs', headers=headers()).json()['jobs']
    assert rows[0]['credit_cost'] == 2
    assert sandbox.client.post(f'/api/editor/jobs/{job_id}/retry', headers=headers(), json={'accepted_cost':3}).status_code == 409
    monkeypatch.setattr(editor_operations,'render_video',render_success)
    response = sandbox.client.post(f'/api/editor/jobs/{job_id}/retry', headers=headers(), json={'accepted_cost':2,'request_id':str(uuid.uuid4())})
    assert response.status_code == 200
    data = history(sandbox)
    assert data['available'] == 3 and data['reserved'] == 0
    assert data['total'] == 5
    assert sum(e['amount'] for e in data['entries']) == 3


@pytest.mark.parametrize('action',['interrupt','delete'])
def test_interruption_or_project_deletion_releases_held_credits(sandbox, monkeypatch, action):
    seed_editor_song(sandbox)
    monkeypatch.setattr(api_server.settings,'LYRIC_EXPORT_CREDITS',2)
    async def no_worker(job_id):
        pass
    monkeypatch.setattr(export_jobs,'run',no_worker)
    job_id = sandbox.client.post('/api/editor/tasks/editor/lyric-video', headers=headers(), json={'accepted_cost':2,'request_id':str(uuid.uuid4())}).json()['task_id']
    assert history(sandbox)['available'] == 3
    assert history(sandbox)['reserved'] == 2
    if action == 'delete':
        assert sandbox.client.delete('/api/tasks/editor', headers=headers()).status_code == 200
    else:
        async def expire():
            async with sandbox.sessions() as db:
                row = await db.get(ExportJob,job_id)
                row.lease_until = export_jobs.now()-timedelta(seconds=1)
                await db.commit()
        asyncio.run(expire())
        for _ in range(2):
            assert sandbox.client.get(f'/api/editor/jobs/{job_id}', headers=headers()).json()['status'] == 'interrupted'
    data = history(sandbox)
    assert data['available'] == 5 and data['reserved'] == 0
    assert data['total'] == 3


def test_paid_combined_import_cannot_bypass_export_price(sandbox, monkeypatch):
    monkeypatch.setattr(api_server.settings,'LYRIC_EXPORT_CREDITS',2)
    assert sandbox.client.post('/api/tasks/from-suno', headers=headers(), json={'suno_url':'https://suno.com/s/test','ass_only':False}).status_code == 409
    response = sandbox.client.post('/api/upload', headers=headers(), files={
        'mp3':('song.mp3',b'audio','audio/mpeg'),'lyrics':('song.txt',b'lyrics','text/plain')})
    assert response.status_code == 409
    assert history(sandbox)['available'] == 5


def test_manual_grant_is_recorded_once_and_has_no_public_endpoint(sandbox):
    async def exercise():
        async with sandbox.sessions() as db:
            assert await credits.grant(db,'alice',10,'beta-invite-1') is True
            await db.commit()
        async with sandbox.sessions() as db:
            assert await credits.grant(db,'alice',10,'beta-invite-1') is False
            await db.commit()
        async with sandbox.sessions() as db:
            with pytest.raises(HTTPException):
                await credits.grant(db,'alice',20,'beta-invite-1')
            await db.rollback()
    asyncio.run(exercise())
    data = history(sandbox)
    assert data['available'] == 15 and data['total'] == 2
    assert sum(e['amount'] for e in data['entries']) == 15
    assert history(sandbox,'bob')['available'] == 5


def test_credit_reservation_and_terminal_events_are_idempotent(sandbox):
    async def exercise():
        for _ in range(2):
            async with sandbox.sessions() as db:
                await credits.reserve(db,'alice','same-operation','alignment',1)
                await db.commit()
        for _ in range(2):
            async with sandbox.sessions() as db:
                await credits.finish(db,'alice','same-operation','alignment',success=True)
                await db.commit()
        async with sandbox.sessions() as db:
            assert await credits.finish(db,'alice','same-operation','alignment',success=False) is False
            await db.commit()
    asyncio.run(exercise())
    data = history(sandbox)
    assert data['available'] == 4 and data['reserved'] == 0 and data['total'] == 3


@pytest.mark.parametrize('fault',['missing_subtitle','missing_upload'])
def test_alignment_credits_are_returned_when_deliverables_are_missing(sandbox, monkeypatch, fault):
    import sys
    install_pipeline(sandbox,monkeypatch,False)
    if fault == 'missing_subtitle':
        original = sys.modules['src.main'].process_one
        def partial(**kwargs):
            result = original(**kwargs)
            (kwargs['output_dir'] / 'source.ass').unlink()
            return result
        monkeypatch.setattr(sys.modules['src.main'],'process_one',partial)
    else:
        original_save = sandbox.storage.save
        async def missing(key,path):
            if key.endswith('_alignment.json'):
                return key
            return await original_save(key,path)
        monkeypatch.setattr(sandbox.storage,'save',missing)
    task_id = submit(sandbox,monkeypatch,'suno').json()['task_id']
    state = sandbox.client.get('/api/tasks/'+task_id, headers=headers()).json()
    assert state['status'] == 'failed'
    data = history(sandbox)
    assert data['available'] == 5 and data['reserved'] == 0
    assert sorted(e['event'] for e in data['entries']) == ['opening','release','reserve']


def test_new_user_100_permanent_credits_and_monthly_free_quota_after_consumption(sandbox):
    from src.models import User, UserPlan
    from src.credits import replenish_free_quota, check_monthly_quota_status
    from src.settings import get_settings

    # 1. New user registration starts with 100 permanent credits
    reg_res = sandbox.client.post('/api/auth/register', json={
        'email': 'newartist@example.com', 'username': 'newartist', 'password': 'password123'
    })
    assert reg_res.status_code == 200, reg_res.text
    token = reg_res.json()['access_token']
    auth_h = {'Authorization': f'Bearer {token}'}

    me_res = sandbox.client.get('/api/auth/me', headers=auth_h)
    assert me_res.status_code == 200
    user_data = me_res.json()
    assert user_data['credits'] == 100

    credits_res = sandbox.client.get('/api/credits', headers=auth_h).json()
    assert credits_res['available'] == 100
    assert credits_res['wallet']['permanent_available'] == 100
    assert credits_res['wallet']['subscription_available'] == 0
    # Permanent credits have not been consumed yet (100 >= 20), so monthly quota is not eligible
    assert credits_res['monthly_quota']['eligible'] is False
    assert credits_res['monthly_quota']['claimed'] is False

    uid = user_data['id']

    # 2. While permanent credits >= 20, claim is rejected
    claim_res = sandbox.client.post('/api/credits/claim-monthly-quota', headers=auth_h).json()
    assert claim_res['granted'] is False
    assert claim_res['reason'] == 'has_permanent_credits'

    # 3. Simulate consuming the 100 permanent credits down to 0
    async def consume():
        async with sandbox.sessions() as db:
            u = await db.get(User, uid)
            u.credits = 0
            await db.commit()
    asyncio.run(consume())

    credits_res2 = sandbox.client.get('/api/credits', headers=auth_h).json()
    assert credits_res2['available'] == 0
    assert credits_res2['monthly_quota']['eligible'] is True
    assert credits_res2['monthly_quota']['claimed'] is False

    # 4. Now that permanent credits are consumed, claim the 20 monthly credits
    claim_res2 = sandbox.client.post('/api/credits/claim-monthly-quota', headers=auth_h).json()
    assert claim_res2['granted'] is True
    assert claim_res2['amount'] == 20
    assert claim_res2['balance'] == 20

    # 5. After claiming, balance is 20 (monthly subscription/expiring lot)
    credits_res3 = sandbox.client.get('/api/credits', headers=auth_h).json()
    assert credits_res3['available'] == 20
    assert credits_res3['wallet']['subscription_available'] == 20
    assert credits_res3['wallet']['permanent_available'] == 0
    assert credits_res3['wallet']['next_expiry'] is not None
    assert credits_res3['monthly_quota']['claimed'] is True
    assert credits_res3['monthly_quota']['eligible'] is False

    # 6. Cannot claim twice in the same month
    claim_res3 = sandbox.client.post('/api/credits/claim-monthly-quota', headers=auth_h).json()
    assert claim_res3['granted'] is False
    assert claim_res3['reason'] == 'already_claimed'

