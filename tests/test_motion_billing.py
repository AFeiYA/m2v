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
    seed_cloud_motion(sandbox)
    return sandbox


def request(**overrides):
    return RenderRequest(project_id='alice_motion',request_id=uuid.uuid4(),accepted_cost=2,length=.5,**overrides)


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


def test_paid_http_record_webcodecs_charges_and_records(paid, monkeypatch):
    monkeypatch.setattr(get_settings(), 'MOTION_WEBCODECS_CREDITS', 2)
    base = '/api/cloud-motion'
    job_id = 'wc_test_' + str(uuid.uuid4())[:8]
    req_body = {
        'project_id': 'alice_motion',
        'job_id': job_id,
        'title': 'Alice WebCodecs Export',
        'aspect': '9:16',
        'duration': 15.0,
        'total_frames': 450,
        'file_size': 1024000
    }
    res = paid.client.post(base + '/render/record_webcodecs', headers=headers(), json=req_body)
    assert res.status_code == 200, res.text
    assert res.json()['status'] == 'done'
    credits_response = paid.client.get('/api/credits', headers=headers()).json()
    assert credits_response['available'] == 3, credits_response

    # Idempotent re-post does not double charge
    res2 = paid.client.post(base + '/render/record_webcodecs', headers=headers(), json=req_body)
    assert res2.status_code == 200
    credits_response2 = paid.client.get('/api/credits', headers=headers()).json()
    assert credits_response2['available'] == 3


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
