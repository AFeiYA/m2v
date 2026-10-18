"""Queue admission and per-user/global concurrency limits for render jobs."""
from __future__ import annotations

import asyncio
import threading
from fastapi import HTTPException
from sqlalchemy import func, select

from src.models import ExportJob
from src.settings import get_settings

ACTIVE_STATUSES = ("queued", "running", "uploading")

_ADMISSION_LOCK = asyncio.Lock()
_motion_lock = threading.Lock()
_active_motion_jobs: dict[str, set[str]] = {}  # user_id -> set of job_ids


def register_motion_job(user_id: str, job_id: str):
    """Register an active motion render job into concurrency tracking."""
    with _motion_lock:
        _active_motion_jobs.setdefault(user_id, set()).add(job_id)


def unregister_motion_job(user_id: str, job_id: str):
    """Unregister a finished or failed motion render job."""
    with _motion_lock:
        if user_id in _active_motion_jobs:
            _active_motion_jobs[user_id].discard(job_id)
            if not _active_motion_jobs[user_id]:
                del _active_motion_jobs[user_id]


def get_active_motion_count(user_id: str | None = None) -> int:
    """Return number of active motion jobs for a specific user, or across all users."""
    with _motion_lock:
        if user_id is not None:
            return len(_active_motion_jobs.get(user_id, set()))
        return sum(len(jobs) for jobs in _active_motion_jobs.values())


async def check_render_admission(db, user_id: str):
    """Enforce per-user and global concurrency limits across both lyric and motion exports."""
    settings = get_settings()
    max_user = settings.MAX_CONCURRENT_RENDERS_PER_USER
    max_global = settings.MAX_GLOBAL_CONCURRENT_RENDERS

    async with _ADMISSION_LOCK:
        # 1. Per-user concurrency check (ExportJob rows + active Motion renders)
        user_db_active = (await db.execute(select(func.count()).select_from(ExportJob).where(
            ExportJob.user_id == user_id,
            ExportJob.status.in_(ACTIVE_STATUSES),
        ))).scalar_one()

        motion_user = get_active_motion_count(user_id)
        total_user_active = user_db_active + motion_user

        if total_user_active >= max_user:
            raise HTTPException(
                429,
                f"You already have {total_user_active} render job(s) in progress (limit: {max_user}). "
                "Please wait for your current video to finish."
            )

        # 2. Global concurrency check (All ExportJob rows + all active Motion renders)
        global_db_active = (await db.execute(select(func.count()).select_from(ExportJob).where(
            ExportJob.status.in_(ACTIVE_STATUSES),
        ))).scalar_one()

        motion_global = get_active_motion_count(None)
        total_global_active = global_db_active + motion_global

        if total_global_active >= max_global:
            raise HTTPException(
                503,
                f"Render queue is currently at capacity ({total_global_active}/{max_global} slots active). "
                "Please wait a moment and retry."
            )

        return {"user_active": total_user_active, "global_active": total_global_active}
