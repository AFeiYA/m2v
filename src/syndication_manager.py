"""
全网多平台协同发布管理中心 (Syndication Manager)
统一调度 哔哩哔哩、小红书、微信视频号、抖音、YouTube 的认证与一键并发全网多发分发任务。

核心特性：
1. 会话级多租户隔离与独立沙箱 (基于 src.session_manager)
2. 统一查询所有平台登录/鉴权状态 (按 session 动态分发)
3. 并发分发流水线 (ThreadPoolExecutor 并发发布，互不阻塞)
4. 聚合任务进度实时追踪与准确状态机 (精准区分 审核中、发布成功、错误重试)
5. 防重复提交并发锁与发布回执持久化
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from src.bilibili_uploader import bilibili_uploader
from src.douyin_uploader import douyin_uploader
from src.session_manager import (
    acquire_publish_lock,
    clear_session_data,
    get_publish_receipts,
    get_uploader_for_session,
    release_publish_lock,
    resolve_session_id,
    save_publish_receipt,
)
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
def get_all_platforms_status(session_id: str = Depends(resolve_session_id)):
    """获取指定会话下所有支持平台的连接与认证状态汇总"""
    results = {}
    configured_count = 0

    for pid, meta in PLATFORM_REGISTRY.items():
        try:
            uploader = get_uploader_for_session(pid, session_id)
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
        "session_id": session_id,
    }


@syndication_router.post("/publish")
def start_syndication_publish(
    req: SyndicationPublishRequest,
    background_tasks: BackgroundTasks,
    session_id: str = Depends(resolve_session_id),
):
    """一键向勾选的多个社交媒体平台并发分发发布视频 (带会话沙箱与防重复提交保护)"""
    selected = [p for p in req.platforms if p in PLATFORM_REGISTRY]
    if not selected:
        raise HTTPException(400, "请至少选择一个要发布的平台")

    # 并发防重复提交互斥锁检查
    locked_platforms = []
    for pid in selected:
        if not acquire_publish_lock(session_id, pid, req.video_source):
            locked_platforms.append(PLATFORM_REGISTRY[pid]["name"])

    if locked_platforms:
        # 释放已获取到的锁
        for pid in selected:
            if PLATFORM_REGISTRY[pid]["name"] not in locked_platforms:
                release_publish_lock(session_id, pid, req.video_source)
        raise HTTPException(409, f"以下平台正在发布该视频，请勿重复提交: {', '.join(locked_platforms)}")

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
            "session_id": session_id,
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
            _update_platform_state(pid, 0.05, f"准备提交至{PLATFORM_REGISTRY[pid]['name']}...", "uploading")

            def _cb(pct: float, msg: str):
                _update_platform_state(pid, pct, msg, "uploading" if pct < 0.95 else "submitting")

            try:
                uploader = get_uploader_for_session(pid, session_id)
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

                # 精准状态判定 (修复 success=false 仍判成功的 bug，区分审核中)
                res = res or {}
                is_failed = res.get("success") is False or res.get("status") == "error"
                is_review = (
                    res.get("status") in ["under_review", "reviewing", "pending_review"]
                    or res.get("is_review") is True
                    or ("审核" in str(res.get("message", "")))
                )

                with syndicate_lock:
                    ps = syndicate_tasks[task_id]["platform_states"][pid]
                    ps["progress"] = 1.0
                    ps["result"] = res
                    if is_failed:
                        ps["status"] = "error"
                        ps["message"] = res.get("message", "发布失败")
                        ps["error"] = res.get("message", "平台返回失败")
                    elif is_review:
                        ps["status"] = "under_review"
                        ps["message"] = res.get("message", "提交成功，正在审核中")
                    else:
                        ps["status"] = "completed"
                        ps["message"] = res.get("message", "发布成功")

            except Exception as e:
                logger.error(f"平台 [{pid}] 发布失败: {e}")
                with syndicate_lock:
                    ps = syndicate_tasks[task_id]["platform_states"][pid]
                    ps["status"] = "error"
                    ps["progress"] = 1.0
                    ps["message"] = f"发布失败: {str(e)}"
                    ps["error"] = str(e)
            finally:
                release_publish_lock(session_id, pid, req.video_source)

        # 启动线程池并发发布
        with ThreadPoolExecutor(max_workers=min(len(selected), 4)) as executor:
            list(executor.map(_publish_single_platform, selected))

        # 最终汇总与持久化回执
        with syndicate_lock:
            all_states = list(syndicate_tasks[task_id]["platform_states"].values())
            all_done = all(s["status"] in ["completed", "under_review", "error"] for s in all_states)
            has_success = any(s["status"] in ["completed", "under_review"] for s in all_states)
            has_error = any(s["status"] == "error" for s in all_states)
            if all_done:
                syndicate_tasks[task_id]["overall_progress"] = 1.0
                if has_success and not has_error:
                    syndicate_tasks[task_id]["status"] = "completed"
                elif has_success and has_error:
                    syndicate_tasks[task_id]["status"] = "partial_success"
                else:
                    syndicate_tasks[task_id]["status"] = "error"

                # 保存发布回执至对应沙箱
                save_publish_receipt(session_id, syndicate_tasks[task_id])

    background_tasks.add_task(_syndicate_worker)
    return {"task_id": task_id, "status": "running", "platforms": selected, "session_id": session_id}


@syndication_router.get("/tasks/{task_id}")
def get_syndication_task_progress(task_id: str):
    """获取多平台一键发布的实时聚合进度"""
    with syndicate_lock:
        if task_id not in syndicate_tasks:
            raise HTTPException(404, "任务不存在")
        return syndicate_tasks[task_id]


@syndication_router.get("/receipts")
def get_session_publish_receipts(session_id: str = Depends(resolve_session_id)):
    """获取当前会话的历史发布回执"""
    return {
        "session_id": session_id,
        "receipts": get_publish_receipts(session_id),
    }


@syndication_router.post("/session/clear")
def clear_current_session(session_id: str = Depends(resolve_session_id)):
    """主动擦除当前会话的云端凭据与沙箱数据 (阅后即焚)"""
    return clear_session_data(session_id)
