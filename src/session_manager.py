"""
会话沙箱与多租户凭据隔离管理器 (Session Sandbox Manager)

核心特性:
1. 会话标识解析 (resolve_session_id):
   - 支持从 Header (X-Session-ID)、Query 参数或 Cookie 中提取会话 ID
   - 严格正则表达式校验 (防路径穿透与非法字符)
   - 缺省时回退到 "default" (完全向下兼容本地单人模式)
2. 磁盘存储沙箱隔离 (get_session_dir):
   - "default" -> work/
   - 独立用户 -> work/sessions/{session_id}/
   - 严格相对路径断言，防止目录遍历攻击
3. 实例对象池与隔离分发 (get_uploader_for_session):
   - 为每个 session_id 派发独立的 Uploader 实例与独立的 profile_dir / cookies_path
   - 线程安全的实例缓存池
4. 阅后即焚与凭据主动擦除 (clear_session_data):
   - 支持用户主动销毁云端沙箱与登录态
   - 包含基于 TTL 的过期沙箱清理能力
5. 发布回执持久化与防重锁 (Receipts & Idempotency):
   - 记录发布回执至 publish_receipts.json
   - 防止同一会话对同一视频在同一平台并发重复提交
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import Header, HTTPException, Query, Request

logger = logging.getLogger("session_manager")

# 会话 ID 格式：8 到 64 位由字母、数字、下划线、减号组成
SESSION_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{8,64}$")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WORK_DIR = _PROJECT_ROOT / "work"
_SESSIONS_ROOT = _WORK_DIR / "sessions"

# 线程锁与全局对象池: key 为 (session_id, platform) -> Uploader instance
_uploader_pool: dict[tuple[str, str], Any] = {}
_pool_lock = threading.Lock()

# 发布并发互斥锁: key 为 (session_id, platform, video_source) -> publish_start_time
_active_publishes: dict[tuple[str, str, str], float] = {}
_publish_lock = threading.Lock()


def validate_session_id(session_id: str) -> bool:
    """校验 session_id 字符串格式是否合法"""
    if not session_id or not isinstance(session_id, str):
        return False
    if session_id == "default":
        return True
    return bool(SESSION_ID_REGEX.match(session_id))


def resolve_session_id(
    request: Request = None,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None),
) -> str:
    """
    解析当前 HTTP 请求的 Session ID。
    优先级:
    1. Header: X-Session-ID
    2. Query Param: session_id
    3. Cookie: m2v_session_id
    4. 缺省值: "default"
    """
    header_val = x_session_id if isinstance(x_session_id, str) else None
    query_val = session_id if isinstance(session_id, str) else None

    sid = header_val or query_val
    if not sid and request and hasattr(request, "cookies"):
        sid = request.cookies.get("m2v_session_id")

    if not sid:
        return "default"

    sid = sid.strip()
    if not validate_session_id(sid):
        raise HTTPException(
            status_code=400,
            detail=f"非法的会话标识符 (Session ID: '{sid[:16]}...'). 必须为 8-64 位字母、数字、减号或下划线",
        )
    return sid


def get_session_dir(session_id: str) -> Path:
    """
    获取指定会话的独立沙箱目录。
    - "default" -> work/
    - 其他 -> work/sessions/{session_id}/
    具备严格的路径穿越断言。
    """
    if session_id == "default":
        _WORK_DIR.mkdir(parents=True, exist_ok=True)
        return _WORK_DIR

    _SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)
    target = (_SESSIONS_ROOT / session_id).resolve()

    # 严格校验：确保解析后的物理绝对路径必定在 _SESSIONS_ROOT 内部
    if not target.is_relative_to(_SESSIONS_ROOT.resolve()):
        raise HTTPException(status_code=403, detail="非法目录访问: 路径越界")

    target.mkdir(parents=True, exist_ok=True)

    # 更新元数据文件 (记录活跃时间用于 TTL 清理)
    meta_file = target / "metadata.json"
    try:
        now = time.time()
        meta = {}
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta.setdefault("created_at", now)
        meta["last_active"] = now
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug(f"更新 session 元数据失败: {e}")

    return target


def get_uploader_for_session(platform: str, session_id: str = "default") -> Any:
    """
    获取或创建指定 session_id 下该平台的 Uploader 实例。
    每个 session 独立隔离其 cookies_path 与 profile_dir。
    """
    key = (session_id, platform)
    with _pool_lock:
        if key in _uploader_pool:
            return _uploader_pool[key]

        sdir = get_session_dir(session_id)

        if platform == "bilibili":
            from src.bilibili_uploader import BilibiliUploader, bilibili_uploader

            if session_id == "default":
                uploader = bilibili_uploader
            else:
                uploader = BilibiliUploader(cookies_path=sdir / "bilibili_cookies.json")

        elif platform == "xiaohongshu":
            from src.xiaohongshu_uploader import XiaohongshuUploader, xiaohongshu_uploader

            if session_id == "default":
                uploader = xiaohongshu_uploader
            else:
                uploader = XiaohongshuUploader(
                    profile_dir=sdir / "xhs_profile",
                    cookies_path=sdir / "xhs_cookies.json",
                )

        elif platform == "wechat":
            from src.wechat_uploader import WeChatChannelsUploader, wechat_uploader

            if session_id == "default":
                uploader = wechat_uploader
            else:
                uploader = WeChatChannelsUploader(
                    profile_dir=sdir / "wechat_profile",
                    cookies_path=sdir / "wechat_cookies.json",
                )

        elif platform == "douyin":
            from src.douyin_uploader import DouyinUploader, douyin_uploader

            if session_id == "default":
                uploader = douyin_uploader
            else:
                uploader = DouyinUploader(
                    profile_dir=sdir / "douyin_profile",
                    cookies_path=sdir / "douyin_cookies.json",
                )

        elif platform == "youtube":
            from src.youtube_uploader import YouTubeUploader, youtube_uploader

            if session_id == "default":
                uploader = youtube_uploader
            else:
                uploader = YouTubeUploader(
                    credentials_path=sdir / "youtube_credentials.json",
                )
        else:
            raise ValueError(f"未知的平台类型: {platform}")

        _uploader_pool[key] = uploader
        return uploader


def clear_session_data(session_id: str) -> dict:
    """
    物理销毁指定 Session 的所有云端资产与登录态（阅后即焚）。
    """
    if session_id == "default":
        # 针对默认单人环境，不删除 work 根目录，仅清理缓存池
        with _pool_lock:
            for k in list(_uploader_pool.keys()):
                if k[0] == "default":
                    _uploader_pool.pop(k, None)
        return {"success": True, "message": "已重置默认单例缓存"}

    # 1. 清理内存缓存池中的对应对象
    with _pool_lock:
        for k in list(_uploader_pool.keys()):
            if k[0] == session_id:
                _uploader_pool.pop(k, None)

    # 2. 物理删除磁盘目录
    sdir = _SESSIONS_ROOT / session_id
    if sdir.exists() and sdir.is_dir():
        try:
            shutil.rmtree(sdir, ignore_errors=True)
            logger.info(f"成功清理用户会话沙箱目录: {sdir}")
        except Exception as e:
            logger.warning(f"删除会话沙箱目录失败: {e}")
            return {"success": False, "message": f"删除会话失败: {str(e)}"}

    return {"success": True, "message": f"会话 {session_id} 的凭据与沙箱数据已物理清除"}


def acquire_publish_lock(session_id: str, platform: str, video_source: str, ttl_seconds: float = 600.0) -> bool:
    """
    防重复提交互斥锁。
    如果该会话正在发布同一个视频到同一个平台，则拒绝重复请求。
    """
    key = (session_id, platform, video_source)
    now = time.time()
    with _publish_lock:
        if key in _active_publishes:
            start_time = _active_publishes[key]
            if now - start_time < ttl_seconds:
                return False  # 正在发布中
            # 已超时，自动释放旧锁
        _active_publishes[key] = now
        return True


def release_publish_lock(session_id: str, platform: str, video_source: str):
    """释放发布互斥锁"""
    key = (session_id, platform, video_source)
    with _publish_lock:
        _active_publishes.pop(key, None)


def save_publish_receipt(session_id: str, receipt: dict):
    """
    将发布回执持久化到对应沙箱的 publish_receipts.json 中
    """
    sdir = get_session_dir(session_id)
    receipt_file = sdir / "publish_receipts.json"
    receipts = []
    try:
        if receipt_file.exists():
            receipts = json.loads(receipt_file.read_text(encoding="utf-8"))
            if not isinstance(receipts, list):
                receipts = []
    except Exception:
        receipts = []

    # 追加回执并限制最多保存 100 条
    receipt["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
    receipts.insert(0, receipt)
    receipts = receipts[:100]

    try:
        receipt_file.write_text(json.dumps(receipts, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"保存发布回执失败: {e}")


def get_publish_receipts(session_id: str) -> list[dict]:
    """读取当前会话的所有历史发布回执"""
    sdir = get_session_dir(session_id)
    receipt_file = sdir / "publish_receipts.json"
    if not receipt_file.exists():
        return []
    try:
        return json.loads(receipt_file.read_text(encoding="utf-8"))
    except Exception:
        return []


def clean_expired_sessions(max_age_hours: int = 168) -> int:
    """
    扫描并清理闲置超过 max_age_hours (默认 7 天) 的会话沙箱
    返回清理的会话数量
    """
    if not _SESSIONS_ROOT.exists():
        return 0

    now = time.time()
    max_age_seconds = max_age_hours * 3600
    cleaned_count = 0

    for sdir in _SESSIONS_ROOT.iterdir():
        if not sdir.is_dir():
            continue
        try:
            meta_file = sdir / "metadata.json"
            last_active = None
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                last_active = meta.get("last_active")
            if last_active is None:
                last_active = sdir.stat().st_mtime

            if now - last_active > max_age_seconds:
                clear_session_data(sdir.name)
                cleaned_count += 1
        except Exception as e:
            logger.debug(f"清理过期会话 {sdir.name} 异常: {e}")

    return cleaned_count
