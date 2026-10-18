"""Queue admission and per-user/global concurrency limits for render jobs."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select

from src.models import ExportJob
from src.settings import get_settings

ACTIVE_STATUSES = ("queued", "running", "uploading")


async def check_render_admission(db, user_id: str):
    """Enforce per-user and global concurrency limits before accepting an export job."""
    settings = get_settings()
    max_user = settings.MAX_CONCURRENT_RENDERS_PER_USER
    max_global = settings.MAX_GLOBAL_CONCURRENT_RENDERS

    # 1. Per-user concurrency check
    user_active = (await db.execute(select(func.count()).select_from(ExportJob).where(
        ExportJob.user_id == user_id,
        ExportJob.status.in_(ACTIVE_STATUSES),
    ))).scalar_one()

    if user_active >= max_user:
        raise HTTPException(
            429,
            f"You already have {user_active} render job(s) in progress (limit: {max_user}). "
            "Please wait for your current video to finish."
        )

    # 2. Global concurrency check
    global_active = (await db.execute(select(func.count()).select_from(ExportJob).where(
        ExportJob.status.in_(ACTIVE_STATUSES),
    ))).scalar_one()

    if global_active >= max_global:
        raise HTTPException(
            503,
            f"Render queue is currently at capacity ({global_active}/{max_global} slots active). "
            "Please wait a moment and retry."
        )

    return {"user_active": user_active, "global_active": global_active}
