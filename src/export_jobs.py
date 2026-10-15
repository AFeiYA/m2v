"""Database-backed lyric render jobs, leased attempts and atomic publication.

No audio separation or alignment inference is invoked by this module. A lost
worker becomes interrupted after its lease expires; only an explicit retry runs
it again. Each attempt writes its own object so a late worker cannot overwrite
or delete a newer attempt's video.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.models import ExportJob, Task, VideoExport
from src.utils import log

ACTIVE = ("queued", "running", "uploading")
RETRYABLE = ("failed", "interrupted")
LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 10


def now():
    return datetime.now(timezone.utc)


def sessions():
    # Resolve at runtime: serving/worker loops must not share pooled connections.
    from src.api_server import async_session
    return async_session()


def public_job(row):
    return {"id": row.id, "task_id": row.task_id, "title": row.title, "kind": "video",
            "status": row.status, "phase": row.phase, "progress": row.progress,
            "message": row.message, "error": row.error, "result": row.result,
            "attempt": row.attempt, "created_at": row.created_at.isoformat()}


async def reconcile(db, uid):
    # Do not mark all running jobs interrupted on startup: another process may
    # still own a valid lease. Conditional updates also fence that old worker.
    await db.execute(update(ExportJob).where(
        ExportJob.user_id == uid, ExportJob.status.in_(ACTIVE), ExportJob.lease_until < now(),
    ).execution_options(synchronize_session=False).values(status="interrupted", phase="interrupted", run_token=None,
             message="Rendering was interrupted. Retry uses your saved audio and timeline.",
             error="The render worker stopped responding.", updated_at=now()))


async def owned(db, job_id, uid):
    await reconcile(db, uid)
    row = (await db.execute(select(ExportJob).where(
        ExportJob.id == job_id, ExportJob.user_id == uid,
        ExportJob.status != "dismissed",
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Export job not found")
    return row


async def create(task, user, options, background, db):
    values = options.model_dump(mode="json")
    request_id = values.get("request_id")
    job_id = hashlib.sha256(f'{user.id}:{task.id}:video:{request_id}'.encode()).hexdigest() if request_id else uuid.uuid4().hex
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    # Keep old completed exports idempotent, even if they predate export_jobs.
    completed = await db.get(VideoExport, job_id)
    if completed:
        if completed.user_id != user.id or completed.task_id != task.id:
            raise HTTPException(404, "Export not found")
        if completed.deleted_at or (completed.details or {}).get("request_fingerprint") != fingerprint:
            raise HTTPException(409, "Start a new export request for deleted videos or changed settings")
        return {"task_id": job_id, "status": "completed"}
    await reconcile(db, user.id)
    existing = await db.get(ExportJob, job_id)
    if existing:
        if existing.user_id != user.id or existing.task_id != task.id:
            raise HTTPException(404, "Export job not found")
        if existing.fingerprint != fingerprint or existing.status == "dismissed":
            raise HTTPException(409, "Start a new export request for changed settings")
        await db.commit()
        return {"task_id": job_id, "status": existing.status}
    uid, tid = user.id, task.id
    db.add(ExportJob(id=job_id, user_id=uid, task_id=tid,
                     title=task.song_title or task.title, options=values, fingerprint=fingerprint,
                     alignment_key=task.alignment_json_key, audio_key=task.input_mp3_key,
                     lease_until=now()+timedelta(seconds=LEASE_SECONDS)))
    try:
        # Commit before starting the worker or returning the ID. A different
        # browser/process must be able to read a queued request immediately.
        await db.commit()
    except IntegrityError:
        await db.rollback()
        row = await owned(db, job_id, uid)
        if row.fingerprint != fingerprint:
            raise HTTPException(409, "Request ID already has different export settings")
        return {"task_id": job_id, "status": row.status}
    background.add_task(run, job_id)
    return {"task_id": job_id, "status": "queued"}


async def retry(db, job_id, uid, background):
    row = await owned(db, job_id, uid)
    if row.status in ACTIVE:
        await db.commit()
        return {"task_id": job_id, "status": row.status}
    if row.status not in RETRYABLE:
        raise HTTPException(409, "Only failed or interrupted exports can be retried")
    claimed = await db.execute(update(ExportJob).where(
        ExportJob.id == job_id, ExportJob.user_id == uid, ExportJob.status.in_(RETRYABLE),
    ).values(status="queued", phase="queued", progress=0, error=None, result=None,
             output_key=None, run_token=None, attempt=ExportJob.attempt+1,
             message="Waiting to retry rendering", updated_at=now(),
             lease_until=now()+timedelta(seconds=LEASE_SECONDS)))
    await db.commit()
    if claimed.rowcount:
        background.add_task(run, job_id)
    return {"task_id": job_id, "status": "queued"}


async def dismiss(db, job_id, uid):
    row = await owned(db, job_id, uid)
    if row.status not in RETRYABLE:
        raise HTTPException(409, "Only failed or interrupted exports can be dismissed")
    await db.execute(update(ExportJob).where(
        ExportJob.id == job_id, ExportJob.user_id == uid, ExportJob.status.in_(RETRYABLE),
    ).values(status="dismissed", updated_at=now()))
    await db.commit()
    return {"message": "Export job dismissed. Your audio and alignment are unchanged."}


async def change(job_id, token, **values):
    async with sessions() as db:
        result = await db.execute(update(ExportJob).where(
            ExportJob.id == job_id, ExportJob.run_token == token, ExportJob.status.in_(ACTIVE),
        ).values(**values, updated_at=now(), lease_until=now()+timedelta(seconds=LEASE_SECONDS)))
        await db.commit()
        if result.rowcount != 1:
            raise RuntimeError("Render attempt no longer owns this job")


async def publish(job_id, token, key, result, size):
    # The usable artifact and completed status are one transaction. If the
    # transaction fails after upload, the job must not claim it is completed.
    async with sessions() as db:
        candidate = await db.get(ExportJob, job_id)
        if candidate is None:
            raise RuntimeError("Song was deleted while rendering")
        task = (await db.execute(select(Task).where(Task.id == candidate.task_id).with_for_update())).scalar_one_or_none()
        row = (await db.execute(select(ExportJob).where(
            ExportJob.id == job_id, ExportJob.run_token == token, ExportJob.status.in_(ACTIVE),
        ).with_for_update())).scalar_one_or_none()
        if row is None:
            raise RuntimeError("Render attempt was interrupted or deleted")
        if task is None or task.user_id != row.user_id:
            raise RuntimeError("Song was deleted while rendering")
        if await db.get(VideoExport, job_id):
            raise RuntimeError("Export already exists")
        details = {**result, "size_bytes": size, "request_fingerprint": row.fingerprint}
        db.add(VideoExport(id=job_id, user_id=row.user_id, task_id=row.task_id,
                           title=row.title, kind="lyric", storage_key=key, details=details))
        row.status, row.phase, row.progress = "completed", "completed", 100
        row.output_key = key
        row.result = {**result, "export_id": job_id, "video_url": f"/api/editor/jobs/{job_id}/video"}
        row.message, row.error = "Video ready in My Exports", None
        row.run_token = None
        await db.commit()


async def run(job_id):
    from src import editor_operations as operations
    from src.song_assets import source_keys
    from src.song_sections import bind_source_sections
    from src.storage import get_storage
    token = uuid.uuid4().hex
    async with sessions() as db:
        claimed = await db.execute(update(ExportJob).where(
            ExportJob.id == job_id, ExportJob.status == "queued", ExportJob.run_token.is_(None),
        ).values(run_token=token, lease_until=now()+timedelta(seconds=LEASE_SECONDS), updated_at=now()))
        await db.commit()
        if not claimed.rowcount:
            return
        row = await db.get(ExportJob, job_id)
        alignment_key, audio_key, task_id = row.alignment_key, row.audio_key, row.task_id
        options = dict(row.options)
    storage = get_storage()
    state = {"progress": 0, "message": "Waiting for a render slot"}
    heartbeat_error = []

    async def heartbeat():
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_SECONDS)
                await change(job_id, token, **state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            heartbeat_error.append(exc)
            log.warning("Render heartbeat failed: %s (%s)", job_id, type(exc).__name__)

    heartbeat_task = asyncio.create_task(heartbeat())
    key = None
    published = False
    try:
        loop = asyncio.get_running_loop()
        slots = getattr(loop, "_m2v_editor_slots", None)
        if slots is None:
            slots = asyncio.Semaphore(2)
            loop._m2v_editor_slots = slots
        async with slots:
            state.update(progress=5, message="Loading saved audio and timeline")
            await change(job_id, token, status="running", phase="loading", **state)
            with tempfile.TemporaryDirectory(prefix="m2v-render-") as directory:
                work = Path(directory)
                alignment, audio = work / "alignment.json", work / ("source"+Path(audio_key).suffix)
                await storage.load(alignment_key, alignment)
                await storage.load(audio_key, audio)
                payload = json.loads(alignment.read_text())
                metadata_key, cover_key = source_keys(audio_key)
                if await storage.exists(metadata_key):
                    metadata = work / "source_suno.json"
                    await storage.load(metadata_key, metadata)
                    bind_source_sections(payload, json.loads(metadata.read_text()).get("sections") or [])
                    alignment.write_text(json.dumps(payload, ensure_ascii=False))
                values = operations.video_options(payload, options)
                if await storage.exists(cover_key):
                    cover = work / "source_cover.jpg"
                    await storage.load(cover_key, cover)
                    values["cover_path"] = str(cover)
                state.update(progress=10, message="Rendering from saved timeline")
                await change(job_id, token, phase="rendering", **state)
                def progress(value, message):
                    # Renderer callback is on a thread. Only the serving loop
                    # mutates the heartbeat state; never share an AsyncSession.
                    loop.call_soon_threadsafe(state.update, {"progress": max(10, min(90, int(value))), "message": "Rendering video"})
                output = work / "video.mp4"
                result = await asyncio.to_thread(operations.render_video, alignment, audio, output, values, progress)
                if not output.is_file() or output.stat().st_size <= 0:
                    raise RuntimeError("Renderer did not produce a video file")
                if heartbeat_error:
                    raise RuntimeError("Unable to maintain render lease. Retry when the service is available.")
                state.update(progress=95, message="Uploading video")
                await change(job_id, token, status="uploading", phase="uploading", **state)
                key = f"results/{task_id}/exports/{job_id}/{token}.mp4"
                await storage.save(key, output)
                if not await storage.exists(key):
                    raise RuntimeError("Video upload could not be verified")
                remote_size = await storage.get_size(key)
                if remote_size is not None and remote_size != output.stat().st_size:
                    raise RuntimeError("Uploaded video size does not match the rendered file")
                result = {k: result[k] for k in ("resolution", "size_mb", "elapsed_seconds", "duration") if k in result}
                await publish(job_id, token, key, result, output.stat().st_size)
                published = True
    except asyncio.CancelledError:
        # Graceful shutdown gets an immediate interruption. An abrupt stop is
        # detected from the expiring lease on the next list/status request.
        try:
            await change(job_id, token, status="interrupted", phase="interrupted", run_token=None,
                         error="Server stopped during rendering", message="Rendering interrupted. Retry is available.")
        except Exception:
            pass
        raise
    except Exception as exc:
        log.exception("Persistent render failed: %s", job_id)
        try:
            await change(job_id, token, status="failed", phase="failed", error=str(exc), message="Video export failed. Retry is available.", run_token=None)
        except Exception:
            log.warning("Unable to mark render failed: %s; its lease will expire", job_id)
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        if key and not published:
            try:
                # A commit acknowledgement can be lost after the transaction
                # actually succeeds. Never delete a file referenced by a ready
                # export, or guess when the database cannot be reached.
                async with sessions() as db:
                    linked = (await db.execute(select(VideoExport.id).where(
                        VideoExport.storage_key == key, VideoExport.deleted_at.is_(None),
                    ).limit(1))).scalar_one_or_none()
                if linked is None:
                    await storage.delete(key)
            except Exception:
                log.warning("Unable to clean unpublished render object: %s", job_id)
