"""
卡拉OK 时间轴编辑器 — APIRouter 模块

所有编辑器 API 作为 FastAPI Router 挂载到主 api_server 中。
通过 task_id 访问文件（走存储层 + 认证），不再直接读写本地目录。

路由前缀: /api/editor
"""

from __future__ import annotations

from src.version_lifecycle import live_task

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_flexible
from src.database import get_db
from src.editor_operations import router as operations_router
from src.models import Task, TaskStatus, TaskStep, User
from src.schemas import RealignTaskRequest
from src.storage import LocalStorage, get_storage
from src.utils import log

router = APIRouter(prefix="/api/editor", tags=["Editor"])


# ======================================================================
# 列出可编辑的歌曲 (已完成的任务)
# ======================================================================

@router.get("/songs")
async def list_songs(
    user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """列出当前用户所有可编辑的歌曲（有 alignment 的任务）"""
    result = await db.execute(
        select(Task)
        .where(
            Task.user_id == user.id, live_task(),
            Task.alignment_json_key.isnot(None),
        )
        .order_by(Task.created_at.desc())
    )
    tasks = result.scalars().all()
    storage = get_storage()

    songs = []
    for task in tasks:
        lines_count = 0
        duration = 0.0
        try:
            align_data = await _load_alignment(storage, task.alignment_json_key)
            lines = align_data.get("lines", [])
            lines_count = len(lines)
            if lines:
                duration = lines[-1].get("end", 0)
        except FileNotFoundError:
            log.warning("跳过缺少对齐文件的任务: task=%s key=%s", task.id, task.alignment_json_key)
            continue
        except Exception as exc:
            log.warning("读取任务对齐数据失败: %s (%s)", task.id, type(exc).__name__)
            raise HTTPException(503, "Unable to load song data. Please retry later.") from exc

        title = task.song_title or task.title or "Untitled"
        updated_dt = getattr(task, "updated_at", None) or task.completed_at or task.created_at
        version = str(int(updated_dt.timestamp())) if updated_dt else "1"
        songs.append({
            "task_id": task.id,
            "name": title,
            "stem": title,
            "version": version,
            "has_alignment": True,
            "has_audio": task.input_mp3_key is not None,
            "has_vocals": await _find_track_key(storage, task, "vocals") is not None,
            "has_instrumental": await _find_track_key(storage, task, "instrumental") is not None,
            "lines_count": lines_count,
            "duration": round(duration, 1),
            "status": task.status.value if isinstance(task.status, TaskStatus) else task.status,
        })

    return songs


@router.get("/tasks/{task_id}/info")
async def song_info(task_id: str, user: User = Depends(get_current_user_flexible), db: AsyncSession = Depends(get_db)):
    task = await _get_user_task(db, user.id, task_id)
    if not task.alignment_json_key:
        raise HTTPException(404, "Alignment is not ready")
    storage = get_storage()
    return {"task_id":task.id,"name":task.song_title or task.title,"version":str(int((task.updated_at or task.created_at).timestamp())),
            "has_vocals":await _find_track_key(storage,task,"vocals") is not None,
            "has_instrumental":await _find_track_key(storage,task,"instrumental") is not None}


# ======================================================================
# 获取 / 保存对齐 JSON
# ======================================================================

async def _hydrate_source_sections(storage, task: Task, payload: dict) -> dict:
    """Bind source_suno.json sections into alignment payload when missing."""
    if not isinstance(payload, dict) or payload.get("sections") or not task.input_mp3_key:
        return payload
    from src.song_assets import source_keys
    from src.song_sections import bind_source_sections
    metadata_key, _ = source_keys(task.input_mp3_key)
    if metadata_key and await storage.exists(metadata_key):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            meta_path = Path(tmp.name)
        try:
            await storage.load(metadata_key, meta_path)
            bind_source_sections(payload, json.loads(meta_path.read_text(encoding="utf-8")))
        except Exception as exc:
            log.debug("绑定源歌曲段落跳过: task=%s (%s)", task.id, type(exc).__name__)
        finally:
            meta_path.unlink(missing_ok=True)
    return payload


@router.get("/tasks/{task_id}/align")
async def get_alignment(
    task_id: str,
    response: Response,
    user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """获取任务的对齐 JSON"""
    task = await _get_user_task(db, user.id, task_id)
    if not task.alignment_json_key:
        raise HTTPException(404, "该任务没有对齐数据")

    updated_dt = getattr(task, "updated_at", None) or task.completed_at or task.created_at
    if updated_dt:
        response.headers["X-Resource-Version"] = str(int(updated_dt.timestamp()))

    storage = get_storage()
    try:
        payload = await _load_alignment(storage, task.alignment_json_key)
        return await _hydrate_source_sections(storage, task, payload)
    except FileNotFoundError as exc:
        log.warning("对齐文件缺失: task=%s key=%s", task.id, task.alignment_json_key)
        raise HTTPException(404, "Alignment file is missing from storage. Please import and align this song again.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(422, "Alignment file is invalid. Please import and align this song again.") from exc
    except Exception as exc:
        log.warning("读取任务对齐数据失败: %s (%s)", task.id, type(exc).__name__)
        raise HTTPException(503, "Unable to load alignment from storage. Please retry later.") from exc


@router.get("/tasks/{task_id}/review")
async def get_task_review(
    task_id: str,
    user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """获取对齐时间异常审查结果与智能高光切片推荐（纯只读分析，不篡改原时间戳）"""
    from src.editing_review import (
        PORTRAIT_SAFE_AREA,
        inspect_timing_anomalies,
        recommend_excerpt_candidates,
    )

    task = await _get_user_task(db, user.id, task_id)
    if not task.alignment_json_key:
        raise HTTPException(404, "该任务没有对齐数据")

    storage = get_storage()
    try:
        payload = await _load_alignment(storage, task.alignment_json_key)
        payload = await _hydrate_source_sections(storage, task, payload)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Alignment file is missing from storage.") from exc

    return {
        "task_id": task_id,
        "timing_review": inspect_timing_anomalies(payload),
        "excerpt_candidates": recommend_excerpt_candidates(payload),
        "safe_area": PORTRAIT_SAFE_AREA,
    }


@router.put("/tasks/{task_id}/align")
async def save_alignment(
    task_id: str,
    request: Request,
    user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """保存编辑后的对齐 JSON（带校验 + 备份）"""
    task = await _get_user_task(db, user.id, task_id)
    if not task.alignment_json_key:
        raise HTTPException(404, "该任务没有对齐数据")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "无效的 JSON")

    errors = validate_alignment(data)
    if errors:
        raise HTTPException(422, {"errors": errors})

    storage = get_storage()

    # 备份旧版本
    bak_key = task.alignment_json_key + ".bak"
    if isinstance(storage, LocalStorage):
        src = storage.get_local_path(task.alignment_json_key)
        if src.exists():
            dst = storage.get_local_path(bak_key)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))

    # 写入新数据
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        tmp_path = Path(f.name)

    try:
        await storage.save(task.alignment_json_key, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    task.updated_at = datetime.now(timezone.utc)
    await db.commit()
    version = str(int(task.updated_at.timestamp()))

    from src.editing_review import inspect_timing_anomalies
    timing_review = inspect_timing_anomalies(data)

    log.info("对齐 JSON 已保存: task=%s, version=%s", task_id, version)
    return {"status": "ok", "task_id": task_id, "version": version, "timing_review": timing_review}


# ======================================================================
# 重新对齐（编辑歌词文本，扣除 20 积分并单版本原地覆盖）
# ======================================================================

@router.post("/tasks/{task_id}/realign")
async def realign_lyrics(
    task_id: str,
    req: RealignTaskRequest,
    user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """用户编辑歌词后重新运行声学对齐（扣除 20 积分，保留单版本原地覆盖）"""
    task = await _get_user_task(db, user.id, task_id)
    new_lyrics = req.lyrics_text.strip()
    if not new_lyrics:
        raise HTTPException(400, "歌词内容不能为空")

    if task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING):
        raise HTTPException(409, "当前歌曲正在对齐处理中，请稍候再试")

    storage = get_storage()
    if not task.input_mp3_key or not await storage.exists(task.input_mp3_key):
        raise HTTPException(404, "原歌曲音频文件缺失，无法重新对齐")

    # 检查歌词是否发生实质变化：若歌词内容完全一致，则无需重新对齐与扣费（先于余额校验）
    from src.suno_import_identity import lyrics_signature
    new_signature = lyrics_signature(new_lyrics)
    old_signature = (task.config_snapshot or {}).get("import_lyrics_signature")
    if old_signature == new_signature:
        return {
            "status": "unchanged",
            "task_id": task.id,
            "cost_credits": 0,
            "message": "歌词文本未发生变化，无需重新对齐 (0 积分消耗)",
        }

    # 积分校验与扣除 (20 积分)
    from src.settings import get_settings
    from src.credits import lock_balance, reserve
    cost = get_settings().ALIGNMENT_CREDITS
    current_credits = await lock_balance(db, user.id)
    if current_credits < cost:
        raise HTTPException(403, f"积分不足。重新对齐需消耗 {cost} 积分，当前余额: {current_credits} 积分")

    # 1. 预留扣除 20 积分 (使用 task.id 作为 operation_id，支持 allow_reopen=True)。
    #    先扣费再写入歌词文件，避免扣费失败时存储中的歌词已被覆盖。
    task.cost_credits = cost
    await reserve(db, user.id, task.id, "alignment", cost, allow_reopen=True)

    # 2. 写入新的歌词文本到 storage
    lyrics_key = f"uploads/{user.id}/{task.id}/source.txt"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as f:
        f.write(new_lyrics)
        tmp_lyrics_p = Path(f.name)
    try:
        await storage.save(lyrics_key, tmp_lyrics_p)
    finally:
        tmp_lyrics_p.unlink(missing_ok=True)

    task.input_lyrics_key = lyrics_key

    # 3. 设置 AlignmentExecution 租约与 execution_token
    import uuid
    from datetime import timedelta
    from src.models import AlignmentExecution
    from src.alignment_execution import now, QUEUE_SECONDS
    token = uuid.uuid4().hex
    exec_row = await db.get(AlignmentExecution, task.id)
    if exec_row:
        exec_row.token = token
        exec_row.phase = "queued"
        exec_row.lease_until = now() + timedelta(seconds=QUEUE_SECONDS)
    else:
        exec_row = AlignmentExecution(
            task_id=task.id,
            token=token,
            phase="queued",
            lease_until=now() + timedelta(seconds=QUEUE_SECONDS),
        )
        db.add(exec_row)

    # 4. 更新 Task 状态和标记：单版本模型，打上 is_custom_lyrics 标记，状态置为 PENDING 供 managed_worker claim
    snapshot = dict(task.config_snapshot or {})
    snapshot.update({
        "language": req.language or snapshot.get("language", "auto"),
        "skip_separation": req.skip_separation,
        "is_custom_lyrics": True,
        "import_lyrics_signature": new_signature,
        "custom_realigned_at": datetime.now(timezone.utc).isoformat(),
        "reuse_stems_from": task.id,  # 复用当前任务已分离的人声干音
        "_execution_token": token,
    })
    task.config_snapshot = snapshot
    task.status = TaskStatus.PENDING
    task.current_step = TaskStep.QUEUED
    task.progress = 0
    task.error_message = None
    task.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # 5. 派发后台 Worker
    from src.api_server import _dispatch_task
    task.celery_task_id = _dispatch_task(
        task.id, task.input_mp3_key, task.input_lyrics_key, task.config_snapshot
    )
    await db.commit()

    log.info("已提交歌词重新对齐: task=%s, user=%s, cost=%s", task.id, user.id, cost)
    return {
        "status": "processing",
        "task_id": task.id,
        "cost_credits": cost,
        "message": "已提交重新对齐，正在后台处理中…",
    }


# ======================================================================
# 音频流
# ======================================================================

async def _stream_storage_file(storage, key: str):
    suffix = Path(key).suffix.lower()
    media_type = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac",
                  ".m4a": "audio/mp4", ".mp4": "video/mp4"}.get(suffix, "application/octet-stream")
    if isinstance(storage, LocalStorage):
        local_path = storage.get_local_path(key)
        if not local_path.exists():
            raise HTTPException(404, "音频文件不存在")
        return FileResponse(local_path, media_type=media_type)

    # The owner has already been checked by the calling route. Serve private
    # objects through this origin: browser fetch must not follow an R2 redirect
    # that depends on bucket CORS or an obsolete public-domain configuration.
    with tempfile.NamedTemporaryFile(prefix="m2v-editor-media-", suffix=suffix, delete=False) as f:
        local_path = Path(f.name)
    try:
        await storage.load(key, local_path)
    except Exception as exc:
        local_path.unlink(missing_ok=True)
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if isinstance(exc, FileNotFoundError) or code in ("NoSuchKey", "NotFound", "404"):
            raise HTTPException(404, "音轨或视频文件不存在") from exc
        log.warning("编辑器媒体读取失败: key=%s error_type=%s code=%s", key, type(exc).__name__, code)
        raise HTTPException(502, "文件存储读取失败，请检查存储配置与权限") from exc
    return FileResponse(
        local_path, media_type=media_type, headers={"Cache-Control": "private, no-store"},
        background=BackgroundTask(local_path.unlink, missing_ok=True),
    )


async def _find_track_key(storage, task, kind):
    stem = Path(task.input_mp3_key).stem if task.input_mp3_key else task.title
    for ext in (".mp3", ".wav", ".flac"):
        for name in (f"{stem}_{kind}{ext}", f"{task.title}_{kind}{ext}", f"{task.id}_{kind}{ext}", f"source_{kind}{ext}"):
            key = f"results/{task.id}/{name}"
            if await storage.exists(key):
                return key
    return None


@router.get("/tasks/{task_id}/audio")
async def get_audio(
    task_id: str,
    user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """返回任务的音频文件"""
    task = await _get_user_task(db, user.id, task_id)
    if not task.input_mp3_key:
        raise HTTPException(404, "该任务没有音频文件")

    storage = get_storage()
    return await _stream_storage_file(storage, task.input_mp3_key)


@router.get("/tasks/{task_id}/vocals")
async def get_vocals(
    task_id: str,
    user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """返回任务的人声音轨文件"""
    task = await _get_user_task(db, user.id, task_id)
    storage = get_storage()
    key = await _find_track_key(storage, task, "vocals")
    if key is None:
        raise HTTPException(404, "该任务没有分离人声，请试听原曲")
    return await _stream_storage_file(storage, key)


@router.get("/tasks/{task_id}/inst")
async def get_inst(
    task_id: str,
    user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """返回任务的伴奏音轨文件"""
    task = await _get_user_task(db, user.id, task_id)
    storage = get_storage()
    key = await _find_track_key(storage, task, "instrumental")
    if key is None:
        raise HTTPException(404, "该任务没有分离伴奏")
    return await _stream_storage_file(storage, key)


# ======================================================================
# 校验
# ======================================================================

def validate_alignment(data: dict) -> list[str]:
    """校验 alignment JSON — 仅检查致命错误，宽松容忍编辑偏差"""
    errors = []
    lines = data.get("lines")
    if not isinstance(lines, list):
        return ["'lines' 必须是数组"]

    for i, line in enumerate(lines):
        words = line.get("words", [])
        if not words:
            errors.append(f"第 {i+1} 行: words 为空")
            continue

        # 自动修正 line.start/end 与首末字一致
        line["start"] = words[0].get("start", line.get("start", 0))
        line["end"] = words[-1].get("end", line.get("end", 0))

        for j, w in enumerate(words):
            if w.get("start", 0) < -0.01 or w.get("end", 0) < -0.01:
                errors.append(f"第 {i+1} 行第 {j+1} 字: 时间值 < 0")

        for j, w in enumerate(words):
            if w.get("end", 0) < w.get("start", 0) - 0.01:
                errors.append(
                    f"第 {i+1} 行第 {j+1} 字 '{w.get('word','')}': "
                    f"end({w.get('end',0):.3f}) < start({w.get('start',0):.3f})"
                )

    return errors[:20]


# ======================================================================
# 辅助
# ======================================================================

async def _get_user_task(db: AsyncSession, user_id: str, task_id: str) -> Task:
    """获取属于指定用户的任务，不存在则 404"""
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user_id, live_task())
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


async def _load_alignment(storage, key: str) -> dict:
    """从存储加载 alignment JSON 并解析"""
    if isinstance(storage, LocalStorage):
        local_path = storage.get_local_path(key)
        if not local_path.exists():
            raise FileNotFoundError(f"对齐文件不存在: {key}")
        return json.loads(local_path.read_text(encoding="utf-8"))

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = Path(f.name)
    try:
        await storage.load(key, tmp)
        return json.loads(tmp.read_text(encoding="utf-8"))
    finally:
        tmp.unlink(missing_ok=True)


router.include_router(operations_router)
