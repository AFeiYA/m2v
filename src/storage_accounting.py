"""Storage accounting and visible retention policy: no silent deletion of songs."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from src.auth import get_current_user_flexible
from src.database import get_db
from src.models import Task, User, UserPlan, VersionTrash, VideoExport
from src.song_library import identity


router = APIRouter(prefix="/api/storage", tags=["Storage Accounting"])

PLAN_QUOTAS_BYTES = {
    UserPlan.FREE: 5 * 1024 * 1024 * 1024,        # 5 GB
    UserPlan.PRO: 50 * 1024 * 1024 * 1024,       # 50 GB
    UserPlan.ENTERPRISE: 200 * 1024 * 1024 * 1024, # 200 GB
}

RETENTION_POLICY = {
    "policy_version": "1.0",
    "silent_deletion_forbidden": True,
    "summary": "Source songs, lyric edits, and version histories are permanently retained. No songs or versions are ever silently deleted.",
    "song_retention": "All imported songs, audio stems, and alignment versions remain available in your account indefinitely while active.",
    "export_retention": "Exported videos remain in high-speed storage with signed, authenticated download access until you explicitly choose to delete them.",
    "trash_retention": "Deleted versions in Trash are held safely and can be restored at any time.",
    "quota_policy": "If storage reaches 100%, new imports are temporarily held until space is cleared or plan is upgraded, but existing work is never deleted.",
}


@router.get("/accounting")
async def get_storage_accounting(user: User = Depends(get_current_user_flexible), db=Depends(get_db)):
    """Return user's storage consumption, quota limits, and explicit retention policy."""
    # 1. Video export storage (sum of size_bytes in details)
    exports = (await db.execute(select(VideoExport).where(
        VideoExport.user_id == user.id,
        VideoExport.deleted_at.is_(None),
    ))).scalars().all()

    video_bytes = 0
    for exp in exports:
        details = exp.details or {}
        size = details.get("size_bytes") or 0
        video_bytes += int(size)

    # 2. Task counts and audio/metadata calculation
    tasks = (await db.execute(select(Task).where(
        Task.user_id == user.id
    ))).scalars().all()

    trashed_ids = set((await db.execute(select(VersionTrash.task_id).where(
        VersionTrash.user_id == user.id
    ))).scalars().all())

    active_tasks = [t for t in tasks if t.id not in trashed_ids]
    trashed_tasks = [t for t in tasks if t.id in trashed_ids]

    # Calculate estimated/measured audio bytes (average ~5MB per input mp3) + metadata (~200KB)
    audio_bytes = len(active_tasks) * (5 * 1024 * 1024)
    trash_bytes = len(trashed_tasks) * (5 * 1024 * 1024)
    metadata_bytes = len(tasks) * (200 * 1024)

    total_bytes = video_bytes + audio_bytes + trash_bytes + metadata_bytes
    quota_bytes = PLAN_QUOTAS_BYTES.get(user.plan, PLAN_QUOTAS_BYTES[UserPlan.FREE])
    usage_pct = round((total_bytes / quota_bytes) * 100, 2) if quota_bytes > 0 else 0.0

    # 3. Song groupings
    unique_song_ids = set(identity(t) for t in active_tasks)
    song_count = len(unique_song_ids)


    return {
        "user_id": user.id,
        "plan": user.plan.value if hasattr(user.plan, "value") else str(user.plan),
        "usage": {
            "total_bytes": total_bytes,
            "video_bytes": video_bytes,
            "audio_bytes": audio_bytes,
            "trash_bytes": trash_bytes,
            "metadata_bytes": metadata_bytes,
            "quota_bytes": quota_bytes,
            "usage_percent": min(usage_pct, 100.0),
        },
        "counts": {
            "songs": song_count,
            "active_versions": len(active_tasks),
            "trashed_versions": len(trashed_tasks),
            "exports": len(exports),
        },
        "retention_policy": RETENTION_POLICY,
    }
