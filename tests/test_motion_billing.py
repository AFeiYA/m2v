"""Paid Motion exports use the shared ledger; no live accounts or media."""
import asyncio
import uuid
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from tests.test_saas_isolation import sandbox, seed_cloud_motion, headers  # noqa: F401
from src import motion_billing as billing
from src.motion_api import RenderRequest
from src.models import User, MotionExportRequest, MotionRenderLease, CreditReservation, CreditEntry, VideoExport
from src.settings import get_settings


@pytest.fixture
def paid(sandbox,monkeypatch):
    monkeypatch.setattr(get_settings(),'MOTION_EXPORT_CREDITS',2)
    monkeypatch.setattr(get_settings(),'MOTION_WEBCODECS_CREDITS',2)
    seed_cloud_motion(sandbox)
    return sandbox


def request(**overrides):
    base = {'project_id':'alice_motion','request_id':uuid.uuid4(),'accepted_cost':2,'length':.5}
    base.update(overrides)
    return RenderRequest(**base)


def test_hold_publish_and_duplicate_finish_are_atomic_and_idempotent(paid):
    async def run():
        req=request()
        async with paid.sessions() as db:
            first=await billing.admit(db,'alice','alice_motion','candidate',req);await db.commit()
            job=first['id'];assert (await db.get(User,'alice',populate_existing=True)).credits==3
        async with paid.sessions() as db:
            assert (await billing.admit(db,'alice','alice_motion','new-candidate',req))['replay'];await db.commit()
            assert (await db.get(User,'alice',populate_existing=True)).credits==3
        async with paid.sessions() as db:
            await billing.publish(db,'alice',job,'alice_motion','results/test.mp4','poster',{});await db.commit()
        async with paid.sessions() as db:
            await billing.finish(db,'alice',job,True);await billing.finish(db,'alice',job,False);await db.commit()
            assert (await db.get(User,'alice',populate_existing=True)).credits==3
            assert (await db.get(MotionExportRequest,job)).state=='done'
            assert await db.get(VideoExport,job)
            entries=(await db.execute(select(CreditEntry).where(CreditEntry.operation_id==job))).scalars().all()
            assert {e.event for e in entries}=={'reserve','settle'}
    asyncio.run(run())


@pytest.mark.parametrize('cancelled',[False,True])
def test_failed_or_cancelled_render_refunds_once_and_never_publishes(paid,cancelled):
    async def run():
        async with paid.sessions() as db:
            job=(await billing.admit(db,'alice','alice_motion','candidate',request()))['id'];await db.commit()
        async with paid.sessions() as db:
            await billing.finish(db,'alice',job,cancelled=cancelled);await billing.finish(db,'alice',job);await db.commit()
            assert (await db.get(User,'alice',populate_existing=True)).credits==5
            assert await db.get(MotionRenderLease,job) is None
        async with paid.sessions() as db:
            with pytest.raises(RuntimeError):
                await billing.publish(db,'alice',job,'alice_motion','results/test.mp4','poster',{})
            await db.rollback()
    asyncio.run(run())


def test_expired_worker_releases_hold_and_late_publish_is_fenced(paid):
    async def run():
        async with paid.sessions() as db:
            job=(await billing.admit(db,'alice','alice_motion','candidate',request()))['id'];await db.commit()
        async with paid.sessions() as db:
            await db.execute(update(MotionExportRequest).where(MotionExportRequest.id==job).values(lease_until=billing.now()-timedelta(seconds=1)));await db.commit()
        async with paid.sessions() as db:
            await billing.reconcile(db,'alice');await db.commit()
            assert (await db.get(User,'alice',populate_existing=True)).credits==5
            assert (await db.get(MotionExportRequest,job)).state=='interrupted'
        async with paid.sessions() as db:
            assert not await billing.heartbeat(db,'alice',job)
            with pytest.raises(RuntimeError):await billing.publish(db,'alice',job,'alice_motion','results/test.mp4','poster',{})
    asyncio.run(run())


def test_insufficient_balance_and_rejected_price_leave_no_hold_or_slot(paid):
    async def run():
        for req in [RenderRequest(project_id='alice_motion',accepted_cost=2),RenderRequest(project_id='alice_motion',request_id=uuid.uuid4(),accepted_cost=1)]:
            async with paid.sessions() as db:
                with pytest.raises(HTTPException) as error:await billing.admit(db,'alice','alice_motion','candidate',req)
                assert error.value.status_code==409;await db.rollback()
        async with paid.sessions() as db:
            await db.execute(update(User).where(User.id=='alice').values(credits=1));await db.commit()
        async with paid.sessions() as db:
            with pytest.raises(HTTPException) as error:await billing.admit(db,'alice','alice_motion','candidate',request())
            assert error.value.status_code==403;await db.rollback()
        async with paid.sessions() as db:
            assert not (await db.execute(select(MotionRenderLease))).scalars().all()
            assert not (await db.execute(select(CreditReservation))).scalars().all()
    asyncio.run(run())


def test_parallel_duplicate_requests_hold_once_and_keep_price_snapshot(paid,monkeypatch):
    req=request()
    def submit(_):
        async def run():
            async with paid.sessions() as db:
                result=await billing.admit(db,'alice','alice_motion','candidate',req);await db.commit();return result
        return asyncio.run(run())
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(submit,range(2)))
    assert results[0]['id']==results[1]['id']
    assert sorted(r['replay'] for r in results)==[False,True]
    monkeypatch.setattr(get_settings(),'MOTION_EXPORT_CREDITS',4)
    assert submit(0)['replay']
    async def check():
        async with paid.sessions() as db:
            assert (await db.get(User,'alice')).credits==3
            assert (await db.get(MotionExportRequest,results[0]['id'])).cost==2
    asyncio.run(check())


def test_request_id_cannot_be_rebound_to_new_settings(paid):
    async def run():
        req=request()
        async with paid.sessions() as db:
            await billing.admit(db,'alice','alice_motion','candidate',req);await db.commit()
        async with paid.sessions() as db:
            with pytest.raises(HTTPException) as error:await billing.admit(db,'alice','alice_motion','candidate',req.model_copy(update={'aspect':'9:16'}))
            assert error.value.status_code==409
    asyncio.run(run())


def test_monthly_credits_expiring_during_render_are_not_refunded_as_permanent(paid):
    async def run():
        from src import credits
        from src.credit_lots import CreditLot
        async with paid.sessions() as db:
            await credits.grant(db,'alice',2,'monthly',lot_origin='monthly',expires_at=billing.now()+timedelta(hours=1))
            await db.commit()
        async with paid.sessions() as db:
            job=(await billing.admit(db,'alice','alice_motion','candidate',request()))['id'];await db.commit()
            assert (await db.get(User,'alice',populate_existing=True)).credits==5
        async with paid.sessions() as db:
            await db.execute(update(CreditLot).where(CreditLot.user_id=='alice').values(expires_at=billing.now()-timedelta(seconds=1)))
            await db.commit()
        async with paid.sessions() as db:
            await billing.finish(db,'alice',job);await db.commit()
            assert (await db.get(User,'alice',populate_existing=True)).credits==5
    asyncio.run(run())


def test_publication_failure_rolls_back_export_and_settlement_then_refunds(paid,monkeypatch):
    async def run():
        async with paid.sessions() as db:
            job=(await billing.admit(db,'alice','alice_motion','candidate',request()))['id'];await db.commit()
        from src import credits
        original=credits.finish
        async def broken(*args,**kwargs):raise RuntimeError('simulated ledger failure')
        monkeypatch.setattr(credits,'finish',broken)
        async with paid.sessions() as db:
            with pytest.raises(RuntimeError):await billing.publish(db,'alice',job,'alice_motion','test.mp4','poster',{})
            await db.rollback()
        monkeypatch.setattr(credits,'finish',original)
        async with paid.sessions() as db:
            assert await db.get(VideoExport,job) is None
            await billing.finish(db,'alice',job);await db.commit()
            assert (await db.get(User,'alice',populate_existing=True)).credits==5
    asyncio.run(run())


def test_paid_http_render_publishes_charges_once_and_replays_across_restart(paid,monkeypatch,tmp_path):
    import time
    import threading
    from src import motion_api, motion_cloud
    runtime=tmp_path/'runtime';entry=runtime/'frontend/local/remotion/index.html'
    entry.parent.mkdir(parents=True);entry.write_text('synthetic test renderer')
    monkeypatch.setattr(motion_api,'ROOT',runtime)
    monkeypatch.setattr(motion_api.shutil,'which',lambda name:'/test/node')
    release=threading.Event(); started=[]
    class Child:
        def __init__(self,args):
            self.path=Path(args[-1]);started.append(self.path);self.stdout=self.lines()
        def lines(self):
            yield 'PROGRESS 0/15\n'
            assert release.wait(5)
            yield 'PROGRESS 15/15\n'
        def wait(self):self.path.write_bytes(b'synthetic video'*200);return 0
    from pathlib import Path
    monkeypatch.setattr(motion_api.subprocess,'Popen',lambda args,**kw:Child(args))
    base='/api/cloud-motion'
    assert paid.client.post(base+'/director/rules',headers=headers(),json={'project_id':'alice_motion'}).status_code==200
    body={'project_id':'alice_motion','request_id':str(uuid.uuid4()),'accepted_cost':2,'height':360,'length':.5}
    first=paid.client.post(base+'/render',headers=headers(),json=body)
    assert first.status_code==202,first.text
    job=first.json()['id']
    try:
        again=paid.client.post(base+'/render',headers=headers(),json=body)
        assert again.status_code==202 and again.json()['id']==job
        credits_response=paid.client.get('/api/credits',headers=headers()).json()
        assert credits_response['available']==3, credits_response
        assert paid.client.get(base+f'/render/{job}',headers=headers('bob')).status_code==404
    finally:release.set()
    for _ in range(300):
        result=paid.client.get(base+f'/render/{job}',headers=headers()).json()
        if result['status'] in ('done','failed'):break
        time.sleep(.01)
    assert result['status']=='done',result
    assert len(started)==1
    assert paid.client.get('/api/exports',headers=headers()).json()['total']==1
    assert paid.client.get('/api/credits',headers=headers()).json()['available']==3
    motion_cloud._workspaces.clear()
    replay=paid.client.post(base+'/render',headers=headers(),json=body)
    assert replay.status_code==202 and replay.json()['id']==job
    assert paid.client.get(base+f'/render/{job}/download',headers=headers()).status_code==200
    assert len(started)==1


def test_metadata_only_cloud_export_is_retired_without_charging_or_writing(paid):
    from src.motion_cloud import workspace_for
    job_id = 'a' * 32
    response = paid.client.post('/api/cloud-motion/render/record_webcodecs', headers=headers(), json={
        'project_id':'alice_motion', 'job_id':job_id, 'file_size':1024000,
    })
    assert response.status_code == 410
    workspace = workspace_for('alice', paid.storage)
    assert not list(workspace.root.glob(f'**/{job_id}_status.json'))
    assert paid.client.get('/api/credits',headers=headers()).json()['available'] == 5


def test_busy_engine_waits_without_creating_or_charging_a_request(paid):
    async def run():
        req=request()
        async with paid.sessions() as db:
            with pytest.raises(HTTPException) as error:await billing.admit(db,'alice','alice_motion','candidate',req,busy=True)
            assert error.value.status_code==409;await db.rollback()
        async with paid.sessions() as db:
            assert (await db.get(User,'alice')).credits==5
            assert not (await db.execute(select(MotionExportRequest))).scalars().all()
            first=await billing.admit(db,'alice','alice_motion','candidate',req);await db.commit()
        async with paid.sessions() as db:
            replay=await billing.admit(db,'alice','alice_motion','candidate',req,busy=True)
            assert replay['id']==first['id'] and replay['replay']
    asyncio.run(run())


def test_song_level_video_export_buyout_unlocks_unlimited_exports(paid):
    async def run():
        # First export for alice_motion: charges 2 credits (from 5 to 3)
        req1 = request(request_id=uuid.uuid4(), accepted_cost=2)
        async with paid.sessions() as db:
            first = await billing.admit(db, 'alice', 'alice_motion', 'cand1', req1)
            await db.commit()
            assert not first['replay']
            assert (await db.get(User, 'alice', populate_existing=True)).credits == 3

        # Second export for same song (different clip / aspect / request_id): unlocked! cost is 0!
        req2 = request(request_id=uuid.uuid4(), accepted_cost=0, aspect='9:16')
        async with paid.sessions() as db:
            second = await billing.admit(db, 'alice', 'alice_motion', 'cand2', req2)
            await db.commit()
            assert not second['replay']
            # Credits remain at 3!
            assert (await db.get(User, 'alice', populate_existing=True)).credits == 3

        # Complete and publish first job, and finish second job
        async with paid.sessions() as db:
            await billing.publish(db, 'alice', first['id'], 'alice_motion', 'results/test1.mp4', 'poster', {})
            await billing.finish(db, 'alice', first['id'], True)
            await billing.publish(db, 'alice', second['id'], 'alice_motion', 'results/test2.mp4', 'poster', {})
            await billing.finish(db, 'alice', second['id'], True)
            await db.commit()
            assert (await db.get(User, 'alice', populate_existing=True)).credits == 3

        # Third export for alice_motion after publication: still 0 credits!
        req3 = request(request_id=uuid.uuid4(), accepted_cost=0, visual_mode='tv')
        async with paid.sessions() as db:
            third = await billing.admit(db, 'alice', 'alice_motion', 'cand3', req3)
            await billing.finish(db, 'alice', third['id'], True)
            await db.commit()
            assert not third['replay']
            assert (await db.get(User, 'alice', populate_existing=True)).credits == 3

        # But a DIFFERENT song (alice_song_b) has not been unlocked yet: charges 2 credits!
        req_other = request(project_id='alice_song_b', request_id=uuid.uuid4(), accepted_cost=2)
        async with paid.sessions() as db:
            other = await billing.admit(db, 'alice', 'alice_song_b', 'cand_other', req_other)
            await db.commit()
            assert not other['replay']
            assert (await db.get(User, 'alice', populate_existing=True)).credits == 1

    asyncio.run(run())

