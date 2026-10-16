"""
Celery Worker — 异步执行 pipeline 任务

启动方式:
    celery -A src.worker worker --loglevel=info --concurrency=1 -Q m2v
    (GPU 任务建议 concurrency=1)

任务流程:
    1. 从存储下载 MP3 + 歌词到临时目录
    2. 运行 pipeline (process_one)，通过 Redis pub/sub 推送进度
    3. 上传产物到存储
    4. 更新数据库 Task 记录
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.settings import get_settings

log = logging.getLogger("m2v.worker")
settings = get_settings()

try:
    from celery import Celery

    celery_app = Celery(
        "m2v",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
    )

    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        task_track_started=True,
        task_default_queue="m2v",
        # GPU 任务防止 prefetch 抢占
        worker_prefetch_multiplier=1,
        # 单个任务最长 30 分钟
        task_time_limit=1800,
        task_soft_time_limit=1500,
    )
    _task_decorator = celery_app.task(name="m2v.process_song")
except Exception:
    celery_app = None

    def _task_decorator(func):
        def _dummy_delay(*args, **kwargs):
            raise RuntimeError("Celery 未安装或不可用")

        func.delay = _dummy_delay
        return func


# ── 进度推送 ─────────────────────────────────────────────

def _publish_progress(task_id: str, step: str, progress: int, message: str = ""):
    """通过 Redis pub/sub 推送进度到 WebSocket 层"""
    try:
        import redis
        r = redis.from_url(settings.REDIS_URL)
        event = json.dumps({
            "task_id": task_id,
            "status": "processing",
            "current_step": step,
            "progress": progress,
            "message": message,
        }, ensure_ascii=False)
        r.publish(f"task_progress:{task_id}", event)
    except Exception:
        pass  # 进度推送失败不影响主流程


# ── 数据库更新（复用 asyncpg）────────────────────────────


def _update_task_status(
    task_id: str,
    *,
    status: str | None = None,
    current_step: str | None = None,
    progress: int | None = None,
    error_message: str | None = None,
    output_mp4_key: str | None = None,
    output_ass_key: str | None = None,
    alignment_json_key: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
):
    """在 Celery worker 中同步入口调用异步数据库更新"""
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from src.models import Task, TaskStep, TaskStatus

    async def _inner():
        values = {}
        if status is not None:
            values["status"] = status
        if current_step is not None:
            valid_steps = {s.value for s in TaskStep}
            val = current_step.value if isinstance(current_step, TaskStep) else str(current_step)
            if val not in valid_steps:
                val = TaskStep.ALIGNING.value
            values["current_step"] = val
        if progress is not None:
            values["progress"] = progress
        if error_message is not None:
            values["error_message"] = error_message
        if output_mp4_key is not None:
            values["output_mp4_key"] = output_mp4_key
        if output_ass_key is not None:
            values["output_ass_key"] = output_ass_key
        if alignment_json_key is not None:
            values["alignment_json_key"] = alignment_json_key
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at
        if not values:
            return

        engine = create_async_engine(
            settings.DATABASE_URL,
            poolclass=NullPool,
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                changed = await session.execute(
                    update(Task)
                    .where(Task.id == task_id, Task.status.in_([TaskStatus.PENDING, TaskStatus.PROCESSING]))
                    .values(**values)
                )
                if status == "completed" and changed.rowcount:
                    from src.credits import finish
                    task = await session.get(Task, task_id)
                    await finish(session, task.user_id, task_id, "alignment", success=True)
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_inner())


# ── Pipeline 任务 ────────────────────────────────────────

@_task_decorator
def process_song_task(
    task_id: str,
    mp3_key: str,
    lyrics_key: str,
    config_dict: dict | None = None,
):
    """
    Celery 任务: 下载文件 → 运行 pipeline → 上传结果 → 更新 DB

    Args:
        task_id:     数据库 Task.id
        mp3_key:     存储中的 MP3 文件 key
        lyrics_key:  存储中的歌词文件 key
        config_dict: pipeline 配置 (可选)
    """
    import asyncio
    from src.storage import get_storage
    from src.config import PipelineConfig

    temp_dir = None
    loop = None
    try:
        storage = get_storage()
        _update_task_status(
            task_id, status="processing", current_step="queued", progress=0,
            started_at=datetime.now(timezone.utc),
        )
        _publish_progress(task_id, "queued", 0, "任务开始处理…")
        temp_dir = Path(tempfile.mkdtemp(prefix=f"m2v_task_{task_id[:8]}_"))
        # ── 下载输入文件 ──────────────────────────────
        mp3_local = temp_dir / Path(mp3_key).name
        lyrics_local = temp_dir / Path(lyrics_key).name

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(storage.load(mp3_key, mp3_local))
        loop.run_until_complete(storage.load(lyrics_key, lyrics_local))

        # ── 构建 pipeline 配置 ────────────────────────
        config = PipelineConfig()
        if config_dict:
            if config_dict.get("language"):
                config.aligner.language = str(config_dict["language"])
            if "skip_separation" in config_dict:
                config.skip_separation = bool(config_dict["skip_separation"])
            if "ass_only" in config_dict:
                config.ass_only = bool(config_dict["ass_only"])
            if "beat_effects" in config_dict:
                config.subtitle.enable_beat_effects = bool(config_dict["beat_effects"])

        # ── 进度回调 ─────────────────────────────────
        from src.models import TaskStep
        step_map = {
            "queued": TaskStep.QUEUED.value,
            "preprocessing": TaskStep.PREPROCESSING.value,
            "separating": TaskStep.SEPARATING.value,
            "aligning": TaskStep.ALIGNING.value,
            "analyzing": TaskStep.ALIGNING.value,
            "subtitle": TaskStep.SUBTITLE.value,
            "compositing": TaskStep.COMPOSITING.value,
            "done": TaskStep.DONE.value,
            "error": TaskStep.ERROR.value,
        }

        def on_progress(step: str, progress: int, message: str = ""):
            mapped_step = step_map.get(step, TaskStep.ALIGNING.value)
            actual_progress = int(progress) if progress is not None else 0
            try:
                _update_task_status(
                    task_id,
                    current_step=mapped_step,
                    progress=actual_progress,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("任务 %s 状态写入数据库失败 (不中断计算流程): %s", task_id, exc)

            _publish_progress(task_id, mapped_step, actual_progress, message)

        # ── 执行 pipeline ────────────────────────────
        output_dir = temp_dir / "output"
        output_dir.mkdir()

        # Reuse an owner-verified previous task's stems, never its alignment JSON.
        # Missing/deleted stems fall back to the normal separation pipeline.
        previous = (config_dict or {}).get("reuse_stems_from")
        if previous and not config.skip_separation:
            for track in ("vocals", "instrumental"):
                for extension in ("wav", "mp3", "flac"):
                    name = f"{mp3_local.stem}_{track}.{extension}"
                    key = f"results/{previous}/{name}"
                    target = output_dir / name
                    try:
                        if loop.run_until_complete(storage.exists(key)):
                            loop.run_until_complete(storage.load(key, target))
                            break
                    except Exception as exc:
                        target.unlink(missing_ok=True)
                        log.warning("分离音轨缓存不可用，将重新分离: %s", type(exc).__name__)

        from src.main import process_one
        result_path = process_one(
            mp3_path=mp3_local,
            lyrics_path=lyrics_local,
            output_dir=output_dir,
            background=None,
            config=config,
            on_progress=on_progress,
        )

        # ── 上传结果 ─────────────────────────────────
        stem = mp3_local.stem
        result_keys = {}

        # alignment JSON
        align_json = output_dir / f"{stem}_alignment.json"
        if not align_json.is_file() or align_json.stat().st_size == 0:
            raise RuntimeError("Alignment result was not generated; credits will be returned")
        if align_json.exists():
            from src.song_assets import source_keys
            from src.song_sections import bind_source_sections
            metadata_key, _ = source_keys(mp3_key)
            if loop.run_until_complete(storage.exists(metadata_key)):
                metadata_path = temp_dir / 'source_suno.json'
                loop.run_until_complete(storage.load(metadata_key, metadata_path))
                metadata = json.loads(metadata_path.read_text())
                payload = json.loads(align_json.read_text())
                if bind_source_sections(payload, metadata.get('sections') or []):
                    align_json.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            key = f"results/{task_id}/{align_json.name}"
            loop.run_until_complete(storage.save(key, align_json))
            if not loop.run_until_complete(storage.exists(key)):
                raise RuntimeError("Alignment upload could not be verified")
            size = loop.run_until_complete(storage.get_size(key))
            if size is not None and size != align_json.stat().st_size:
                raise RuntimeError("Alignment upload size mismatch")
            result_keys["alignment_json_key"] = key

        # ASS 字幕
        ass_file = output_dir / f"{stem}.ass"
        if not ass_file.is_file() or ass_file.stat().st_size == 0:
            raise RuntimeError("Subtitle result was not generated; credits will be returned")
        if ass_file.exists():
            key = f"results/{task_id}/{ass_file.name}"
            loop.run_until_complete(storage.save(key, ass_file))
            if not loop.run_until_complete(storage.exists(key)):
                raise RuntimeError("Subtitle upload could not be verified")
            size = loop.run_until_complete(storage.get_size(key))
            if size is not None and size != ass_file.stat().st_size:
                raise RuntimeError("Subtitle upload size mismatch")
            result_keys["output_ass_key"] = key

        # MP4 视频
        mp4_file = output_dir / f"{stem}.mp4"
        if mp4_file.exists():
            key = f"results/{task_id}/{mp4_file.name}"
            loop.run_until_complete(storage.save(key, mp4_file))
            result_keys["output_mp4_key"] = key

        # 人声与伴奏音轨 (供双轨时间轴编辑器试听与微调)
        for vf in list(output_dir.glob(f"{stem}_vocals.*")) + list(output_dir.glob("source_vocals.*")):
            v_key = f"results/{task_id}/{vf.name}"
            loop.run_until_complete(storage.save(v_key, vf))
            break

        for inf in list(output_dir.glob(f"{stem}_instrumental.*")) + list(output_dir.glob("source_instrumental.*")):
            i_key = f"results/{task_id}/{inf.name}"
            loop.run_until_complete(storage.save(i_key, inf))
            break

        loop.close()

        # ── 更新完成状态 ─────────────────────────────
        _update_task_status(
            task_id,
            status="completed",
            current_step="done",
            progress=100,
            completed_at=datetime.now(timezone.utc),
            **result_keys,
        )
        _publish_progress(task_id, "done", 100, "✅ 处理完成！")

        return {"status": "completed", "task_id": task_id, **result_keys}

    except Exception as e:
        from src.task_lifecycle import record_task_failure
        record_task_failure(task_id, str(e))
        _publish_progress(task_id, "error", -1, f"❌ 处理失败: {e}")
        raise

    finally:
        if loop is not None and not loop.is_closed():
            loop.close()
        # 清理临时目录
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
