"""
卡拉OK 时间轴编辑器 — APIRouter 模块

所有编辑器 API 作为 FastAPI Router 挂载到主 api_server 中。
通过 task_id 访问文件（走存储层 + 认证），不再直接读写本地目录。

路由前缀: /api/editor
"""

from __future__ import annotations

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
from src.models import Task, TaskStatus, User
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
            Task.user_id == user.id,
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


# ======================================================================
# 获取 / 保存对齐 JSON
# ======================================================================

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
        return await _load_alignment(storage, task.alignment_json_key)
    except FileNotFoundError as exc:
        log.warning("对齐文件缺失: task=%s key=%s", task.id, task.alignment_json_key)
        raise HTTPException(404, "Alignment file is missing from storage. Please import and align this song again.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(422, "Alignment file is invalid. Please import and align this song again.") from exc
    except Exception as exc:
        log.warning("读取任务对齐数据失败: %s (%s)", task.id, type(exc).__name__)
        raise HTTPException(503, "Unable to load alignment from storage. Please retry later.") from exc


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

    log.info("对齐 JSON 已保存: task=%s, version=%s", task_id, version)
    return {"status": "ok", "task_id": task_id, "version": version}


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
# 重新生成 ASS / 视频
# ======================================================================

@router.post("/tasks/{task_id}/regen")
async def regenerate(
    task_id: str,
    request: Request,
    user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """从编辑后的 alignment JSON 重新生成 ASS / MP4"""
    task = await _get_user_task(db, user.id, task_id)
    if not task.alignment_json_key:
        raise HTTPException(404, "该任务没有对齐数据")

    body = await request.json()
    mode = body.get("mode", "ass")
    storage = get_storage()

    work_dir = Path(tempfile.mkdtemp(prefix=f"m2v_regen_{task_id[:8]}_"))

    try:
        # 下载 alignment JSON
        align_local = work_dir / "alignment.json"
        await storage.load(task.alignment_json_key, align_local)

        from src.aligner import AlignmentResult
        from src.subtitle import generate_ass
        from src.config import SubtitleConfig, CompositorConfig

        alignment = AlignmentResult.load_json(align_local)
        ass_path = work_dir / f"{task.title}.ass"

        # 下载音频
        audio_local = None
        if task.input_mp3_key:
            audio_local = work_dir / Path(task.input_mp3_key).name
            await storage.load(task.input_mp3_key, audio_local)

        generate_ass(
            alignment=alignment,
            output_path=ass_path,
            audio_path=audio_local,
        )

        # 上传 ASS
        ass_key = f"results/{task_id}/{task.title}.ass"
        await storage.save(ass_key, ass_path)
        task.output_ass_key = ass_key

        if mode == "video" and audio_local:
            from src.compositor import compose_video
            mp4_path = work_dir / f"{task.title}.mp4"
            compose_video(
                audio_path=audio_local,
                subtitle_path=ass_path,
                output_path=mp4_path,
                config=CompositorConfig(),
            )
            mp4_key = f"results/{task_id}/{task.title}.mp4"
            await storage.save(mp4_key, mp4_path)
            task.output_mp4_key = mp4_key
            await db.flush()
            return {"status": "ok", "mode": "video", "task_id": task_id}

        await db.flush()
        return {"status": "ok", "mode": "ass", "task_id": task_id}

    except Exception as e:
        log.error("重新生成失败: %s", e, exc_info=True)
        raise HTTPException(500, str(e))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


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
        select(Task).where(Task.id == task_id, Task.user_id == user_id)
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
