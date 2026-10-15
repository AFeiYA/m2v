"""Persistent export history and scoped, short-lived media delivery."""
from __future__ import annotations

import re
import hashlib
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_flexible
from src.database import get_db
from src.models import Task, User, VideoExport
from src.settings import get_settings
from src.storage import LocalStorage, S3Storage, get_storage

router = APIRouter(prefix="/api/exports", tags=["My Exports"])


async def record_export(export_id, uid, task_id, key, kind="lyric", details=None):
    # Rendering threads can run on separate loops. The API factory uses NullPool.
    from src.api_server import async_session
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if not task or task.user_id != uid:
            return
        existing = await db.get(VideoExport, export_id)
        # Keep deletion tombstones: reloading status files must not resurrect files.
        if existing:
            return
        db.add(VideoExport(id=export_id, user_id=uid, task_id=task_id,
                           title=task.song_title or task.title, kind=kind,
                           storage_key=key, details=details or {}))
        await db.commit()


async def owned_export(export_id, uid, db):
    record = (await db.execute(select(VideoExport).where(
        VideoExport.id == export_id, VideoExport.user_id == uid,
        VideoExport.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if record is None:
        raise HTTPException(404, "Export not found")
    return record


def describe(record):
    created = record.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return {"id": record.id, "task_id": record.task_id, "title": record.title,
            "kind": record.kind, "status": "ready", "created_at": created.isoformat(),
            "details": {k: v for k, v in (record.details or {}).items() if k != "request_fingerprint"}}


@router.get("")
async def list_exports(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50),
                       user: User = Depends(get_current_user_flexible), db: AsyncSession = Depends(get_db)):
    filters = (VideoExport.user_id == user.id, VideoExport.deleted_at.is_(None))
    total = (await db.execute(select(func.count()).select_from(VideoExport).where(*filters))).scalar_one()
    records = (await db.execute(select(VideoExport).where(*filters).order_by(
        VideoExport.created_at.desc(), VideoExport.id.desc()).offset((page-1)*page_size).limit(page_size))).scalars()
    return {"exports": [describe(r) for r in records], "total": total, "page": page, "page_size": page_size}


@router.get("/{export_id}/access")
async def media_access(export_id: str, preview: bool = False,
                       user: User = Depends(get_current_user_flexible), db: AsyncSession = Depends(get_db)):
    record = await owned_export(export_id, user.id, db)
    storage = get_storage()
    try:
        exists = await storage.exists(record.storage_key)
    except Exception as exc:
        raise HTTPException(503, "Video storage is temporarily unavailable. Please retry.") from exc
    if not exists:
        raise HTTPException(404, "Video file is unavailable. You can delete this export record.")
    filename = (record.title or "lyric-video") + ".mp4"
    if isinstance(storage, S3Storage):
        # Never use a public_domain URL for private user exports.
        disposition = "inline" if preview else "attachment"
        url = storage.client.generate_presigned_url("get_object", Params={
            "Bucket": storage.bucket, "Key": record.storage_key,
            "ResponseContentType": "video/mp4",
            "ResponseContentDisposition": f"{disposition}; filename=\"video.mp4\"; filename*=UTF-8''{quote(filename, safe='')}",
        }, ExpiresIn=900)
    else:
        settings = get_settings()
        ticket = jwt.encode({"sub": user.id, "type": "export-media", "export": export_id,
                             "preview": preview, "exp": datetime.now(timezone.utc)+timedelta(minutes=15)},
                            settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        url = f"/api/exports/{export_id}/file?ticket={ticket}"
    from fastapi.responses import JSONResponse
    return JSONResponse({"url": url, "filename": filename, "expires_in": 900},
                        headers={"Cache-Control": "private, no-store"})


@router.get("/{export_id}/file")
async def local_media(export_id: str, ticket: str, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    try:
        payload = jwt.decode(ticket, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "export-media" or payload.get("export") != export_id:
            raise JWTError("Wrong scope")
    except JWTError as exc:
        raise HTTPException(401, "Download link expired. Request a new link.") from exc
    record = await owned_export(export_id, payload.get("sub"), db)
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        raise HTTPException(404, "Local media is unavailable")
    from fastapi.responses import FileResponse
    path = storage.get_local_path(record.storage_key)
    if not path.is_file():
        raise HTTPException(404, "Video file is unavailable")
    return FileResponse(path, media_type="video/mp4", filename=(record.title or "video")+".mp4",
                        content_disposition_type="inline" if payload.get("preview") else "attachment",
                        headers={"Cache-Control": "private, no-store"})


@router.delete("/{export_id}")
async def delete_export(export_id: str, user: User = Depends(get_current_user_flexible), db: AsyncSession = Depends(get_db)):
    record = await owned_export(export_id, user.id, db)
    try:
        await get_storage().delete(record.storage_key)
    except FileNotFoundError:
        pass
    except Exception as exc:
        raise HTTPException(502, "Unable to delete video. Please retry.") from exc
    record.deleted_at = datetime.now(timezone.utc)
    task = await db.get(Task, record.task_id)
    if task and task.output_mp4_key == record.storage_key:
        task.output_mp4_key = None
    # Remove cached Motion/Rhythm copies/status through their owning workspace too.
    if record.kind in ("poster", "rhythm"):
        for suffix in ("_status.json", ".json"):
            await get_storage().delete(record.storage_key.removesuffix('.mp4')+suffix)
        from src.motion_cloud import _workspaces
        workspace = _workspaces.get((id(get_storage()), user.id))
        if workspace:
            directory = workspace.root / record.task_id / "motion_exports"
            for suffix in (".mp4", "_status.json", ".json"):
                path = directory / (record.id + suffix)
                path.unlink(missing_ok=True)
    await db.commit()
    return {"message": "Export deleted. Your song and alignment are unchanged."}


@router.post("/discover")
async def discover_exports(user: User = Depends(get_current_user_flexible), db: AsyncSession = Depends(get_db)):
    """Explicit recovery scan for exports created before the durable library existed."""
    from src.motion_cloud import task_prefix
    storage = get_storage()
    tasks = (await db.execute(select(Task).where(Task.user_id == user.id).order_by(Task.created_at.desc()).limit(100))).scalars().all()
    added = 0
    for task in tasks:
        if task.output_mp4_key:
            pipeline_id = hashlib.sha256(("pipeline:" + task.id).encode()).hexdigest()
            if not await db.get(VideoExport, pipeline_id) and await storage.exists(task.output_mp4_key):
                db.add(VideoExport(id=pipeline_id, user_id=user.id, task_id=task.id,
                                   title=task.song_title or task.title, kind="lyric",
                                   storage_key=task.output_mp4_key, details={"recovered": True}))
                added += 1
        for prefix, kind in ((f"results/{task.id}/exports/", "lyric"),
                             (task_prefix(user.id, task.id)+"motion_exports/", "poster")):
            for key in await storage.list_keys(prefix):
                export_id = key.removeprefix(prefix).removesuffix(".mp4")
                if not key.endswith(".mp4") or not re.fullmatch(r"[a-f0-9]{32,64}", export_id):
                    continue
                if await db.get(VideoExport, export_id):
                    continue
                details = {"recovered": True}
                export_kind = kind
                if kind == "poster":
                    status_key = key.removesuffix(".mp4") + "_status.json"
                    if await storage.exists(status_key):
                        with tempfile.TemporaryDirectory(prefix="m2v-export-recovery-") as directory:
                            local = Path(directory) / "status.json"
                            await storage.load(status_key, local)
                            try:
                                status = json.loads(local.read_text())
                                if status.get("scene") == "rhythm":
                                    export_kind = "rhythm"
                                details.update(resolution=[status.get("width"), status.get("height")],
                                               duration=status.get("total", 0)/30)
                            except (ValueError, TypeError, AttributeError):
                                pass
                db.add(VideoExport(id=export_id, user_id=user.id, task_id=task.id,
                                   title=task.song_title or task.title, kind=export_kind, storage_key=key,
                                   details=details))
                added += 1
    await db.commit()
    return {"added": added, "message": "Checked the latest 100 projects for earlier exports."}
