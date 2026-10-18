"""
M2V API Server — FastAPI 主应用

面向用户的 Web 服务，提供:
- 用户认证 (注册/登录/JWT)
- 文件上传 (MP3 + 歌词)
- 异步任务管理 (创建/查询/进度)
- WebSocket 实时进度推送
- 文件下载 (结果产物)
- 集成现有时间轴编辑器

启动方式:
    python -m src.api_server
    或: m2v serve
    或: uvicorn src.api_server:app --reload
"""

from __future__ import annotations

from src.version_lifecycle import live_task

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from src.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    get_current_user_flexible,
    get_user_from_token,
    hash_password,
    verify_password,
)
from src.database import async_session, create_tables, get_db
from src.models import Task, TaskStatus, TaskStep, User
from src.schemas import (
    ErrorResponse,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    SunoTaskRequest,
    TaskCreateRequest,
    TaskListResponse,
    TaskProgressEvent,
    TaskResponse,
    TokenResponse,
    UploadResponse,
    UserResponse,
    UserUpdateRequest,
)
from src.settings import get_settings
from src.storage import LocalStorage, get_storage
from src.utils import log
from src.editor_server import router as editor_router

settings = get_settings()


# ======================================================================
# App lifecycle
# ======================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭时执行的初始化逻辑"""
    log.info("🚀 M2V API Server 启动中…")
    # 创建数据库表 (开发用；生产应使用 Alembic)
    await create_tables()
    log.info("✅ 数据库就绪")
    yield
    log.info("👋 M2V API Server 关闭")


app = FastAPI(
    title="M2V — Auto-Karaoke MV Generator",
    version="0.2.0",
    description="面向用户的卡拉OK视频生成服务",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter()


# ======================================================================
# Auth 路由
# ======================================================================

@api_router.post("/api/auth/register", response_model=TokenResponse, tags=["Auth"])
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    # 检查重复
    existing = await db.execute(
        select(User).where((User.email == req.email) | (User.username == req.username))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="邮箱或用户名已被注册",
        )

    user = User(
        email=req.email,
        username=req.username,
        password_hash=hash_password(req.password),
        credits=settings.FREE_MONTHLY_QUOTA,
    )
    db.add(user)
    await db.flush()

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@api_router.post("/api/auth/login", response_model=TokenResponse, tags=["Auth"])
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    user.last_login_at = datetime.now(timezone.utc)

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@api_router.post("/api/auth/refresh", response_model=TokenResponse, tags=["Auth"])
async def refresh_token(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """刷新访问令牌"""
    payload = decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(400, "需要 refresh_token")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(401, "用户不存在或已禁用")

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@api_router.get("/api/auth/me", response_model=UserResponse, tags=["Auth"])
async def get_me(user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        display_name=getattr(user, "display_name", None) or user.username,
        avatar_url=user.avatar_url,
        plan=user.plan.value,
        credits=user.credits,
        is_verified=user.is_verified,
        created_at=user.created_at,
    )


@api_router.patch("/api/auth/me", response_model=UserResponse, tags=["Auth"])
async def update_me(
    req: UserUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新当前用户信息（支持修改显示昵称）"""
    if req.display_name is not None:
        cleaned = req.display_name.strip()
        if len(cleaned) > 64:
            raise HTTPException(400, "昵称不能超过 64 个字符")
        user.display_name = cleaned or None
        await db.commit()
        await db.refresh(user)

    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        display_name=getattr(user, "display_name", None) or user.username,
        avatar_url=user.avatar_url,
        plan=user.plan.value,
        credits=user.credits,
        is_verified=user.is_verified,
        created_at=user.created_at,
    )


def _dispatch_task(task_id: str, mp3_key: str, lyrics_key: str, config_snapshot: dict) -> str | None:
    """提交任务到后台执行：优先尝试 Celery，无 Celery 时启动守护工作线程执行"""
    try:
        from src.worker import process_song_task
        res = process_song_task.delay(
            task_id=task_id,
            mp3_key=mp3_key,
            lyrics_key=lyrics_key,
            config_dict=config_snapshot,
        )
        return str(res.id)
    except Exception as e:
        log.warning("Celery 调度不可用 (%s)，启用在机工作线程兜底执行", e)

    import threading
    def _run():
        try:
            from src.worker import process_song_task
            process_song_task(
                task_id=task_id,
                mp3_key=mp3_key,
                lyrics_key=lyrics_key,
                config_dict=config_snapshot,
            )
        except Exception as ex:
            log.error("在机工作线程执行失败: %s", ex)
            from src.task_lifecycle import record_task_failure
            try:
                record_task_failure(task_id, str(ex))
            except Exception:
                log.exception("记录任务失败与退款异常: task=%s", task_id)

    t = threading.Thread(target=_run, daemon=True, name=f"WorkerThread-{task_id[:8]}")
    t.start()
    return f"thread-{t.name}"


async def _reserve_import(db: AsyncSession, task: Task) -> None:
    """Persist the task and its hold together, before external storage/downloads.

    The unique import claim is flushed first. Concurrent identical imports can
    reuse the winner even when only one credit remains.
    """
    from src.credits import reserve
    db.add(task)
    await db.flush()
    from src.models import AlignmentExecution
    from src.alignment_execution import now, LEASE_SECONDS
    from datetime import timedelta
    db.add(AlignmentExecution(task_id=task.id, token=uuid.uuid4().hex, phase="preparing",
                              lease_until=now()+timedelta(seconds=LEASE_SECONDS)))
    await reserve(db, task.user_id, task.id, "alignment", task.cost_credits)
    await db.commit()


@asynccontextmanager
async def _prepare_import(db, task, storage, cleanup_keys):
    """A failed preparation has a durable task to refund; it never reaches a worker."""
    task_id = task.id
    from src.models import AlignmentExecution
    from src.alignment_execution import heartbeat
    lease = await db.get(AlignmentExecution, task_id)
    try:
        with heartbeat(task_id, lease.token, "preparing"):
            yield
            await db.commit()
    except BaseException:
        await db.rollback()
        from src.task_lifecycle import fail_task_and_refund
        await fail_task_and_refund(db, task_id, "Import file preparation interrupted or failed. Please retry.")
        await db.commit()
        for asset_key in cleanup_keys:
            try:
                await storage.delete(asset_key)
            except Exception:
                log.warning("Import cleanup failed: task=%s", task_id)
        raise


async def _commit_and_dispatch(db: AsyncSession, task: Task) -> None:
    """Hand off a prepared, reserved task once; never revive a cancelled import."""
    from src.models import AlignmentExecution
    from src.alignment_execution import now, QUEUE_SECONDS
    from datetime import timedelta
    task_id = task.id
    active = await db.execute(update(Task).where(
        Task.id == task_id, Task.status == TaskStatus.PENDING,
    ).values(progress=Task.progress, updated_at=Task.updated_at))
    lease = (await db.execute(update(AlignmentExecution).where(
        AlignmentExecution.task_id == task_id, AlignmentExecution.phase == "preparing",
        AlignmentExecution.lease_until > now(),
    ).values(phase="queued", lease_until=now()+timedelta(seconds=QUEUE_SECONDS))
      .returning(AlignmentExecution.token))).scalar_one_or_none() if active.rowcount else None
    if lease is None:
        await db.rollback()
        from src.task_lifecycle import fail_task_and_refund
        await fail_task_and_refund(db, task_id, "Import interrupted before dispatch; credits returned.")
        await db.commit()
        raise HTTPException(409, "Import was interrupted. Please try again.")
    await db.commit()
    try:
        task.celery_task_id = _dispatch_task(
            task.id, task.input_mp3_key, task.input_lyrics_key,
            {**(task.config_snapshot or {}), "_execution_token": lease},
        )
        await db.flush()
    except Exception as exc:
        from src.task_lifecycle import fail_task_and_refund
        await db.rollback()
        await fail_task_and_refund(db, task_id, str(exc))
        await db.commit()
        raise HTTPException(503, "任务无法启动，已退还额度，请稍后重试") from exc


# ======================================================================
# 文件上传 + 创建任务
# ======================================================================

@api_router.post("/api/upload", response_model=UploadResponse, tags=["Tasks"])
async def upload_and_create_task(
    mp3: UploadFile = File(..., description="MP3 音频文件"),

    lyrics: UploadFile = File(..., description="歌词文件 (.txt / .lrc)"),
    song_title: str | None = Query(None, description="歌曲名称"),
    suno_url: str | None = Query(None, description="Suno 歌曲链接"),
    language: str = Query("auto", description="语言代码，默认自动检测"),
    skip_separation: bool = Query(False, description="跳过人声分离"),
    ass_only: bool = Query(False, description="只生成 ASS"),
    beat_effects: bool = Query(False, description="节奏动画"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传音频 + 歌词，创建处理任务"""
    from src.alignment_execution import reconcile
    await reconcile(db, user.id)
    from src.storage_accounting import check_storage_quota
    await check_storage_quota(db, user)
    # 配额检查
    if not ass_only and settings.LYRIC_EXPORT_CREDITS:
        raise HTTPException(409, "Import alignment only, then export from Lyric Editor to review the video credit price.")
    if user.credits <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="配额不足，请升级套餐",
        )

    # 文件类型校验
    if not mp3.filename or not mp3.filename.lower().endswith((".mp3", ".wav", ".flac")):
        raise HTTPException(400, "请上传 MP3/WAV/FLAC 音频文件")
    if not lyrics.filename or not lyrics.filename.lower().endswith((".txt", ".lrc")):
        raise HTTPException(400, "请上传 TXT 或 LRC 歌词文件")

    # 文件大小校验
    max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    mp3_content = await mp3.read()
    if len(mp3_content) > max_size:
        raise HTTPException(400, f"音频文件超过 {settings.MAX_UPLOAD_SIZE_MB}MB 限制")

    lyrics_content = await lyrics.read()
    if len(lyrics_content) > 5 * 1024 * 1024:  # 歌词最大 5MB
        raise HTTPException(400, "歌词文件过大")

    import tempfile
    import re

    def clean_name(raw, fallback):
        return re.sub(r'[^\w.\-\u4e00-\u9fa5]', '_', Path(raw or fallback).name).strip('.') or fallback

    task_id = str(uuid.uuid4())
    prefix = f"uploads/{user.id}/{task_id}"
    mp3_key = f"{prefix}/{clean_name(mp3.filename, 'audio.mp3')}"
    lyrics_key = f"{prefix}/{clean_name(lyrics.filename, 'lyrics.txt')}"
    final_title = (song_title or "").strip() or Path(mp3.filename).stem
    task = Task(
        id=task_id, user_id=user.id, title=final_title, song_title=final_title,
        suno_url=(suno_url or "").strip() or None,
        input_mp3_key=mp3_key, input_lyrics_key=lyrics_key,
        config_snapshot={"language": language, "skip_separation": skip_separation,
                         "ass_only": ass_only, "beat_effects": beat_effects},
    )
    await _reserve_import(db, task)
    storage = get_storage()
    async with _prepare_import(db, task, storage, [mp3_key, lyrics_key]):
        with tempfile.TemporaryDirectory(prefix="m2v-upload-") as directory:
            audio = Path(directory) / ("audio" + Path(mp3.filename).suffix)
            text = Path(directory) / "lyrics.txt"
            audio.write_bytes(mp3_content)
            text.write_bytes(lyrics_content)
            await storage.save(mp3_key, audio)
            await storage.save(lyrics_key, text)
    await _commit_and_dispatch(db, task)
    return UploadResponse(mp3_key=mp3_key, lyrics_key=lyrics_key, task_id=task.id)


@api_router.post("/api/tasks/from-suno", response_model=UploadResponse, tags=["Tasks"])
async def create_task_from_suno(
    req: SunoTaskRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """从 Suno 链接自动拉取歌名、歌词、音频并创建生成任务"""
    from src.alignment_execution import reconcile
    await reconcile(db, user.id)
    clean_url = req.suno_url.strip()
    if not req.ass_only and settings.LYRIC_EXPORT_CREDITS:
        raise HTTPException(409, "Import alignment only, then export from Lyric Editor to review the video credit price.")
    if not clean_url:
        raise HTTPException(400, "请提供有效的 Suno 链接")

    from src.suno_fetch import fetch_song, download_song
    try:
        song = await asyncio.to_thread(fetch_song, clean_url)
    except Exception as e:
        raise HTTPException(400, f"提取 Suno 歌曲失败: {e}")

    song.id = str(song.id).lower()
    canonical_url = f"https://suno.com/song/{song.id}"
    final_title = (req.song_title or song.title or "Suno_Track").strip()
    lyrics_text = (req.lyrics_text if req.lyrics_text is not None else (song.lyrics or song.raw_prompt or "")).strip()
    if not lyrics_text:
        raise HTTPException(400, "未能从 Suno 页面提取到有效歌词，请检查该歌曲")

    from src.suno_import_identity import alignment_options, lyrics_signature, reusable_import, reusable_audio
    storage = get_storage()
    options = {
        "language": req.language,
        "skip_separation": req.skip_separation,
        "ass_only": req.ass_only,
        "beat_effects": req.beat_effects,
    }
    signature = lyrics_signature(lyrics_text)

    async def reuse_response(existing):
        video_job_id = None
        message = "Song and lyrics unchanged. Reusing existing alignment without another alignment charge."
        if not req.ass_only and existing.status == TaskStatus.COMPLETED:
            from src.editor_operations import VideoOptions, start_job
            # Render from the saved (possibly manually edited) timeline. Never
            # dispatch the separation/alignment worker for an output change.
            job = await start_job(existing.id, "video", VideoOptions(aspect_ratio="16:9"),
                                  background, user, db)
            video_job_id = job["task_id"]
            message += " Video is rendering and will appear in My Exports."
        elif not req.ass_only:
            message += " Alignment is still processing; export video from Lyric Editor when it is ready."
        return UploadResponse(mp3_key=existing.input_mp3_key, lyrics_key=existing.input_lyrics_key,
                              task_id=existing.id, video_job_id=video_job_id, message=message)

    if not req.force_realign:
        existing = await reusable_import(db, user.id, song, clean_url, signature, options, storage)
        if existing:
            return await reuse_response(existing)
    if user.credits <= 0:
        raise HTTPException(403, "配额不足，请升级套餐")
    claim = sha256(json.dumps([user.id, song.id, signature, alignment_options(options)], sort_keys=True).encode()).hexdigest()
    if req.force_realign:
        claim = sha256(uuid.uuid4().bytes).hexdigest()
    old_claim = (await db.execute(select(Task).where(Task.idempotency_key == claim))).scalar_one_or_none()
    if old_claim and (old_claim.status in (TaskStatus.PENDING, TaskStatus.PROCESSING) or
                      (old_claim.status == TaskStatus.COMPLETED and old_claim.alignment_json_key and
                       await storage.exists(old_claim.alignment_json_key))):
        return await reuse_response(old_claim)
    if old_claim:
        # A failed or missing-result task is retryable; preserve its history.
        old_claim.idempotency_key = None
        await db.flush()

    import tempfile

    from src.storage_accounting import check_storage_quota
    await check_storage_quota(db, user)
    task_id = str(uuid.uuid4())
    cached_audio = await reusable_audio(db, user.id, song, clean_url, storage)
    owns_audio = cached_audio is None
    mp3_key = cached_audio.input_mp3_key if cached_audio else f"uploads/{user.id}/{task_id}/source.mp3"
    lyrics_key = f"uploads/{user.id}/{task_id}/source.txt"
    task = Task(
        id=task_id, user_id=user.id, title=final_title, song_title=final_title,
        suno_url=canonical_url, input_mp3_key=mp3_key, input_lyrics_key=lyrics_key,
        idempotency_key=claim,
        config_snapshot={**options, "suno_song_id": song.id, "import_lyrics_signature": signature,
                         **({"reuse_stems_from": cached_audio.id} if cached_audio else {})},
    )
    owner_id = user.id
    try:
        await _reserve_import(db, task)
    except IntegrityError:
        await db.rollback()
        existing = (await db.execute(select(Task).where(
            Task.user_id == owner_id, Task.idempotency_key == claim,
        ))).scalar_one_or_none()
        if existing is None:
            raise
        return await reuse_response(existing)

    # Only this request's assets may be cleaned up. Never delete shared audio.
    cleanup = [lyrics_key]
    async with _prepare_import(db, task, storage, cleanup):
        with tempfile.TemporaryDirectory(prefix="m2v-suno-") as download_dir:
            directory = Path(download_dir)
            if owns_audio:
                if not (song.audio_url or song.video_url):
                    raise HTTPException(400, "未能获取 Suno 音频直链")
                try:
                    mp3_tmp, _, _, _ = await asyncio.to_thread(
                        download_song, song, directory, song_name="source",
                        save_json=False, allow_local_fallback=False,
                    )
                except Exception as e:
                    raise HTTPException(400, f"下载 Suno 音频失败: {e}") from e
                if mp3_tmp is None:
                    raise HTTPException(400, "Suno 音频及公开视频音轨均无法读取，请上传有权使用的音频文件")
                mp3_key = f"uploads/{owner_id}/{task_id}/source{mp3_tmp.suffix}"
                task.input_mp3_key = mp3_key
                from src.song_assets import save_source, source_keys
                cleanup.extend([mp3_key, *source_keys(mp3_key)])
                await storage.save(mp3_key, mp3_tmp)
                source_result = await save_source(storage, mp3_key, song)
                task.config_snapshot = {**task.config_snapshot, 'library_artist':source_result['metadata'].get('artist','')}
            lyrics_tmp = directory / "lyrics.txt"
            lyrics_tmp.write_text(lyrics_text, encoding="utf-8")
            await storage.save(lyrics_key, lyrics_tmp)
    await _commit_and_dispatch(db, task)
    return UploadResponse(
        mp3_key=mp3_key, lyrics_key=lyrics_key, task_id=task.id,
        message=f"Suno 歌曲《{final_title}》解析成功，任务已创建",
    )



# ======================================================================
# 任务管理
# ======================================================================

@api_router.get("/api/tasks", response_model=TaskListResponse, tags=["Tasks"])
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的任务列表"""
    from src.alignment_execution import reconcile
    await reconcile(db, user.id)
    # 总数
    count_q = select(func.count(Task.id)).where(Task.user_id == user.id, live_task())
    total = (await db.execute(count_q)).scalar() or 0

    # 分页查询
    query = (
        select(Task)
        .where(Task.user_id == user.id, live_task())
        .order_by(Task.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    tasks = result.scalars().all()

    return TaskListResponse(
        tasks=[_task_to_response(t) for t in tasks],
        total=total,
    )


@api_router.get("/api/tasks/{task_id}", response_model=TaskResponse, tags=["Tasks"])
async def get_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取单个任务详情"""
    from src.alignment_execution import reconcile
    await reconcile(db, user.id)
    task = await _get_user_task(db, user.id, task_id)
    return _task_to_response(task)


@api_router.delete("/api/tasks/{task_id}", response_model=MessageResponse, tags=["Tasks"])
async def delete_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除任务及其文件"""
    task = await _get_user_task(db, user.id, task_id)
    # Serialize task deletion with export publication (same lock ordering).
    locked = await db.execute(update(Task).where(Task.id == task.id).values(progress=Task.progress, updated_at=Task.updated_at))
    if not locked.rowcount:
        raise HTTPException(404, "Task not found")
    await db.refresh(task)
    from src.models import ExportJob, VideoExport
    from src.credits import finish
    render_rows = (await db.execute(select(ExportJob).where(ExportJob.task_id == task.id).with_for_update())).scalars().all()
    if task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING):
        from src.credits import key, legacy_refund
        from src.models import CreditReservation
        if await db.get(CreditReservation, key(user.id, "alignment", task.id)):
            await finish(db, user.id, task.id, "alignment", success=False)
        else:
            await legacy_refund(db, user.id, task.id, task.cost_credits)
    for render in render_rows:
        await finish(db, user.id, render.id, "lyric_export", success=False)
    storage = get_storage()

    # 删除存储文件
    from src.motion_cloud import delete_artifacts
    await delete_artifacts(user.id, task.id, storage)
    from src.song_assets import source_keys
    other_audio_user = (await db.execute(select(Task.id).where(
        Task.id != task.id, Task.input_mp3_key == task.input_mp3_key,
    ).limit(1))).scalar_one_or_none()
    audio_keys = [] if other_audio_user else [task.input_mp3_key, *source_keys(task.input_mp3_key)]
    for key in [
        *audio_keys,
        task.input_lyrics_key,
        task.output_mp4_key,
        task.output_ass_key,
        task.alignment_json_key,
    ]:
        if key:
            try:
                await storage.delete(key)
            except Exception:
                pass

    exports = (await db.execute(select(VideoExport).where(VideoExport.task_id == task.id))).scalars().all()
    for record in exports:
        await storage.delete(record.storage_key)
        await db.delete(record)
    from sqlalchemy import delete
    await db.execute(delete(ExportJob).where(ExportJob.task_id == task.id))
    from src.models import AlignmentExecution
    await db.execute(delete(AlignmentExecution).where(AlignmentExecution.task_id == task.id))
    await db.delete(task)
    return MessageResponse(message="任务已删除")


# ======================================================================
# 文件下载
# ======================================================================

@api_router.get("/api/tasks/{task_id}/download/{file_type}", tags=["Files"])
async def download_file(
    task_id: str,
    file_type: str,
    user: User = Depends(get_current_user_flexible),
    db: AsyncSession = Depends(get_db),
):
    """
    下载任务产物

    file_type: mp4 | ass | alignment | mp3 | lyrics
    """
    task = await _get_user_task(db, user.id, task_id)

    key_map = {
        "mp4": task.output_mp4_key,
        "ass": task.output_ass_key,
        "alignment": task.alignment_json_key,
        "mp3": task.input_mp3_key,
        "lyrics": task.input_lyrics_key,
    }

    key = key_map.get(file_type)
    if not key:
        raise HTTPException(404, f"文件类型 '{file_type}' 不存在或尚未生成")

    storage = get_storage()

    # 本地存储直接返回文件
    if isinstance(storage, LocalStorage):
        local_path = storage.get_local_path(key)
        if not local_path.exists():
            raise HTTPException(404, "文件不存在")
        return FileResponse(
            local_path,
            filename=Path(key).name,
            media_type="application/octet-stream",
        )

    # S3 返回签名 URL 重定向
    url = await storage.get_url(key)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url)


# ======================================================================
# WebSocket 实时进度
# ======================================================================

@api_router.websocket("/ws/tasks/{task_id}/progress")
async def task_progress_ws(websocket: WebSocket, task_id: str):
    """
    WebSocket 端点: 实时推送任务进度 (需鉴权与任务所有权核验)

    客户端连接后，服务端核查令牌与任务归属，若合法则监听 Redis pub/sub 频道并将进度事件转发。
    """
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization") or ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with async_session() as db:
        try:
            user = await get_user_from_token(token, db)
        except Exception:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        task = await db.get(Task, task_id)
        if not task or task.user_id != user.id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await websocket.accept()

    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        pubsub = r.pubsub()
        await pubsub.subscribe(f"task_progress:{task_id}")

        import time
        checked_at = 0.0
        while True:
            if time.monotonic() - checked_at >= 10:
                from src.alignment_execution import reconcile
                async with async_session() as db:
                    await reconcile(db, user.id)
                    await db.commit()
                    current = await db.get(Task, task_id)
                    if current is None:
                        break
                    if current.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                        await websocket.send_text(_task_to_response(current).model_dump_json())
                        break
                checked_at = time.monotonic()
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message and message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                await websocket.send_text(data)

                # 任务完成或失败时关闭
                event = json.loads(data)
                if event.get("current_step") in ("done", "error"):
                    break

            # 心跳 (防止连接超时)
            await asyncio.sleep(0.5)

    except WebSocketDisconnect:
        log.debug("WebSocket 断开: task=%s", task_id)
    except (ImportError, Exception) as e:
        try:
            await websocket.send_text(json.dumps({
                "task_id": task_id,
                "message": f"实时进度不可用 ({e})，请使用轮询 API",
            }))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ======================================================================
# 集成时间轴编辑器 (通过 Router 挂载)
# ======================================================================

from src.export_library import router as export_library_router
api_router.include_router(export_library_router)
from src.credits import router as credits_router
api_router.include_router(credits_router)
from src.song_library import router as song_library_router
api_router.include_router(song_library_router)
from src.storage_accounting import router as storage_accounting_router
api_router.include_router(storage_accounting_router)
from src.backup import router as backup_router
api_router.include_router(backup_router)
app.include_router(api_router)
app.include_router(editor_router)
from src.motion_cloud import router as cloud_motion_router
app.include_router(cloud_motion_router)


# ======================================================================
# 静态文件 (前端)
# ======================================================================

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    local_dir = frontend_dir / "local"
    static_target = local_dir if local_dir.exists() else frontend_dir
    app.mount(
        "/static",
        StaticFiles(directory=str(static_target)),
        name="static",
    )

    @app.get("/", tags=["Frontend"])
    async def serve_dashboard():
        """返回仪表板主页"""
        return FileResponse(frontend_dir / "index.html")

    @app.get("/lyric-editor", tags=["Frontend"])
    @app.get("/lyric-editor/{task_id}", tags=["Frontend"])
    async def serve_editor(task_id: str | None = None):
        """返回时间轴歌词编辑器 (task_id 由前端路由处理)"""
        editor_file = frontend_dir / "lyric-editor.html"
        if not editor_file.exists():
            editor_file = frontend_dir / "local" / "index.html"
        if editor_file.exists():
            return FileResponse(editor_file)
        return FileResponse(frontend_dir / "index.html")

    @app.get("/local", tags=["Frontend"])
    @app.get("/local/{rest:path}", tags=["Frontend"])
    async def retired_local_pages(rest: str = ""):
        """Retired public pages must not expose internal HTML source files."""
        raise HTTPException(404, "页面地址已更新，请从首页进入")

    @app.get("/storyboard", tags=["Frontend"])
    async def serve_storyboard():
        sb_file = frontend_dir / "storyboard.html"
        if not sb_file.exists():
            sb_file = frontend_dir / "local" / "storyboard.html"
        if sb_file.exists():
            return FileResponse(sb_file)
        return FileResponse(frontend_dir / "index.html")

    @app.get("/rhythm-studio", tags=["Frontend"])
    async def serve_rhythm_studio():
        return FileResponse(frontend_dir / "rhythm-studio.html")

    @app.get("/motion-studio", tags=["Frontend"])
    async def serve_motion_studio():
        ms_file = frontend_dir / "motion-studio.html"
        if not ms_file.exists():
            ms_file = frontend_dir / "local" / "motion_studio_director.html"
        if ms_file.exists():
            return FileResponse(ms_file)
        return FileResponse(frontend_dir / "index.html")

    @app.get("/motion-lab", tags=["Frontend"])
    async def serve_motion_lab():
        return FileResponse(frontend_dir / "motion-lab.html")

    @app.get("/gallery", tags=["Frontend"])
    async def serve_gallery():
        g_file = frontend_dir / "gallery.html"
        if not g_file.exists():
            g_file = frontend_dir / "local" / "gallery.html"
        if g_file.exists():
            return FileResponse(g_file)
        return FileResponse(frontend_dir / "index.html")

    app.mount("/", StaticFiles(directory=str(frontend_dir)), name="frontend_root")


# ======================================================================
# 辅助函数
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


def _task_to_response(task: Task) -> TaskResponse:
    """ORM 对象转 Pydantic 响应"""
    return TaskResponse(
        id=task.id,
        title=task.title,
        song_title=task.song_title or task.title,
        suno_url=task.suno_url,
        status=task.status.value if isinstance(task.status, TaskStatus) else task.status,
        current_step=task.current_step.value if isinstance(task.current_step, TaskStep) else task.current_step,
        progress=task.progress,
        input_mp3_key=task.input_mp3_key,
        input_lyrics_key=task.input_lyrics_key,
        output_mp4_key=task.output_mp4_key,
        output_ass_key=task.output_ass_key,
        alignment_json_key=task.alignment_json_key,
        error_message=task.error_message,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )


# ======================================================================
# CLI 入口
# ======================================================================

def run_server(host: str | None = None, port: int | None = None) -> None:
    """启动 API 服务"""
    import uvicorn
    uvicorn.run(
        "src.api_server:app",
        host=host or settings.HOST,
        port=port or settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )


if __name__ == "__main__":
    run_server()
