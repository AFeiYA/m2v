"""
全网多平台协同发布管理中心 (Syndication Manager)
统一调度 哔哩哔哩、小红书、微信视频号、抖音、YouTube 的认证与一键并发全网多发分发任务。

核心特性：
1. 统一查询所有平台登录/鉴权状态
2. 并发分发流水线 (ThreadPoolExecutor 并发发布，互不阻塞)
3. 聚合任务进度实时追踪 (每个平台拥有独立进度与状态，实时汇总总进度)
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from src.bilibili_uploader import bilibili_uploader
from src.douyin_uploader import douyin_uploader
from src.wechat_uploader import wechat_uploader
from src.xiaohongshu_uploader import xiaohongshu_uploader
from src.youtube_uploader import youtube_uploader

logger = logging.getLogger("syndication_manager")

PLATFORM_REGISTRY = {
    "bilibili": {
        "id": "bilibili",
        "name": "哔哩哔哩",
        "icon": "📺",
        "color": "#00A1D6",
        "uploader": bilibili_uploader,
    },
    "xiaohongshu": {
        "id": "xiaohongshu",
        "name": "小红书",
        "icon": "📕",
        "color": "#FF2442",
        "uploader": xiaohongshu_uploader,
    },
    "wechat": {
        "id": "wechat",
        "name": "微信视频号",
        "icon": "🟢",
        "color": "#07C160",
        "uploader": wechat_uploader,
    },
    "douyin": {
        "id": "douyin",
        "name": "抖音",
        "icon": "🎵",
        "color": "#161823",
        "uploader": douyin_uploader,
    },
    "youtube": {
        "id": "youtube",
        "name": "YouTube",
        "icon": "▶️",
        "color": "#FF0000",
        "uploader": youtube_uploader,
    },
}

syndicate_tasks: dict[str, dict] = {}
syndicate_lock = threading.Lock()


class SyndicationPublishRequest(BaseModel):
    video_source: str
    title: str
    desc: str = ""
    tags: list[str] = Field(default_factory=lambda: ["AI音乐", "Suno", "自制MV", "宝藏音乐", "原创音乐"])
    cover_source: str = ""
    platforms: list[str] = Field(default_factory=lambda: ["bilibili"])
    bilibili_tid: int = 28
    youtube_privacy: str = "public"


syndication_router = APIRouter(prefix="/api/syndicate", tags=["Syndication"])


@syndication_router.get("/status")
def get_all_platforms_status():
    """获取所有支持平台的连接与认证状态汇总"""
    results = {}
    configured_count = 0

    for pid, meta in PLATFORM_REGISTRY.items():
        uploader = meta["uploader"]
        try:
            status = uploader.get_account_status()
            is_logged_in = bool(status.get("is_logged_in") or status.get("is_login"))
            if is_logged_in:
                configured_count += 1
            results[pid] = {
                "id": pid,
                "name": meta["name"],
                "icon": meta["icon"],
                "color": meta["color"],
                "is_logged_in": is_logged_in,
                "uname": status.get("uname", ""),
                "avatar": status.get("avatar") or status.get("face", ""),
                "message": status.get("message", ""),
            }
        except Exception as e:
            results[pid] = {
                "id": pid,
                "name": meta["name"],
                "icon": meta["icon"],
                "color": meta["color"],
                "is_logged_in": False,
                "uname": "",
                "avatar": "",
                "message": str(e),
            }

    return {
        "platforms": results,
        "configured_count": configured_count,
        "total_count": len(PLATFORM_REGISTRY),
    }


@syndication_router.post("/publish")
def start_syndication_publish(req: SyndicationPublishRequest, background_tasks: BackgroundTasks):
    """一键向勾选的多个社交媒体平台并发分发发布视频"""
    selected = [p for p in req.platforms if p in PLATFORM_REGISTRY]
    if not selected:
        raise HTTPException(400, "请至少选择一个要发布的平台")

    task_id = uuid.uuid4().hex[:12]
    now = time.time()

    platform_states = {}
    for pid in selected:
        platform_states[pid] = {
            "name": PLATFORM_REGISTRY[pid]["name"],
            "icon": PLATFORM_REGISTRY[pid]["icon"],
            "status": "pending",
            "progress": 0.01,
            "message": "排队等待发布...",
            "result": None,
            "error": None,
        }

    with syndicate_lock:
        syndicate_tasks[task_id] = {
            "id": task_id,
            "title": req.title,
            "video_source": req.video_source,
            "platforms": selected,
            "status": "running",
            "overall_progress": 0.01,
            "created_at": now,
            "platform_states": platform_states,
        }

    def _syndicate_worker():
        def _update_platform_state(pid: str, pct: float, msg: str, status: str = "uploading"):
            with syndicate_lock:
                if task_id in syndicate_tasks and pid in syndicate_tasks[task_id]["platform_states"]:
                    ps = syndicate_tasks[task_id]["platform_states"][pid]
                    ps["progress"] = round(pct, 2)
                    ps["message"] = msg
                    ps["status"] = status
                    # 计算加权综合进度
                    total_p = sum(s["progress"] for s in syndicate_tasks[task_id]["platform_states"].values())
                    syndicate_tasks[task_id]["overall_progress"] = round(total_p / len(selected), 2)

        def _publish_single_platform(pid: str):
            uploader = PLATFORM_REGISTRY[pid]["uploader"]
            _update_platform_state(pid, 0.05, f"准备提交至{PLATFORM_REGISTRY[pid]['name']}...", "uploading")

            def _cb(pct: float, msg: str):
                _update_platform_state(pid, pct, msg, "uploading" if pct < 0.95 else "submitting")

            try:
                if pid == "bilibili":
                    res = uploader.publish_video(
                        video_source=req.video_source,
                        title=req.title,
                        desc=req.desc,
                        tags=req.tags,
                        tid=req.bilibili_tid,
                        cover_source=req.cover_source,
                        progress_callback=_cb,
                    )
                elif pid == "xiaohongshu":
                    res = uploader.publish_video(
                        video_source=req.video_source,
                        title=req.title,
                        desc=req.desc,
                        tags=req.tags,
                        cover_source=req.cover_source,
                        progress_callback=_cb,
                    )
                elif pid == "wechat":
                    res = uploader.publish_video(
                        video_source=req.video_source,
                        title=req.title,
                        desc=req.desc,
                        tags=req.tags,
                        cover_source=req.cover_source,
                        progress_callback=_cb,
                    )
                elif pid == "douyin":
                    res = uploader.publish_video(
                        video_source=req.video_source,
                        title=req.title,
                        desc=req.desc,
                        tags=req.tags,
                        cover_source=req.cover_source,
                        progress_callback=_cb,
                    )
                elif pid == "youtube":
                    res = uploader.publish_video(
                        video_source=req.video_source,
                        title=req.title,
                        desc=req.desc,
                        tags=req.tags,
                        cover_source=req.cover_source,
                        privacy_status=req.youtube_privacy,
                        progress_callback=_cb,
                    )
                else:
                    raise ValueError(f"未知平台: {pid}")

                with syndicate_lock:
                    ps = syndicate_tasks[task_id]["platform_states"][pid]
                    ps["status"] = "completed"
                    ps["progress"] = 1.0
                    ps["message"] = res.get("message", "发布成功")
                    ps["result"] = res

            except Exception as e:
                logger.error(f"平台 [{pid}] 发布失败: {e}")
                with syndicate_lock:
                    ps = syndicate_tasks[task_id]["platform_states"][pid]
                    ps["status"] = "error"
                    ps["progress"] = 1.0
                    ps["message"] = f"发布失败: {str(e)}"
                    ps["error"] = str(e)

        # 启动线程池并发发布
        with ThreadPoolExecutor(max_workers=min(len(selected), 4)) as executor:
            executor.map(_publish_single_platform, selected)

        # 最终汇总
        with syndicate_lock:
            all_states = syndicate_tasks[task_id]["platform_states"].values()
            all_done = all(s["status"] in ["completed", "error"] for s in all_states)
            any_success = any(s["status"] == "completed" for s in all_states)
            if all_done:
                syndicate_tasks[task_id]["overall_progress"] = 1.0
                syndicate_tasks[task_id]["status"] = "completed" if any_success else "error"

    background_tasks.add_task(_syndicate_worker)
    return {"task_id": task_id, "status": "running", "platforms": selected}


@syndication_router.get("/tasks/{task_id}")
def get_syndication_task_progress(task_id: str):
    """获取多平台一键发布的实时聚合进度"""
    with syndicate_lock:
        if task_id not in syndicate_tasks:
            raise HTTPException(404, "任务不存在")
        return syndicate_tasks[task_id]
