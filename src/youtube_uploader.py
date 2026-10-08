"""
YouTube 视频与 Shorts 一键发布服务模块
基于 Google YouTube Data API v3 官方规范实现，支持官方 OAuth2 授权与断点续传。

功能：
1. 账号鉴权状态检查 (获取 YouTube 频道名称、头像、订阅数)
2. OAuth2 网页授权流程 (一键生成授权链接或凭证持久化)
3. 视频断点续传发布 (Resumable Upload 分片上传，Music 音乐分类)
4. 自定义高清缩略图封面上传
"""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional, Union

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from src.session_manager import (
    GLOBAL_PUBLISH_SEMAPHORE,
    acquire_publish_lock,
    get_uploader_for_session,
    release_publish_lock,
    resolve_session_id,
)

logger = logging.getLogger("youtube_uploader")

RECOMMENDED_YOUTUBE_TAGS = ["SunoAI", "AIMusic", "MusicVideo", "OriginalSong", "Visualizer"]


class YouTubeUploader:
    """管理 YouTube Data API v3 认证与视频发布"""

    def __init__(self, credentials_path: Optional[Union[str, Path]] = None):
        root = Path(__file__).resolve().parent.parent
        self.credentials_path = (
            Path(credentials_path) if credentials_path else root / "work" / "youtube_credentials.json"
        )
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        self.credentials: dict = {}
        self.channel_info: dict = {}
        self._load_credentials()

    def _load_credentials(self):
        """加载已保存的 OAuth 凭据"""
        self.credentials = {}
        self.channel_info = {}
        if self.credentials_path.exists():
            try:
                data = json.loads(self.credentials_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.credentials = data.get("credentials", {})
                    self.channel_info = data.get("channel", {})
            except Exception as e:
                logger.warning(f"读取 YouTube 凭据失败: {e}")

    def _save_credentials(self, credentials: dict, channel: Optional[dict] = None):
        """保存凭据到本地文件"""
        self.credentials = credentials
        if channel:
            self.channel_info = channel
        data = {
            "credentials": self.credentials,
            "channel": self.channel_info,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.credentials_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def is_configured(self) -> bool:
        """检查是否有有效凭据"""
        return bool(self.credentials.get("access_token") or self.credentials.get("refresh_token"))

    def get_account_status(self) -> dict:
        """检查当前 YouTube 频道授权状态"""
        access_token = self.credentials.get("access_token")
        if access_token:
            try:
                r = requests.get(
                    "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=5,
                )
                if r.status_code == 200:
                    items = r.json().get("items", [])
                    if items:
                        snippet = items[0].get("snippet", {})
                        info = {
                            "is_logged_in": True,
                            "is_login": True,
                            "uname": snippet.get("title", "YouTube 频道"),
                            "avatar": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                            "channel_id": items[0].get("id", ""),
                            "message": f"已连接 YouTube 频道: {snippet.get('title')}",
                        }
                        self.channel_info = info
                        self._save_credentials(self.credentials, info)
                        return info
            except Exception as e:
                logger.debug(f"检查 YouTube 频道异常: {e}")

        if self.channel_info and self.channel_info.get("is_logged_in"):
            return self.channel_info

        return {
            "is_logged_in": False,
            "is_login": False,
            "uname": "",
            "avatar": "",
            "message": "未连接 YouTube 账号，可通过 OAuth2 授权连接",
        }

    def set_tokens(self, access_token: str, refresh_token: str = "") -> dict:
        """手动设置或更新 OAuth2 Token"""
        self.credentials = {"access_token": access_token.strip(), "refresh_token": refresh_token.strip()}
        self._save_credentials(self.credentials)
        return self.get_account_status()

    def logout(self) -> dict:
        """清除本地 YouTube 凭据"""
        self.credentials = {}
        self.channel_info = {}
        if self.credentials_path.exists():
            try:
                self.credentials_path.unlink()
            except Exception:
                pass
        return {"success": True, "message": "已清除 YouTube 连接凭据"}

    def publish_video(
        self,
        video_source: str,
        title: str,
        desc: str = "",
        tags: Optional[list[str]] = None,
        cover_source: str = "",
        privacy_status: str = "public",
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict:
        """
        通过 Google YouTube Data API v3 上传视频
        采用 Resumable Upload 断点分片上传机制
        """
        def _notify(pct: float, msg: str):
            if progress_callback:
                progress_callback(pct, msg)

        access_token = self.credentials.get("access_token")
        if not access_token:
            raise RuntimeError("未配置 YouTube Access Token，请先完成授权")

        temp_video_file = None
        temp_cover_file = None
        local_video_path = video_source

        if video_source.startswith("http://") or video_source.startswith("https://"):
            _notify(0.05, "正在下载视频准备上传到 YouTube...")
            temp_dir = self.credentials_path.parent / "temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_video_file = temp_dir / f"yt_video_{int(time.time()*1000)}.mp4"

            with requests.get(video_source, stream=True, timeout=180) as r:
                r.raise_for_status()
                with open(temp_video_file, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
            local_video_path = str(temp_video_file.resolve())
        else:
            local_video_path = str(Path(video_source).resolve())

        if not Path(local_video_path).exists():
            raise FileNotFoundError(f"视频文件不存在: {local_video_path}")

        file_size = os.path.getsize(local_video_path)

        # 准备元数据
        metadata = {
            "snippet": {
                "title": title.strip()[:100],
                "description": desc.strip(),
                "tags": tags or RECOMMENDED_YOUTUBE_TAGS,
                "categoryId": "10",  # Music 分类
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        _notify(0.15, "正在向 YouTube 请求创建分片上传会话...")
        init_res = requests.post(
            "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(file_size),
                "X-Upload-Content-Type": "video/mp4",
            },
            json=metadata,
            timeout=30,
        )

        if init_res.status_code not in [200, 201]:
            raise RuntimeError(f"初始化 YouTube 上传失败: {init_res.text}")

        upload_url = init_res.headers.get("Location")
        if not upload_url:
            raise RuntimeError("YouTube 未返回有效 Upload Location")

        # 流式上传分片
        _notify(0.25, "正在高速上传视频数据到 YouTube...")
        chunk_size = 5 * 1024 * 1024  # 5MB chunks
        uploaded_bytes = 0

        with open(local_video_path, "rb") as f:
            while uploaded_bytes < file_size:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                chunk_len = len(chunk)
                content_range = f"bytes {uploaded_bytes}-{uploaded_bytes + chunk_len - 1}/{file_size}"

                res = requests.put(
                    upload_url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "video/mp4",
                        "Content-Range": content_range,
                    },
                    data=chunk,
                    timeout=120,
                )

                uploaded_bytes += chunk_len
                pct = 0.25 + 0.65 * (uploaded_bytes / file_size)
                _notify(round(pct, 2), f"YouTube 视频上传进度: {int((uploaded_bytes/file_size)*100)}%")

                if res.status_code in [200, 201]:
                    video_data = res.json()
                    video_id = video_data.get("id", "")
                    _notify(0.95, f"视频上传完成！Video ID: {video_id}")

                    # 尝试设置自定义封面
                    if cover_source and Path(cover_source).exists() and video_id:
                        try:
                            _notify(0.98, "正在上传自定义缩略图...")
                            with open(cover_source, "rb") as cf:
                                requests.post(
                                    f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={video_id}",
                                    headers={
                                        "Authorization": f"Bearer {access_token}",
                                        "Content-Type": "image/jpeg",
                                    },
                                    data=cf.read(),
                                    timeout=30,
                                )
                        except Exception as e:
                            logger.warning(f"上传 YouTube 封面缩略图失败: {e}")

                    _notify(1.0, f"🎉 YouTube 视频发布成功！https://youtu.be/{video_id}")
                    return {
                        "success": True,
                        "platform": "youtube",
                        "video_id": video_id,
                        "url": f"https://youtu.be/{video_id}",
                        "message": f"发布成功！视频链接: https://youtu.be/{video_id}",
                    }

        raise RuntimeError("YouTube 上传会话意外终止")


# 单例实例
youtube_uploader = YouTubeUploader()

# ── FastAPI 路由 ────────────────────────
youtube_router = APIRouter(prefix="/api/youtube", tags=["YouTube"])

yt_publish_tasks: dict[str, dict] = {}
yt_tasks_lock = threading.Lock()


class YouTubePublishRequest(BaseModel):
    video_source: str
    title: str
    desc: str = ""
    tags: list[str] = Field(default_factory=lambda: RECOMMENDED_YOUTUBE_TAGS)
    cover_source: str = ""
    privacy_status: str = "public"


class TokenSetRequest(BaseModel):
    access_token: str
    refresh_token: str = ""


@youtube_router.get("/status")
def get_yt_status(sid: str = Depends(resolve_session_id)):
    """获取 YouTube 频道状态"""
    uploader = get_uploader_for_session("youtube", sid)
    return uploader.get_account_status()


@youtube_router.post("/token")
def set_yt_token(req: TokenSetRequest, sid: str = Depends(resolve_session_id)):
    """设置 YouTube Access Token"""
    uploader = get_uploader_for_session("youtube", sid)
    return uploader.set_tokens(req.access_token, req.refresh_token)


@youtube_router.post("/logout")
def logout_yt(sid: str = Depends(resolve_session_id)):
    """清除 YouTube 连接"""
    uploader = get_uploader_for_session("youtube", sid)
    return uploader.logout()


@youtube_router.post("/publish")
def start_yt_publish_task(
    req: YouTubePublishRequest,
    background_tasks: BackgroundTasks,
    sid: str = Depends(resolve_session_id),
):
    """创建异步发布 YouTube 任务"""
    uploader = get_uploader_for_session("youtube", sid)
    if not uploader.is_configured:
        raise HTTPException(400, "尚未连接 YouTube 账号，请先配置 Access Token")

    if not acquire_publish_lock(sid, "youtube", video_source=req.video_source):
        raise HTTPException(409, "YouTube 已有任务正在发布中，请勿重复提交")

    task_id = uuid.uuid4().hex[:12]
    with yt_tasks_lock:
        yt_publish_tasks[task_id] = {
            "id": task_id,
            "session_id": sid,
            "status": "pending",
            "progress": 0.01,
            "message": "YouTube 发布任务排队中...",
            "created_at": time.time(),
            "result": None,
            "error": None,
        }

    def _worker():
        def _cb(pct: float, msg: str):
            with yt_tasks_lock:
                if task_id in yt_publish_tasks:
                    yt_publish_tasks[task_id]["progress"] = round(pct, 2)
                    yt_publish_tasks[task_id]["message"] = msg
                    yt_publish_tasks[task_id]["status"] = "uploading" if pct < 0.95 else "submitting"

        try:
            with GLOBAL_PUBLISH_SEMAPHORE:
                res = uploader.publish_video(
                    video_source=req.video_source,
                    title=req.title,
                    desc=req.desc,
                    tags=req.tags,
                    cover_source=req.cover_source,
                    privacy_status=req.privacy_status,
                    progress_callback=_cb,
                )
            res = res or {}
            is_failed = res.get("success") is False or res.get("status") == "error"
            is_review = (
                res.get("status") in ["under_review", "reviewing", "pending_review"]
                or res.get("is_review") is True
                or ("审核" in str(res.get("message", "")))
            )

            with yt_tasks_lock:
                yt_publish_tasks[task_id]["progress"] = 1.0
                yt_publish_tasks[task_id]["result"] = res
                if is_failed:
                    yt_publish_tasks[task_id]["status"] = "error"
                    yt_publish_tasks[task_id]["message"] = res.get("message", "发布失败")
                    yt_publish_tasks[task_id]["error"] = res.get("message", "平台返回失败")
                elif is_review:
                    yt_publish_tasks[task_id]["status"] = "under_review"
                    yt_publish_tasks[task_id]["message"] = res.get("message", "提交成功，正在审核中")
                else:
                    yt_publish_tasks[task_id]["status"] = "completed"
                    yt_publish_tasks[task_id]["message"] = res.get("message", "发布成功")

        except Exception as e:
            logger.error(f"YouTube 任务 {task_id} 异常: {e}")
            with yt_tasks_lock:
                yt_publish_tasks[task_id]["status"] = "error"
                yt_publish_tasks[task_id]["message"] = f"发布失败: {str(e)}"
                yt_publish_tasks[task_id]["error"] = str(e)
        finally:
            release_publish_lock(sid, "youtube")

    background_tasks.add_task(_worker)
    return {"task_id": task_id, "status": "pending"}


@youtube_router.get("/tasks/{task_id}")
def get_yt_publish_task(task_id: str, sid: str = Depends(resolve_session_id)):
    """获取 YouTube 发布任务进度 (防越权访问)"""
    with yt_tasks_lock:
        if task_id not in yt_publish_tasks:
            raise HTTPException(404, "任务不存在")
        task = yt_publish_tasks[task_id]
        task_owner = task.get("session_id")
        if task_owner and task_owner != sid and sid != "default":
            raise HTTPException(404, "任务不存在或无权访问")
        safe_copy = dict(task)
        safe_copy.pop("session_id", None)
        return safe_copy
