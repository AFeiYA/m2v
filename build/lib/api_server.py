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

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
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
    TaskCreateRequest,
    TaskListResponse,
    TaskProgressEvent,
    TaskResponse,
    TokenResponse,
    UploadResponse,
    UserResponse,
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


# ======================================================================
# Auth 路由
# ======================================================================

@app.post("/api/auth/register", response_model=TokenResponse, tags=["Auth"])
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


@app.post("/api/auth/login", response_model=TokenResponse, tags=["Auth"])
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


@app.post("/api/auth/refresh", response_model=TokenResponse, tags=["Auth"])
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


@app.get("/api/auth/me", response_model=UserResponse, tags=["Auth"])
async def get_me(user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        avatar_url=user.avatar_url,
        plan=user.plan.value,
        credits=user.credits,
        is_verified=user.is_verified,
        created_at=user.created_at,
    )


# ======================================================================
# 文件上传 + 创建任务
# ======================================================================

@app.post("/api/upload", response_model=UploadResponse, tags=["Tasks"])
async def upload_and_create_task(
    mp3: UploadFile = File(..., description="MP3 音频文件"),
    lyrics: UploadFile = File(..., description="歌词文件 (.txt / .lrc)"),
    language: str = Query("zh", description="语言代码"),
    skip_separation: bool = Query(False, description="跳过人声分离"),
    ass_only: bool = Query(False, description="只生成 ASS"),
    beat_effects: bool = Query(False, description="节奏动画"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传音频 + 歌词，创建处理任务"""
    # 配额检查
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

    # 创建 Task 记录
    task = Task(
        user_id=user.id,
        title=Path(mp3.filename).stem,
        config_snapshot={
            "language": language,
            "skip_separation": skip_separation,
            "ass_only": ass_only,
            "beat_effects": beat_effects,
        },
    )
    # 先 flush 拿到 task.id
    db.add(task)
    await db.flush()

    # 保存文件到存储
    import tempfile

    storage = get_storage()

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(mp3.filename).suffix) as f:
        f.write(mp3_content)
        mp3_tmp = Path(f.name)

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(lyrics.filename).suffix) as f:
        f.write(lyrics_content)
        lyrics_tmp = Path(f.name)

    try:
        mp3_key = f"uploads/{user.id}/{task.id}/{mp3.filename}"
        lyrics_key = f"uploads/{user.id}/{task.id}/{lyrics.filename}"

        await storage.save(mp3_key, mp3_tmp)
        await storage.save(lyrics_key, lyrics_tmp)

        task.input_mp3_key = mp3_key
        task.input_lyrics_key = lyrics_key
    finally:
        mp3_tmp.unlink(missing_ok=True)
        lyrics_tmp.unlink(missing_ok=True)

    # 扣减配额
    user.credits -= 1

    # 提交到 Celery 队列
    try:
        from src.worker import process_song_task
        celery_result = process_song_task.delay(
            task_id=task.id,
            mp3_key=mp3_key,
            lyrics_key=lyrics_key,
            config_dict=task.config_snapshot,
        )
        task.celery_task_id = celery_result.id
    except Exception as e:
        log.warning("Celery 不可用，任务将保持 pending 状态: %s", e)

    await db.flush()

    return UploadResponse(
        mp3_key=mp3_key,
        lyrics_key=lyrics_key,
        task_id=task.id,
    )


# ======================================================================
# 任务管理
# ======================================================================

@app.get("/api/tasks", response_model=TaskListResponse, tags=["Tasks"])
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的任务列表"""
    # 总数
    count_q = select(func.count(Task.id)).where(Task.user_id == user.id)
    total = (await db.execute(count_q)).scalar() or 0

    # 分页查询
    query = (
        select(Task)
        .where(Task.user_id == user.id)
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


@app.get("/api/tasks/{task_id}", response_model=TaskResponse, tags=["Tasks"])
async def get_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取单个任务详情"""
    task = await _get_user_task(db, user.id, task_id)
    return _task_to_response(task)


@app.delete("/api/tasks/{task_id}", response_model=MessageResponse, tags=["Tasks"])
async def delete_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除任务及其文件"""
    task = await _get_user_task(db, user.id, task_id)
    storage = get_storage()

    # 删除存储文件
    for key in [
        task.input_mp3_key,
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

    await db.delete(task)
    return MessageResponse(message="任务已删除")


# ======================================================================
# 文件下载
# ======================================================================

@app.get("/api/tasks/{task_id}/download/{file_type}", tags=["Files"])
async def download_file(
    task_id: str,
    file_type: str,
    user: User = Depends(get_current_user),
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

@app.websocket("/ws/tasks/{task_id}/progress")
async def task_progress_ws(websocket: WebSocket, task_id: str):
    """
    WebSocket 端点: 实时推送任务进度

    客户端连接后，服务端监听 Redis pub/sub 频道
    并将进度事件转发到 WebSocket。
    """
    await websocket.accept()

    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL)
        pubsub = r.pubsub()
        await pubsub.subscribe(f"task_progress:{task_id}")

        while True:
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
    except ImportError:
        # Redis 不可用时，降级为轮询模式
        await websocket.send_text(json.dumps({
            "task_id": task_id,
            "message": "实时进度不可用 (Redis 未连接)，请使用轮询 API",
        }))
    except Exception as e:
        log.error("WebSocket 错误: %s", e)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ======================================================================
# 集成时间轴编辑器 (通过 Router 挂载)
# ======================================================================

app.include_router(editor_router)


# ======================================================================
# 静态文件 (前端)
# ======================================================================

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(frontend_dir)),
        name="static",
    )

    @app.get("/", tags=["Frontend"])
    async def serve_dashboard():
        """返回仪表板主页"""
        dashboard = frontend_dir / "dashboard.html"
        if dashboard.exists():
            return FileResponse(dashboard)
        return FileResponse(frontend_dir / "index.html")

    @app.get("/editor", tags=["Frontend"])
    @app.get("/editor/{task_id}", tags=["Frontend"])
    async def serve_editor(task_id: str | None = None):
        """返回时间轴编辑器 (task_id 由前端路由处理)"""
        return FileResponse(frontend_dir / "index.html")


# ======================================================================
# 辅助函数
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


def _task_to_response(task: Task) -> TaskResponse:
    """ORM 对象转 Pydantic 响应"""
    return TaskResponse(
        id=task.id,
        title=task.title,
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
