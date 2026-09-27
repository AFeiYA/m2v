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

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from celery import Celery

from src.settings import get_settings

settings = get_settings()

# ── Celery 实例 ──────────────────────────────────────────

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


# ── 数据库同步更新（在 worker 进程中使用同步 SQLAlchemy）──

def _get_sync_engine():
    """Worker 中使用同步数据库连接"""
    from sqlalchemy import create_engine

    # 把 async URL 转换为 sync URL
    url = settings.DATABASE_URL
    url = url.replace("sqlite+aiosqlite", "sqlite")
    url = url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    return create_engine(url)


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
    """同步更新数据库 Task 记录"""
    from sqlalchemy.orm import Session
    from src.models import Task

    engine = _get_sync_engine()
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if task is None:
            return
        if status is not None:
            task.status = status
        if current_step is not None:
            task.current_step = current_step
        if progress is not None:
            task.progress = progress
        if error_message is not None:
            task.error_message = error_message
        if output_mp4_key is not None:
            task.output_mp4_key = output_mp4_key
        if output_ass_key is not None:
            task.output_ass_key = output_ass_key
        if alignment_json_key is not None:
            task.alignment_json_key = alignment_json_key
        if started_at is not None:
            task.started_at = started_at
        if completed_at is not None:
            task.completed_at = completed_at
        session.commit()


# ── Pipeline 任务 ────────────────────────────────────────

@celery_app.task(bind=True, name="m2v.process_song")
def process_song_task(
    self,
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

    storage = get_storage()

    # 更新: 开始处理
    _update_task_status(
        task_id,
        status="processing",
        current_step="queued",
        progress=0,
        started_at=datetime.now(timezone.utc),
    )
    _publish_progress(task_id, "queued", 0, "任务开始处理…")

    # 创建临时工作目录
    temp_dir = Path(tempfile.mkdtemp(prefix=f"m2v_task_{task_id[:8]}_"))

    try:
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
                config.aligner.language = config_dict["language"]
            if config_dict.get("skip_separation"):
                config.skip_separation = True
            if config_dict.get("ass_only"):
                config.ass_only = True
            if config_dict.get("beat_effects"):
                config.subtitle.enable_beat_effects = True

        # ── 进度回调 ─────────────────────────────────
        step_map = {
            "preprocessing": ("preprocessing", 10),
            "separating": ("separating", 30),
            "aligning": ("aligning", 60),
            "subtitle": ("subtitle", 80),
            "compositing": ("compositing", 90),
        }

        def on_progress(step: str, progress: int, message: str = ""):
            mapped = step_map.get(step, (step, progress))
            _update_task_status(
                task_id,
                current_step=mapped[0],
                progress=mapped[1],
            )
            _publish_progress(task_id, mapped[0], mapped[1], message)

        # ── 执行 pipeline ────────────────────────────
        output_dir = temp_dir / "output"
        output_dir.mkdir()

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
        if align_json.exists():
            key = f"results/{task_id}/{align_json.name}"
            loop.run_until_complete(storage.save(key, align_json))
            result_keys["alignment_json_key"] = key

        # ASS 字幕
        ass_file = output_dir / f"{stem}.ass"
        if ass_file.exists():
            key = f"results/{task_id}/{ass_file.name}"
            loop.run_until_complete(storage.save(key, ass_file))
            result_keys["output_ass_key"] = key

        # MP4 视频
        mp4_file = output_dir / f"{stem}.mp4"
        if mp4_file.exists():
            key = f"results/{task_id}/{mp4_file.name}"
            loop.run_until_complete(storage.save(key, mp4_file))
            result_keys["output_mp4_key"] = key

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
        _update_task_status(
            task_id,
            status="failed",
            current_step="error",
            error_message=str(e),
            completed_at=datetime.now(timezone.utc),
        )
        _publish_progress(task_id, "error", -1, f"❌ 处理失败: {e}")
        raise

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)
