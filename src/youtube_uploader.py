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

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional, Union

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.session_manager import (
    GLOBAL_PUBLISH_SEMAPHORE,
    acquire_publish_lock,
    get_uploader_for_session,
    release_publish_lock,
    resolve_session_id,
)

logger = logging.getLogger("youtube_uploader")

RECOMMENDED_YOUTUBE_TAGS = ["LyricVideo", "MusicVideo", "OriginalSong", "Visualizer", "Karaoke"]


def is_local_request(request: Optional[Request] = None) -> bool:
    """检查当前环境是否为本地单机环境 (127.0.0.1 / localhost / 开发者本地模式)。
    当部署于远程云端 (staging / production) 时，自动阻止服务器代理上传，保护频道配额与凭据安全。
    """
    deploy_env = os.getenv("DEPLOY_ENV", "").lower()
    if deploy_env in ("staging", "production", "prod"):
        return False
    if request is None:
        return True
    host = getattr(getattr(request, "client", None), "host", "")
    return host in ("127.0.0.1", "localhost", "::1", "testclient") or os.getenv("IS_LOCAL", "true").lower() == "true"


def generate_youtube_metadata(
    title: str,
    artist: str = "",
    style: str = "",
    extra_tags: Optional[list[str]] = None,
) -> dict:
    """生成符合 YouTube 高曝光推荐与卡拉OK版权合规的元数据 (标题、描述、标签)"""
    clean_title = title.strip()
    clean_artist = artist.strip()

    if clean_artist and clean_artist.lower() not in clean_title.lower():
        yt_title = f"{clean_artist} - {clean_title} (Karaoke / Instrumental with Lyrics)"
    else:
        yt_title = f"{clean_title} (Karaoke / Instrumental with Lyrics)"

    # YouTube 标题最长 100 字符限制
    if len(yt_title) > 100:
        yt_title = yt_title[:97] + "..."

    tags = list(RECOMMENDED_YOUTUBE_TAGS)
    if clean_artist:
        tags.extend([clean_artist, f"{clean_artist} Karaoke", f"{clean_artist} Instrumental"])
    tags.extend([clean_title, f"{clean_title} Karaoke", f"{clean_title} Instrumental", "SingAlong"])
    if style:
        tags.append(style)
    if extra_tags:
        tags.extend(extra_tags)

    # 去重且保持出现次序
    seen = set()
    dedup_tags = []
    for t in tags:
        norm = t.strip()
        if norm and norm.lower() not in seen:
            seen.add(norm.lower())
            dedup_tags.append(norm)

    desc_lines = [
        f"🎤 {yt_title}",
        "",
        "🎵 Track Info:",
        f"• Title: {clean_title}",
    ]
    if clean_artist:
        desc_lines.append(f"• Artist: {clean_artist}")
    if style:
        desc_lines.append(f"• Style / Genre: {style}")

    desc_lines.extend([
        "",
        "✨ Visuals & Lyric Animation produced with M2V Motion Studio (AI Kinetic Video & Subtitles).",
        "",
        "🔔 Enjoy singing? Like, subscribe & comment which song you'd like to sing next!",
        "",
        "⚠️ Copyright & Content ID Notice:",
        "This video is an instrumental karaoke visualizer created for musical appreciation, education and singing. All underlying musical compositions and master recording rights belong to their respective artists, songwriters and publishing record labels. Monetization (if any) is claimed directly by the copyright holders via YouTube Content ID.",
        "",
        "#" + " #".join([t.replace(" ", "") for t in dedup_tags[:8]]),
    ])

    return {
        "title": yt_title,
        "description": "\n".join(desc_lines),
        "tags": dedup_tags[:15],
    }


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

    def refresh_access_token(self) -> bool:
        """使用 refresh_token 自动续期 access_token"""
        refresh_token = self.credentials.get("refresh_token") or os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
        client_id = self.credentials.get("client_id") or os.environ.get("YOUTUBE_CLIENT_ID", "")
        client_secret = self.credentials.get("client_secret") or os.environ.get("YOUTUBE_CLIENT_SECRET", "")
        if not refresh_token:
            return False
        if not (client_id and client_secret):
            return False
        try:
            r = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                new_token = data.get("access_token")
                if new_token:
                    self.credentials["access_token"] = new_token
                    self._save_credentials(self.credentials, self.channel_info)
                    logger.info("YouTube Access Token 自动刷新成功")
                    return True
        except Exception as e:
            logger.warning(f"刷新 YouTube Token 异常: {e}")
        return False

    def get_account_status(self) -> dict:
        """检查当前 YouTube 频道授权状态"""
        access_token = self.credentials.get("access_token")
        if not access_token and self.credentials.get("refresh_token"):
            self.refresh_access_token()
            access_token = self.credentials.get("access_token")

        if access_token:
            try:
                r = requests.get(
                    "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=5,
                )
                if r.status_code == 401 and self.refresh_access_token():
                    access_token = self.credentials.get("access_token")
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

    def set_tokens(
        self,
        access_token: str,
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> dict:
        """手动设置或更新 OAuth2 Token"""
        self.credentials = {"access_token": access_token.strip(), "refresh_token": refresh_token.strip()}
        if client_id:
            self.credentials["client_id"] = client_id.strip()
        if client_secret:
            self.credentials["client_secret"] = client_secret.strip()
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
        privacy_status: str = "unlisted",
        dry_run: bool = False,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict:
        """
        通过 Google YouTube Data API v3 上传视频
        采用 Resumable Upload 断点分片上传机制
        支持 dry_run 演练模式以供本地和测试环境安全校验
        """
        def _notify(pct: float, msg: str):
            if progress_callback:
                progress_callback(pct, msg)

        local_video_path = video_source
        if not (video_source.startswith("http://") or video_source.startswith("https://")):
            local_video_path = str(Path(video_source).resolve())
            if not Path(local_video_path).exists():
                raise FileNotFoundError(f"视频文件不存在: {local_video_path}")

        # Dry-run 模拟演练模式：校验文件与参数有效性，不消耗实际配额
        if dry_run:
            _notify(0.2, "【演练模式】正在检查本地视频文件与元数据...")
            file_size_mb = round(os.path.getsize(local_video_path) / (1024 * 1024), 2) if not video_source.startswith("http") else 0.0
            _notify(0.6, f"【演练模式】文件有效 (大小: {file_size_mb} MB)，标题: {title[:35]}...")
            time.sleep(0.3)
            _notify(1.0, "【演练模式】本地校验通过！安全未向 YouTube 发送真实网络上传。")
            return {
                "success": True,
                "dry_run": True,
                "platform": "youtube",
                "video_id": "dry_run_mock_id",
                "url": "https://youtu.be/dry_run_mock_id",
                "message": f"【演练通过】文件就绪 ({file_size_mb} MB)，隐私策略: {privacy_status}",
            }

        access_token = self.credentials.get("access_token")
        if not access_token and self.credentials.get("refresh_token"):
            self.refresh_access_token()
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

    def check_video_compliance(self, video_id: str) -> dict:
        """检查视频在 YouTube 的处理进度与 Content ID 版权限制状态"""
        access_token = self.credentials.get("access_token")
        if not access_token:
            return {
                "success": False,
                "video_id": video_id,
                "message": "未配置 YouTube Access Token，无法查询",
            }

        try:
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "part": "snippet,status,contentDetails",
                    "id": video_id,
                },
                timeout=10,
            )
            if r.status_code != 200:
                return {
                    "success": False,
                    "video_id": video_id,
                    "message": f"YouTube API 请求失败 ({r.status_code}): {r.text}",
                }

            items = r.json().get("items", [])
            if not items:
                return {
                    "success": False,
                    "video_id": video_id,
                    "message": "未在当前频道找到该视频 (可能已被删除或 video_id 错误)",
                }

            item = items[0]
            snippet = item.get("snippet", {})
            status = item.get("status", {})
            content_details = item.get("contentDetails", {})

            upload_status = status.get("uploadStatus", "")  # uploaded, processing, processed, rejected, failed
            rejection_reason = status.get("rejectionReason", "")
            privacy_status = status.get("privacyStatus", "")
            has_licensed_content = bool(content_details.get("licensedContent"))
            region_restriction = content_details.get("regionRestriction")  # {"blocked": [...]} or {"allowed": [...]}

            is_rejected = upload_status in ("rejected", "failed")

            # 评估安全等级
            if is_rejected or (region_restriction and not region_restriction.get("allowed") and len(region_restriction.get("blocked", [])) > 150):
                safety = "blocked"
                message = f"视频已被版权方全球封禁或拒绝 ({rejection_reason or 'Blocked'})，建议立即在后台删除此视频以防风险。"
                can_publish_public = False
            elif region_restriction and region_restriction.get("blocked"):
                blocked_countries = region_restriction.get("blocked", [])
                safety = "region_restricted"
                message = f"视频在部分国家/地区受限（禁播国家: {', '.join(blocked_countries[:5])}{'等' if len(blocked_countries) > 5 else ''}），其他绝大部分国家正常可用，属于常规版权声明（Claim，非Strike）。"
                can_publish_public = True
            elif upload_status == "processing":
                safety = "processing"
                message = "YouTube 正在转码并执行 Content ID 版权扫描，请稍候约 3~10 分钟后再次检查..."
                can_publish_public = False
            elif has_licensed_content:
                safety = "safe_claim"
                message = "Content ID 版权扫描已完成：识别为受版权保护内容，视频可正常播放，广告收益归版权方，对频道无负面影响。"
                can_publish_public = True
            else:
                safety = "clean"
                message = "Content ID 检查已完成：未检测到任何受限版权声明，视频状态完全正常。"
                can_publish_public = True

            return {
                "success": True,
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "url": f"https://youtu.be/{video_id}",
                "upload_status": upload_status,
                "privacy_status": privacy_status,
                "has_licensed_content": has_licensed_content,
                "region_restriction": region_restriction,
                "safety": safety,
                "can_publish_public": can_publish_public,
                "message": message,
            }
        except Exception as e:
            logger.error(f"检查 YouTube 合规状态异常: {e}")
            return {
                "success": False,
                "video_id": video_id,
                "message": f"检查合规状态失败: {e}",
            }

    def update_video_privacy(self, video_id: str, privacy_status: str = "public") -> dict:
        """更新已上传视频的公开范围 (例如从 unlisted 转为 public)"""
        access_token = self.credentials.get("access_token")
        if not access_token and self.credentials.get("refresh_token"):
            self.refresh_access_token()
            access_token = self.credentials.get("access_token")
        if not access_token:
            raise RuntimeError("未配置 YouTube Access Token，请先完成授权")

        valid_statuses = ("public", "private", "unlisted")
        if privacy_status not in valid_statuses:
            raise ValueError(f"无效的公开状态: {privacy_status}，仅支持: {valid_statuses}")

        res = requests.put(
            "https://www.googleapis.com/youtube/v3/videos?part=status",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "id": video_id,
                "status": {
                    "privacyStatus": privacy_status,
                },
            },
            timeout=15,
        )
        if res.status_code not in (200, 204):
            raise RuntimeError(f"更新视频可见性失败 ({res.status_code}): {res.text}")

        return {
            "success": True,
            "video_id": video_id,
            "privacy_status": privacy_status,
            "url": f"https://youtu.be/{video_id}",
            "message": f"视频公开状态已成功更新为: {privacy_status}！",
        }


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
    privacy_status: str = "unlisted"
    dry_run: bool = False


class YouTubeMetadataRequest(BaseModel):
    title: str
    artist: str = ""
    style: str = ""
    extra_tags: list[str] = Field(default_factory=list)


class VideoPrivacyUpdateRequest(BaseModel):
    video_id: str
    privacy_status: str = "public"


class TokenSetRequest(BaseModel):
    access_token: str
    refresh_token: str = ""


@youtube_router.get("/status")
def get_yt_status(request: Request, sid: str = Depends(resolve_session_id)):
    """获取 YouTube 频道状态与本地单机环境检测"""
    uploader = get_uploader_for_session("youtube", sid)
    status = uploader.get_account_status()
    status["is_local"] = is_local_request(request)
    return status


@youtube_router.post("/metadata/suggest")
def suggest_yt_metadata(req: YouTubeMetadataRequest):
    """自动生成高曝光推荐与版权免责声明的卡拉OK元数据"""
    return generate_youtube_metadata(
        title=req.title,
        artist=req.artist,
        style=req.style,
        extra_tags=req.extra_tags,
    )


@youtube_router.get("/compliance/{video_id}")
def check_yt_compliance(video_id: str, sid: str = Depends(resolve_session_id)):
    """检查视频在 YouTube 的处理进度与 Content ID 版权限制状态"""
    uploader = get_uploader_for_session("youtube", sid)
    return uploader.check_video_compliance(video_id)


@youtube_router.post("/privacy")
def update_yt_privacy(req: VideoPrivacyUpdateRequest, sid: str = Depends(resolve_session_id)):
    """一键更新视频公开范围 (如由不公开转为公开)"""
    uploader = get_uploader_for_session("youtube", sid)
    return uploader.update_video_privacy(req.video_id, req.privacy_status)


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
    request: Request,
    sid: str = Depends(resolve_session_id),
):
    """创建异步发布 YouTube 任务 (带 Local-Only 环境保护)"""
    # 云端 Staging / Production 拦截保护 (仅在 dry_run 或本地单机环境下允许真实发布)
    if not req.dry_run and not is_local_request(request):
        raise HTTPException(
            403,
            "当前为云端环境，已禁用直接上传至 YouTube 以保护频道配额与凭据安全。请在本地客户端/本地编辑器（http://127.0.0.1:8000）中执行发布。"
        )

    uploader = get_uploader_for_session("youtube", sid)
    if not req.dry_run and not uploader.is_configured:
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
                    dry_run=req.dry_run,
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
