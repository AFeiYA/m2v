"""
Pydantic 请求 / 响应模型 — API 数据契约
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ======================================================================
# Auth
# ======================================================================

class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    display_name: str | None = None
    avatar_url: str | None = None
    plan: str
    credits: int
    is_verified: bool
    created_at: datetime


class UserUpdateRequest(BaseModel):
    display_name: str | None = None


# ======================================================================
# Task
# ======================================================================

class TaskCreateRequest(BaseModel):
    """创建任务时的可选配置"""
    language: str = "auto"
    skip_separation: bool = False
    ass_only: bool = False
    beat_effects: bool = False
    song_title: str | None = None
    suno_url: str | None = None


class SunoTaskRequest(BaseModel):
    """通过 Suno 链接直接创建任务"""
    suno_url: str
    song_title: str | None = None
    language: str = "auto"
    skip_separation: bool = False
    ass_only: bool = True
    beat_effects: bool = False
    lyrics_text: str | None = None
    force_realign: bool = False


class TaskResponse(BaseModel):
    id: str
    title: str
    song_title: str | None = None
    suno_url: str | None = None
    status: str
    current_step: str
    progress: int
    input_mp3_key: str
    input_lyrics_key: str
    output_mp4_key: str | None = None
    output_ass_key: str | None = None
    alignment_json_key: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int


class TaskProgressEvent(BaseModel):
    """WebSocket 进度推送事件"""
    task_id: str
    status: str
    current_step: str
    progress: int
    message: str = ""


# ======================================================================
# Upload
# ======================================================================

class UploadResponse(BaseModel):
    mp3_key: str
    lyrics_key: str
    task_id: str
    video_job_id: str | None = None
    message: str = "文件上传成功，任务已创建"


# ======================================================================
# General
# ======================================================================

class ErrorResponse(BaseModel):
    detail: str


class MessageResponse(BaseModel):
    message: str
