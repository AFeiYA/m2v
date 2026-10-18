"""Database-serialized render admission, shared by processes and event loops.

The mutex remains locked until the caller commits its queued ExportJob or Motion
lease. Checking a count without reserving/committing is not an admission operation.
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update

from src.models import ExportJob, MotionRenderLease, RenderAdmissionMutex
from src.settings import get_settings

LEASE_SECONDS = 120
ACTIVE_STATUSES = ("queued", "running", "uploading")


def now():
    return datetime.now(timezone.utc)


async def lock_admission(db):
    dialect = db.bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError("Render admission requires PostgreSQL or SQLite")
    await db.execute(insert(RenderAdmissionMutex).values(id="global").on_conflict_do_nothing())
    # PostgreSQL row lock; SQLite write lock. Both last until commit/rollback.
    await db.execute(update(RenderAdmissionMutex).where(RenderAdmissionMutex.id == "global")
                     .values(id=RenderAdmissionMutex.id))


async def check_render_admission(db, user_id):
    await lock_admission(db)
    deadline = now()
    await db.execute(delete(MotionRenderLease).where(MotionRenderLease.lease_until <= deadline))
    settings = get_settings()
    lyric_live = (ExportJob.status.in_(ACTIVE_STATUSES), ExportJob.lease_until > deadline)
    user_lyric = (await db.execute(select(func.count()).select_from(ExportJob).where(
        ExportJob.user_id == user_id, *lyric_live))).scalar_one()
    user_motion = (await db.execute(select(func.count()).select_from(MotionRenderLease).where(
        MotionRenderLease.user_id == user_id))).scalar_one()
    if user_lyric + user_motion >= settings.MAX_CONCURRENT_RENDERS_PER_USER:
        raise HTTPException(429, "Your render slots are full. Wait for an existing video to finish.")
    all_lyric = (await db.execute(select(func.count()).select_from(ExportJob).where(*lyric_live))).scalar_one()
    all_motion = (await db.execute(select(func.count()).select_from(MotionRenderLease))).scalar_one()
    if all_lyric + all_motion >= settings.MAX_GLOBAL_CONCURRENT_RENDERS:
        raise HTTPException(503, "Render capacity is full. Please retry later.")
    return {"user_active": user_lyric + user_motion, "global_active": all_lyric + all_motion}


async def reserve_motion(db, uid, job_id):
    await check_render_admission(db, uid)
    db.add(MotionRenderLease(id=job_id, user_id=uid,
                            lease_until=now() + timedelta(seconds=LEASE_SECONDS)))
    await db.flush()


async def heartbeat_motion(db, uid, job_id):
    result = await db.execute(update(MotionRenderLease).where(
        MotionRenderLease.id == job_id, MotionRenderLease.user_id == uid,
        MotionRenderLease.lease_until > now(),
    ).values(lease_until=now() + timedelta(seconds=LEASE_SECONDS)))
    return bool(result.rowcount)


async def release_motion(db, uid, job_id):
    await db.execute(delete(MotionRenderLease).where(
        MotionRenderLease.id == job_id, MotionRenderLease.user_id == uid))
