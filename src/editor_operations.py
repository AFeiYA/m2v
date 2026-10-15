"""Task-owned background operations for the cloud lyric editor."""
from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
import hashlib
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_flexible
from src.database import get_db
from src.models import User, VideoExport
from src.settings import get_settings
from src.storage import get_storage
from src.task_store import TaskStore
from src.utils import log

router = APIRouter()
jobs = TaskStore(lambda: Path(get_settings().UPLOAD_DIR) / "editor_jobs")


class VideoOptions(BaseModel):
    request_id: uuid.UUID | None = None
    section_name: Literal['', 'chorus', 'verse1', 'intro'] = ''
    aspect_ratio: Literal["9:16", "16:9"] = "9:16"
    template: Literal["apple", "center_bounce", "tv"] = "apple"
    theme: str = "apple_white"
    background_mode: Literal["full_bleed", "ken_burns", "blurred_ambient", "vinyl", "solid_black"] = "full_bleed"
    duration_limit: float | None = Field(default=None, gt=0)
    start_time: float = Field(default=0, ge=0)
    end_time: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def ordered_times(self):
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("结束时间必须晚于开始时间")
        return self


class AnalysisOptions(BaseModel):
    force: bool = False


def render_video(alignment: Path, audio: Path, output: Path, options: dict, progress):
    from src.lyric_engine import export_lyric_video
    return export_lyric_video(alignment_source=alignment, audio_path=audio,
                              output_path=output, progress_callback=progress, **options)


def video_options(payload: dict, options: dict) -> dict:
    result = dict(options)
    result.pop('request_id', None)
    section = result.pop('section_name', '')
    if section:
        import re
        patterns = {'chorus': r'^(?:final\s+)?chorus(?:\s+\d+)?$|^副歌',
                    'verse1': r'^verse(?:\s+1)?$|^主歌(?:\s*1)?$', 'intro': r'^intro$|^前奏$'}
        match = next((s for s in payload.get('sections', []) if re.search(patterns[section], s.get('name', ''), re.I)), None)
        if match is None:
            raise ValueError('所选乐段不存在，请选择完整歌曲或在编辑器指定片段')
        result['start_time'] = match['start']
    return result


def analyze_audio(audio: Path, cache: Path, force: bool):
    from src.audio_analyzer import cached_audio_analysis
    return cached_audio_analysis(audio, cache, force=force)


async def run_job(job_id: str, storage, alignment_key: str, audio_key: str, options: dict):
    job = jobs.get(job_id)
    try:
        # Keep the limiter on the serving loop; Gradio/test startup may use others.
        loop = asyncio.get_running_loop()
        slots = getattr(loop, "_m2v_editor_slots", None)
        if slots is None:
            slots = asyncio.Semaphore(2)
            loop._m2v_editor_slots = slots
        async with slots:
            job.update(status="running", progress=10, message="正在处理…")
            with tempfile.TemporaryDirectory(prefix="m2v-editor-") as directory:
                work = Path(directory)
                alignment = work / "alignment.json"
                audio = work / ("source" + Path(audio_key).suffix)
                await storage.load(alignment_key, alignment)
                await storage.load(audio_key, audio)
                if job["kind"] == "video":
                    from src.song_assets import source_keys
                    from src.song_sections import bind_source_sections
                    metadata_key, cover_key = source_keys(audio_key)
                    payload = json.loads(alignment.read_text())
                    if await storage.exists(metadata_key):
                        metadata = work / 'source_suno.json'
                        await storage.load(metadata_key, metadata)
                        bind_source_sections(payload, json.loads(metadata.read_text()).get('sections') or [])
                        alignment.write_text(json.dumps(payload, ensure_ascii=False))
                    options = video_options(payload, options)
                    if await storage.exists(cover_key):
                        cover = work / 'source_cover.jpg'
                        await storage.load(cover_key, cover)
                        options['cover_path'] = str(cover)
                    output = work / "lyric_video.mp4"
                    def progress(value, message):
                        job.update(progress=value, message=message)
                    result = await asyncio.to_thread(render_video, alignment, audio, output, options, progress)
                    key = f"results/{job['song_task_id']}/exports/{job_id}.mp4"
                    await storage.save(key, output)
                    # Never return temporary paths or an unowned local-file URL.
                    result = {k: result[k] for k in ("resolution", "size_mb", "elapsed_seconds", "duration") if k in result}
                    from src.export_library import record_export
                    await record_export(job_id, job['user_id'], job['song_task_id'], key,
                                        details={**result, "size_bytes": output.stat().st_size,
                                                 "request_fingerprint": job.get("fingerprint")})
                    result["export_id"] = job_id
                    result["video_url"] = f"/api/editor/jobs/{job_id}/video"
                    job.update(output_key=key, status="completed", progress=100, result=result)
                else:
                    cache_key = f"results/{job['song_task_id']}/audio_analysis.json"
                    cache = work / "analysis.json"
                    if await storage.exists(cache_key):
                        await storage.load(cache_key, cache)
                    analysis = await asyncio.to_thread(analyze_audio, audio, cache, options.get("force", False))
                    # Reload after inference so lyrics saved during analysis survive.
                    await storage.load(alignment_key, alignment)
                    payload = json.loads(alignment.read_text(encoding="utf-8"))
                    from src.storyboard_schema import MusicSection
                    from src.audio_analyzer import detect_cut_candidates
                    sections = [MusicSection.model_validate(s) for s in payload.get("sections", [])]
                    analysis.sections = sections
                    analysis.cut_candidates = detect_cut_candidates(analysis.duration, analysis.beats,
                        analysis.downbeats, analysis.drum_hits, analysis.energy_curve, sections)
                    payload.update(analysis=analysis.model_dump(), duration=analysis.duration)
                    alignment.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    await storage.save(alignment_key, alignment)
                    if cache.exists():
                        await storage.save(cache_key, cache)
                    job.update(status="completed", progress=100, result={"bpm": analysis.bpm,
                        "beats": len(analysis.beats), "cache_hit": analysis.metadata.get("cache_hit", False)})
    except Exception as exc:
        log.exception("Cloud editor operation failed: %s", job_id)
        job.update(status="failed", error=str(exc), message="处理失败")


async def start_job(task_id, kind, options, background, user, db):
    from src.editor_server import _get_user_task
    task = await _get_user_task(db, user.id, task_id)
    if not task.alignment_json_key or not task.input_mp3_key:
        raise HTTPException(404, "任务缺少对齐数据或原曲音频")
    values = options.model_dump(mode='json')
    request_id = values.get('request_id')
    job_id = hashlib.sha256(f'{user.id}:{task_id}:{kind}:{request_id}'.encode()).hexdigest() if request_id else uuid.uuid4().hex
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    if request_id:
        completed = await db.get(VideoExport, job_id)
        if completed:
            if completed.user_id != user.id or completed.task_id != task_id:
                raise HTTPException(404, "Export not found")
            if completed.deleted_at or (completed.details or {}).get("request_fingerprint") != fingerprint:
                raise HTTPException(409, "Start a new export request for deleted videos or changed settings")
            return {"task_id": job_id, "status": "completed"}
    with jobs.lock:
        existing = jobs.get(job_id)
        if existing:
            if existing.get('fingerprint') != fingerprint:
                raise HTTPException(409, '同一请求编号不能用于不同导出设置')
            return {"task_id": job_id, "status": existing['status']}
        jobs[job_id] = {"user_id": user.id, "song_task_id": task_id, "kind": kind,
                        "status": "pending", "progress": 0, "result": None, 'fingerprint': fingerprint}
    background.add_task(run_job, job_id, get_storage(), task.alignment_json_key,
                        task.input_mp3_key, values)
    return {"task_id": job_id, "status": "pending"}


@router.post("/tasks/{task_id}/lyric-video")
async def export_video(task_id: str, options: VideoOptions, background: BackgroundTasks,
                       user: User = Depends(get_current_user_flexible), db: AsyncSession = Depends(get_db)):
    return await start_job(task_id, "video", options, background, user, db)


@router.post("/tasks/{task_id}/analyze")
async def analyze(task_id: str, options: AnalysisOptions, background: BackgroundTasks,
                  user: User = Depends(get_current_user_flexible), db: AsyncSession = Depends(get_db)):
    return await start_job(task_id, "analysis", options, background, user, db)


async def owned_job(job_id, user, db):
    from src.editor_server import _get_user_task
    completed = await db.get(VideoExport, job_id)
    if completed:
        if completed.user_id != user.id or completed.deleted_at:
            raise HTTPException(404, "Export not found")
        await _get_user_task(db, user.id, completed.task_id)
        return {"user_id": user.id, "song_task_id": completed.task_id, "kind": "video",
                "status": "completed", "progress": 100, "message": "Video ready",
                "output_key": completed.storage_key,
                "result": {**(completed.details or {}), "export_id": completed.id,
                           "video_url": f"/api/editor/jobs/{job_id}/video"}}
    job = jobs.get(job_id)
    if not job or job["user_id"] != user.id:
        raise HTTPException(404, "任务不存在或已过期")
    await _get_user_task(db, user.id, job["song_task_id"])
    return job


@router.get("/jobs/{job_id}")
async def job_status(job_id: str, user: User = Depends(get_current_user_flexible), db: AsyncSession = Depends(get_db)):
    job = await owned_job(job_id, user, db)
    return {k: job[k] for k in ("status", "progress", "message", "error", "result") if k in job}


@router.get("/jobs/{job_id}/video")
async def job_video(job_id: str, user: User = Depends(get_current_user_flexible), db: AsyncSession = Depends(get_db)):
    from src.editor_server import _stream_storage_file
    job = await owned_job(job_id, user, db)
    if job["status"] != "completed" or not job.get("output_key"):
        raise HTTPException(404, "视频尚未生成")
    return await _stream_storage_file(get_storage(), job["output_key"])
