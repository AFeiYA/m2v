"""Motion render admission, idempotent credit holds and publication fencing."""
from datetime import timedelta
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select, update

from src import credits
from src.models import MotionExportRequest, MotionRenderLease, VideoExport
from src.queue_limiter import now, LEASE_SECONDS, lock_admission, reserve_motion, release_motion
from src.settings import get_settings


async def reconcile(db, uid):
    expired = (await db.execute(select(MotionExportRequest.id).where(
        MotionExportRequest.user_id == uid, MotionExportRequest.state == 'active',
        MotionExportRequest.lease_until <= now()))).scalars().all()
    if not expired:
        return
    await credits.lock_balance(db, uid)
    for job_id in expired:
        changed = await db.execute(update(MotionExportRequest).execution_options(synchronize_session=False).where(
            MotionExportRequest.id == job_id, MotionExportRequest.state == 'active',
            MotionExportRequest.lease_until <= now()).values(state='interrupted'))
        if changed.rowcount:
            await credits.finish(db, uid, job_id, 'motion_export', False)
            await release_motion(db, uid, job_id)


async def admit(db, uid, project_id, candidate_id, request, *, busy=False):
    await lock_admission(db)
    await reconcile(db, uid)
    values = request.model_dump(mode='json')
    request_id = values.get('request_id')
    cost = get_settings().MOTION_EXPORT_CREDITS
    if cost and not request_id:
        raise HTTPException(409, 'A request_id is required for paid Motion exports.')
    job_id = hashlib.sha256(f'{uid}:motion:{request_id}'.encode()).hexdigest()[:32] if request_id else candidate_id
    fingerprint = hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()
    previous = await db.get(MotionExportRequest, job_id, populate_existing=True)
    if previous:
        if previous.user_id != uid or previous.task_id != project_id or previous.fingerprint != fingerprint:
            raise HTTPException(409, 'Request ID already has different Motion export settings. Start a new request.')
        exported=await db.get(VideoExport,job_id)
        if exported and exported.deleted_at is not None:
            raise HTTPException(409,'This video was deleted. Start a new export request.')
        return {'id':job_id, 'replay':True}
    if busy:
        raise HTTPException(409,'已有视频正在导出，请等待完成或取消')
    if values.get('accepted_cost') != cost and cost:
        raise HTTPException(409, 'Review and accept the current Motion export credit price before rendering.')
    await reserve_motion(db, uid, job_id)
    await credits.reserve(db, uid, job_id, 'motion_export', cost)
    db.add(MotionExportRequest(id=job_id,user_id=uid,task_id=project_id,
        fingerprint=fingerprint,cost=cost,state='active',lease_until=now()+timedelta(seconds=LEASE_SECONDS)))
    await db.flush()
    return {'id':job_id, 'replay':False}


async def heartbeat(db, uid, job_id):
    row = await db.get(MotionExportRequest,job_id)
    if not row:
        return None  # Legacy/free clients still use the original lease hooks.
    deadline = now()
    renewed = await db.execute(update(MotionRenderLease).execution_options(synchronize_session=False).where(
        MotionRenderLease.id == job_id, MotionRenderLease.user_id == uid,
        MotionRenderLease.lease_until > deadline).values(lease_until=deadline+timedelta(seconds=LEASE_SECONDS)))
    if not renewed.rowcount:
        return False
    renewed = await db.execute(update(MotionExportRequest).execution_options(synchronize_session=False).where(
        MotionExportRequest.id == job_id, MotionExportRequest.user_id == uid,
        MotionExportRequest.state == 'active', MotionExportRequest.lease_until > deadline,
    ).values(lease_until=deadline+timedelta(seconds=LEASE_SECONDS)))
    return bool(renewed.rowcount)


async def publish(db, uid, job_id, task_id, storage_key, kind, details):
    await credits.lock_balance(db,uid)
    row = await db.get(MotionExportRequest,job_id,populate_existing=True)
    if row and (row.user_id != uid or row.task_id != task_id or row.state != 'active'):
        if row.user_id == uid and row.task_id == task_id and row.state == 'done' and await db.get(VideoExport,job_id):
            return True
        raise RuntimeError('Motion export is no longer eligible for publication')
    if row:
        from datetime import timezone
        expiry = row.lease_until.replace(tzinfo=timezone.utc) if row.lease_until.tzinfo is None else row.lease_until
        if expiry <= now():
            raise RuntimeError('Motion render lease expired before publication')
    from src.export_library import record_export
    if not await record_export(job_id,uid,task_id,storage_key,kind,details,db=db):
        raise RuntimeError('Source song is no longer available for publication')
    if row:
        await credits.finish(db,uid,job_id,'motion_export',True)
        row.state='done'
    return True


async def finish(db, uid, job_id, success=False, cancelled=False):
    await credits.lock_balance(db,uid)
    row = await db.get(MotionExportRequest,job_id,populate_existing=True)
    if row and row.user_id == uid and row.state == 'active':
        # Successful charging happens only in the same transaction as publication.
        delivered = bool(success and await db.get(VideoExport,job_id))
        await credits.finish(db,uid,job_id,'motion_export',delivered)
        row.state = 'done' if delivered else ('cancelled' if cancelled else 'failed')
    await release_motion(db,uid,job_id)
    return row.state if row and row.user_id == uid else None


async def status(db,uid,job_id):
    await reconcile(db,uid)
    row = await db.get(MotionExportRequest,job_id,populate_existing=True)
    if row is None or row.user_id != uid:
        return None
    messages={'interrupted':'Render was interrupted; unused reserved credits returned.',
              'failed':'Motion export failed; unused reserved credits returned.'}
    return {'id':job_id,'status':{'active':'queued','interrupted':'failed'}.get(row.state,row.state),
            'frames':0,'total':0,'error':messages.get(row.state,'')}
