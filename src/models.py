"""
ORM 模型 — 用户 / 任务 / 歌曲

所有表通过 SQLAlchemy 2.0 声明式映射定义。
"""
    


    
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


# ── 枚举 ─────────────────────────────────────────────────

class UserPlan(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStep(str, enum.Enum):
    QUEUED = "queued"
    PREPROCESSING = "preprocessing"
    SEPARATING = "separating"
    ALIGNING = "aligning"
    SUBTITLE = "subtitle"
    COMPOSITING = "compositing"
    DONE = "done"
    ERROR = "error"


# ── 工具函数 ─────────────────────────────────────────────

def _uuid() -> str:
    return str(uuid.uuid4())

def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── User 表 ──────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=_uuid
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    username: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="FIREBASE_AUTH")
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    plan: Mapped[UserPlan] = mapped_column(
        SAEnum(UserPlan), default=UserPlan.FREE, nullable=False
    )
    credits: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 关联
    tasks: Mapped[list["Task"]] = relationship(back_populates="user", lazy="selectin")


# ── Task 表 ──────────────────────────────────────────────

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=False, index=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(
        String(255), nullable=False, default=""
    )
    song_title: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    suno_url: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, index=True
    )

    # 状态
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False
    )
    current_step: Mapped[TaskStep] = mapped_column(
        SAEnum(TaskStep), default=TaskStep.QUEUED, nullable=False
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    cost_credits: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # 输入文件 (存储 key 或本地路径)
    input_mp3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    input_lyrics_key: Mapped[str] = mapped_column(String(512), nullable=False)

    # 输出文件
    output_mp4_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    output_ass_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    alignment_json_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 配置快照 (JSON)
    config_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 错误信息
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    # 关联
    user: Mapped["User"] = relationship(back_populates="tasks")

    # Celery task id (用于查询/取消)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class VideoExport(Base):
    """Durable, user-owned export library; videos live in object storage."""
    __tablename__ = "video_exports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    kind: Mapped[str] = mapped_column(String(20), default="lyric")
    storage_key: Mapped[str] = mapped_column(String(1024))
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExportJob(Base):
    """Durable render request; a lease fences attempts after worker loss."""
    __tablename__ = "export_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="Waiting to render")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    alignment_key: Mapped[str] = mapped_column(String(1024))
    audio_key: Mapped[str] = mapped_column(String(1024))
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    run_token: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class CreditReservation(Base):
    __tablename__ = "credit_reservations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    operation_id: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(24))
    amount: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default="held", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class CreditEntry(Base):
    """Append-only balance events; task deletion does not erase accounting."""
    __tablename__ = "credit_entries"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    operation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    kind: Mapped[str] = mapped_column(String(24))
    event: Mapped[str] = mapped_column(String(24))
    amount: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class AlignmentExecution(Base):
    """Lease for imports created by lease-aware API/worker versions only."""
    __tablename__ = "alignment_executions"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token: Mapped[str] = mapped_column(String(32), nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class SongPreference(Base):
    """Personal library settings; grouping never rewrites existing tasks/assets."""
    __tablename__ = "song_preferences"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False, index=True)
    starred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    preferred_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class VersionTrash(Base):
    __tablename__ = "version_trash"
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    trashed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RenderAdmissionMutex(Base):
    """One database row serializes capacity checks with task admission commits."""
    __tablename__ = "render_admission_mutex"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)


class MotionRenderLease(Base):
    """Durable capacity reservation for a cloud Motion rendering process."""
    __tablename__ = "motion_render_leases"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class MotionExportRequest(Base):
    """Durable owner-scoped request identity and frozen Motion export price."""
    __tablename__ = "motion_export_requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    cost: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default="active", index=True)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
