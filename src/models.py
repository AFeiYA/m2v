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
        String(36), primary_key=True, default=_uuid
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    username: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
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
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(
        String(255), nullable=False, default=""
    )

    # 状态
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False
    )
    current_step: Mapped[TaskStep] = mapped_column(
        SAEnum(TaskStep), default=TaskStep.QUEUED, nullable=False
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100

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

    # 关联
    user: Mapped["User"] = relationship(back_populates="tasks")

    # Celery task id (用于查询/取消)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
