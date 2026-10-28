"""Archive browser-rendered MP4s before settling credits or exposing a download.

This route is independent of the server render worker. A metadata receipt is
never a video asset, and a failed upload must never start a second paid render.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from src import credits
from src.auth import get_current_user_flexible
from src.database import get_db
from src.export_library import record_export
from src.models import Task, User, VideoExport
from src.settings import get_settings
from src.storage import get_storage
from src.version_lifecycle import live_task
from src.utils import log

router = APIRouter(tags=['Browser exports'])
MAX_UPLOAD_BYTES = 512 * 1024 * 1024


def inspect_video(path: Path) -> dict:
    """Probe the uploaded file, not dimensions/duration reported by the client."""
    try:
        with path.open('rb') as source:
            if source.read(12)[4:8] != b'ftyp':
                raise ValueError('Not an MP4')
        result = subprocess.run([
            'ffprobe', '-v', 'error', '-protocol_whitelist', 'file',
            '-show_format', '-show_streams', '-of', 'json', str(path),
        ], capture_output=True, timeout=20, check=True)
        info = json.loads(result.stdout)
        video = next(s for s in info['streams'] if s['codec_type'] == 'video')
        if not any(s['codec_type'] == 'audio' for s in info['streams']):
            raise ValueError('Audio missing')
        duration = float(info['format']['duration'])
        width, height = int(video['width']), int(video['height'])
        if not math.isfinite(duration) or not 0 < duration <= 3600 or not 0 < width <= 4096 or not 0 < height <= 4096:
            raise ValueError('Unsupported video dimensions or duration')
        return {'resolution': [width, height], 'duration': duration}
    except (ValueError, KeyError, StopIteration, OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(422, 'Upload a valid MP4 with both video and audio. Nothing was charged.') from exc


@router.post('/browser-exports')
async def archive_browser_export(
    request: Request, project_id: str = Query(max_length=64), request_id: UUID = Query(),
    accepted_cost: int = Query(ge=0), title: str = Query(default='', max_length=255),
    aspect: Literal['9:16', '16:9'] = Query(default='9:16'),
    user: User = Depends(get_current_user_flexible), db=Depends(get_db),
):
    task = (await db.execute(select(Task).where(
        Task.id == project_id, Task.user_id == user.id, live_task(),
        Task.alignment_json_key.isnot(None),
    ))).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, 'Song not found')
    if request.headers.get('content-type', '').split(';')[0] != 'video/mp4':
        raise HTTPException(415, 'Expected an MP4 upload')
    job_id = hashlib.sha256(f'{user.id}:browser:{request_id}'.encode()).hexdigest()[:32]
    digest, size = hashlib.sha256(), 0
    with tempfile.TemporaryDirectory(prefix='m2v-browser-') as directory:
        path = Path(directory) / 'video.mp4'
        with path.open('wb') as output:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, 'Video is too large to archive. Nothing was charged.')
                digest.update(chunk)
                output.write(chunk)
        details = await asyncio.to_thread(inspect_video, path)
        if (details['resolution'][0] < details['resolution'][1]) != (aspect == '9:16'):
            raise HTTPException(422, 'Video aspect ratio does not match the selected format')
        fingerprint = hashlib.sha256(json.dumps(
            [project_id, title, aspect, digest.hexdigest()], separators=(',', ':')
        ).encode()).hexdigest()
        await credits.lock_balance(db, user.id)
        existing = await db.get(VideoExport, job_id, populate_existing=True)
        if existing:
            if (existing.user_id != user.id or existing.task_id != project_id or existing.deleted_at
                    or (existing.details or {}).get('request_fingerprint') != fingerprint):
                raise HTTPException(409, 'This export request already belongs to a different or deleted video')
            if not await get_storage().exists(existing.storage_key):
                raise HTTPException(503, 'Previously saved video is unavailable. No additional credits were charged.')
            return {'id': job_id, 'status': 'done', 'replay': True}
        from src.motion_billing import is_song_unlocked
        base_cost = get_settings().MOTION_WEBCODECS_CREDITS
        unlocked = await is_song_unlocked(db, user.id, project_id)
        cost = 0 if unlocked else base_cost
        if cost > 0:
            if accepted_cost < cost:
                raise HTTPException(409, 'Export price changed. Review the current price before saving.')
        from src.storage_accounting import check_storage_quota
        await check_storage_quota(db, user)
        if cost > 0:
            await credits.reserve(db, user.id, job_id, 'motion_webcodecs', cost)
        storage = get_storage()
        # Immutable content-addressed key: retrying cannot overwrite another video.
        key = f'exports/{hashlib.sha256(user.id.encode()).hexdigest()}/browser/{job_id}/{digest.hexdigest()}.mp4'
        try:
            await storage.save(key, path)
            if not await storage.exists(key) or await storage.get_size(key) != size:
                raise HTTPException(503, 'Video upload could not be verified. Retry saving; nothing was charged.')
            details.update(size_bytes=size, title=title, aspect=aspect, request_fingerprint=fingerprint)
            if not await record_export(job_id, user.id, project_id, key, 'webcodecs', details, db=db):
                raise HTTPException(409, 'Song is no longer available. Nothing was charged.')
            if cost > 0:
                await credits.finish(db, user.id, job_id, 'motion_webcodecs', True)
        except BaseException:
            # Before commit the per-account lock prevents another attempt from
            # publishing this object. Never delete on an ambiguous commit error.
            try:
                await storage.delete(key)
            except Exception:
                log.warning('Browser export orphan requires cleanup: %s', job_id)
            raise
        await db.commit()
    return {'id': job_id, 'status': 'done', 'replay': False}
