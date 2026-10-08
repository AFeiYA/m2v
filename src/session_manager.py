"""
会话沙箱与多租户凭据隔离管理器 (Session Sandbox Manager) - 安全加固版

核心特性:
1. 服务端加密签发与验签凭证 (issue_session_token / verify_session_token):
   - 采用 HMAC-SHA256 签名，杜绝客户端伪造与自报 ID 劫持
   - 凭证格式: m2v_s_{raw_id}.{hmac_signature}
2. 云端/公网模式禁用 default 共享回退 (is_default_session_allowed):
   - 检测公网 IP / Hugging Face Spaces / M2V_MULTIUSER_MODE
   - 公网环境下严格禁止匿名回退与声明 "default" 访问宿主凭证
3. 平台级并发发布互斥锁 (acquire_publish_lock):
   - 以 (session_id, platform) 为互斥粒度，防止同一浏览器 Profile 并发发布冲突
   - 全局信号量限制服务器最大并发无头浏览器数量
4. 完整生命周期管理与安全擦除 (clear_session_data):
   - 退出时显式关闭活跃网络会话与锁，无掩盖物理删除沙箱
   - 缓存命中自动更新 last_active，后台守护线程定时清理 (clean_expired_sessions)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import Header, HTTPException, Query, Request

logger = logging.getLogger("session_manager")

SESSION_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{8,64}$")


def validate_session_id(session_id: str) -> bool:
    """验证 session_id 格式 (防路径穿透)"""
    if not session_id or not isinstance(session_id, str):
        return False
    if session_id == "default":
        return True
    return bool(SESSION_ID_REGEX.match(session_id))


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WORK_DIR = _PROJECT_ROOT / "work"
_SESSIONS_ROOT = _WORK_DIR / "sessions"
_SECRET_FILE = _WORK_DIR / ".session_secret"


def _get_or_create_session_secret() -> bytes:
    """获取或持久化服务端 Session 签名密钥 (HMAC-SHA256)"""
    env_secret = os.getenv("M2V_SESSION_SECRET")
    if env_secret:
        return env_secret.encode("utf-8")

    _WORK_DIR.mkdir(parents=True, exist_ok=True)
    if _SECRET_FILE.exists():
        try:
            stored = _SECRET_FILE.read_bytes().strip()
            if len(stored) >= 16:
                return stored
        except Exception as e:
            logger.warning(f"读取 session secret 文件失败: {e}")

    secret = secrets.token_bytes(32)
    try:
        _SECRET_FILE.write_bytes(secret)
        try:
            _SECRET_FILE.chmod(0o600)
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"保存 session secret 失败: {e}")
    return secret


_SESSION_SECRET = _get_or_create_session_secret()

# 线程锁与全局对象池: key 为 (session_id, platform) -> Uploader instance
_uploader_pool: dict[tuple[str, str], Any] = {}
_pool_lock = threading.Lock()

# 平台并发互斥锁: key 为 (session_id, platform) -> lock_info
_active_platform_locks: dict[tuple[str, str], dict[str, Any]] = {}
_platform_lock_mutex = threading.Lock()

# 全局最大并发 Playwright 浏览器发布限制 (防止打爆服务器内存/CPU)
GLOBAL_PUBLISH_SEMAPHORE = threading.Semaphore(3)

# 后台清理守护线程状态
_janitor_thread: Optional[threading.Thread] = None
_janitor_running = False


def issue_session_token() -> str:
    """由服务端签发高强度防篡改会话凭据 (HMAC-SHA256)"""
    raw_id = f"m2v_s_{secrets.token_hex(16)}"
    sig = hmac.new(_SESSION_SECRET, raw_id.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    return f"{raw_id}.{sig}"


def verify_session_token(token: str) -> Optional[str]:
    """验证会话凭证的有效性，若合法返回解密校验后的 raw_id"""
    if not token or not isinstance(token, str):
        return None
    token = token.strip()
    if "." not in token:
        return None
    parts = token.split(".", 1)
    if len(parts) != 2:
        return None
    raw_id, sig = parts
    if not SESSION_ID_REGEX.match(raw_id):
        return None

    expected_sig = hmac.new(_SESSION_SECRET, raw_id.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    if hmac.compare_digest(sig, expected_sig):
        return raw_id
    return None


def is_default_session_allowed(request: Optional[Request] = None) -> bool:
    """
    判断当前请求是否允许使用单机全局 default 宿主会话。
    若开启了 M2V_MULTIUSER_MODE，或在公网/云端环境 (如 Hugging Face Spaces)，或来自非本地回环 IP，
    则严格禁止访问 default 会话。
    """
    if os.getenv("M2V_MULTIUSER_MODE", "").lower() in ("1", "true", "yes"):
        return False
    if "SPACE_ID" in os.environ or os.getenv("M2V_CLOUD_MODE", "").lower() in ("1", "true", "yes"):
        return False

    if request:
        client = getattr(request, "client", None)
        client_host = getattr(client, "host", None)
        # 允许本地开发测试回环 IP
        if client_host and client_host not in ("127.0.0.1", "localhost", "::1", "testclient"):
            return False

    return True


def touch_session(session_id: str):
    """更新会话的最后活跃时间 (包括缓存池命中时)"""
    if session_id == "default":
        return
    try:
        sdir = get_session_dir(session_id)
        meta_file = sdir / "metadata.json"
        now = time.time()
        meta = {}
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta["last_active"] = now
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug(f"更新会话活跃时间失败: {e}")


def resolve_session_id(
    request: Request = None,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    _sid: Optional[str] = Query(None, alias="_sid"),
    sid: Optional[str] = Query(None, alias="sid"),
    auth_sid: Optional[str] = Query(None, alias="m2v_sid"),
) -> str:
    """
    解析并验证当前 HTTP 请求的 Session ID。
    1. 提取 Header (X-Session-ID) 或 Query 参数 (_sid / sid) 或 Cookie (m2v_session_id)
    2. 校验签名防篡改 (拒绝未经服务器签发的自报 ID)
    3. 云端/公网模式禁止使用或显式传入 "default"
    """
    header_val = x_session_id if isinstance(x_session_id, str) else None
    query_val = _sid if isinstance(_sid, str) else (sid if isinstance(sid, str) else (auth_sid if isinstance(auth_sid, str) else None))

    token = header_val or query_val
    if not token and request and hasattr(request, "cookies"):
        token = request.cookies.get("m2v_session_id")

    if not token:
        # 未提供凭证
        if is_default_session_allowed(request):
            return "default"
        raise HTTPException(
            status_code=401,
            detail="缺少会话凭据。云端/公网模式已禁用共享 default 账号，请先调用 /api/session/init 初始化专属会话",
        )

    token = token.strip()

    # 显式传入 default 检查
    if token == "default":
        if is_default_session_allowed(request):
            return "default"
        raise HTTPException(
            status_code=403,
            detail="云端/公网模式已禁用 default 宿主会话，请使用服务端签发的会话凭据",
        )

    # 验证服务器签名
    verified_id = verify_session_token(token)
    if not verified_id:
        raise HTTPException(
            status_code=401,
            detail="无效或未通过防篡改签名的会话凭据 (Invalid session token signature)",
        )

    touch_session(verified_id)
    return verified_id


def get_session_dir(session_id: str) -> Path:
    """
    获取指定会话的独立沙箱目录。
    - "default" -> work/
    - 其他 -> work/sessions/{session_id}/
    严格断言路径穿越。
    """
    if session_id == "default":
        _WORK_DIR.mkdir(parents=True, exist_ok=True)
        return _WORK_DIR

    _SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)
    target = (_SESSIONS_ROOT / session_id).resolve()

    if not target.is_relative_to(_SESSIONS_ROOT.resolve()):
        raise HTTPException(status_code=403, detail="非法目录访问: 路径越界")

    target.mkdir(parents=True, exist_ok=True)
    return target


def get_uploader_for_session(platform: str, session_id: str = "default") -> Any:
    """
    获取或创建指定 session_id 下该平台的 Uploader 实例。
    每个 session 独立隔离其 cookies_path 与 profile_dir。
    无论命中缓存还是新建，均刷新会话活跃时间。
    """
    touch_session(session_id)
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
                cookie_file = sdir / "bilibili_cookies.json"
                if is_default_session_allowed() and not cookie_file.exists() and (_WORK_DIR / "bilibili_cookies.json").exists():
                    try:
                        shutil.copy2(_WORK_DIR / "bilibili_cookies.json", cookie_file)
                    except Exception:
                        pass
                uploader = BilibiliUploader(cookies_path=cookie_file)

        elif platform == "xiaohongshu":
            from src.xiaohongshu_uploader import XiaohongshuUploader, xiaohongshu_uploader

            if session_id == "default":
                uploader = xiaohongshu_uploader
            else:
                cookie_file = sdir / "xhs_cookies.json"
                if is_default_session_allowed() and not cookie_file.exists() and (_WORK_DIR / "xhs_cookies.json").exists():
                    try:
                        shutil.copy2(_WORK_DIR / "xhs_cookies.json", cookie_file)
                    except Exception:
                        pass
                uploader = XiaohongshuUploader(
                    profile_dir=sdir / "xhs_profile",
                    cookies_path=cookie_file,
                )

        elif platform == "wechat":
            from src.wechat_uploader import WeChatChannelsUploader, wechat_uploader

            if session_id == "default":
                uploader = wechat_uploader
            else:
                cookie_file = sdir / "wechat_cookies.json"
                if is_default_session_allowed() and not cookie_file.exists() and (_WORK_DIR / "wechat_cookies.json").exists():
                    try:
                        shutil.copy2(_WORK_DIR / "wechat_cookies.json", cookie_file)
                    except Exception:
                        pass
                uploader = WeChatChannelsUploader(
                    profile_dir=sdir / "wechat_profile",
                    cookies_path=cookie_file,
                )

        elif platform == "douyin":
            from src.douyin_uploader import DouyinUploader, douyin_uploader

            if session_id == "default":
                uploader = douyin_uploader
            else:
                cookie_file = sdir / "douyin_cookies.json"
                if is_default_session_allowed() and not cookie_file.exists() and (_WORK_DIR / "douyin_cookies.json").exists():
                    try:
                        shutil.copy2(_WORK_DIR / "douyin_cookies.json", cookie_file)
                    except Exception:
                        pass
                uploader = DouyinUploader(
                    profile_dir=sdir / "douyin_profile",
                    cookies_path=cookie_file,
                )

        elif platform == "youtube":
            from src.youtube_uploader import YouTubeUploader, youtube_uploader

            if session_id == "default":
                uploader = youtube_uploader
            else:
                cred_file = sdir / "youtube_credentials.json"
                if is_default_session_allowed() and not cred_file.exists() and (_WORK_DIR / "youtube_credentials.json").exists():
                    try:
                        shutil.copy2(_WORK_DIR / "youtube_credentials.json", cred_file)
                    except Exception:
                        pass
                uploader = YouTubeUploader(
                    credentials_path=cred_file,
                )
        else:
            raise ValueError(f"未知的平台类型: {platform}")

        _uploader_pool[key] = uploader
        return uploader


def acquire_publish_lock(
    session_id: str,
    platform: str,
    task_id: str = "",
    video_source: str = "",
    ttl_seconds: float = 900.0,
) -> bool:
    """
    平台级发布互斥锁 (以 session_id, platform 为粒度)。
    保证同一浏览器 Profile 下的任务严格串行执行，避免 Playwright 缓存目录竞争冲突。
    """
    key = (session_id, platform)
    now = time.time()
    with _platform_lock_mutex:
        if key in _active_platform_locks:
            info = _active_platform_locks[key]
            if now - info.get("start_time", 0) < ttl_seconds:
                return False  # 该平台正在发布中，拒绝并发冲突
        _active_platform_locks[key] = {
            "start_time": now,
            "task_id": task_id,
            "video_source": video_source,
        }
        return True


def release_publish_lock(session_id: str, platform: str):
    """释放该会话在该平台的发布互斥锁"""
    key = (session_id, platform)
    with _platform_lock_mutex:
        _active_platform_locks.pop(key, None)


def clear_session_data(session_id: str) -> dict:
    """
    物理销毁指定 Session 的所有云端资产与登录态（阅后即焚）。
    释放锁、终止活跃会话、清理对象池并不掩盖错误地删除目录。
    """
    if session_id == "default":
        with _pool_lock:
            for k in list(_uploader_pool.keys()):
                if k[0] == "default":
                    _uploader_pool.pop(k, None)
        return {"success": True, "message": "已重置默认单例缓存"}

    # 1. 释放该会话持有的所有发布锁
    with _platform_lock_mutex:
        for k in list(_active_platform_locks.keys()):
            if k[0] == session_id:
                _active_platform_locks.pop(k, None)

    # 2. 安全清理对象池并关闭网络连接
    with _pool_lock:
        for k in list(_uploader_pool.keys()):
            if k[0] == session_id:
                uploader = _uploader_pool.pop(k, None)
                if uploader and hasattr(uploader, "session") and hasattr(uploader.session, "close"):
                    try:
                        uploader.session.close()
                    except Exception:
                        pass

    # 3. 物理删除磁盘目录 (真实删除并严格报错)
    sdir = _SESSIONS_ROOT / session_id
    if sdir.exists() and sdir.is_dir():
        try:
            shutil.rmtree(sdir)
            logger.info(f"成功清理用户会话沙箱目录: {sdir}")
        except Exception as e:
            logger.warning(f"删除会话沙箱目录失败: {e}")
            return {"success": False, "message": f"删除会话目录失败: {str(e)}"}

    return {"success": True, "message": f"会话 {session_id} 的凭据与沙箱数据已物理清除"}


def save_publish_receipt(session_id: str, receipt: dict):
    """持久化发布回执至该会话沙箱"""
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

    # 浅拷贝并脱敏，绝不保存敏感字段
    clean_receipt = dict(receipt)
    clean_receipt.pop("session_id", None)
    clean_receipt["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")

    receipts.insert(0, clean_receipt)
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


def clean_expired_sessions(
    max_age_hours: float = 168,
    max_age_seconds: Optional[float] = None,
) -> int:
    """扫描并清理闲置超过指定时长的会话沙箱 (默认 7 天)"""
    if not _SESSIONS_ROOT.exists():
        return 0

    now = time.time()
    cutoff_seconds = max_age_seconds if max_age_seconds is not None else (max_age_hours * 3600)
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

            if now - last_active > cutoff_seconds:
                res = clear_session_data(sdir.name)
                if res.get("success"):
                    cleaned_count += 1
        except Exception as e:
            logger.debug(f"清理过期会话 {sdir.name} 异常: {e}")

    return cleaned_count


def start_session_janitor(interval_seconds: int = 3600, max_age_hours: int = 168):
    """启动后台定时清理守护线程"""
    global _janitor_thread, _janitor_running
    if _janitor_running:
        return
    _janitor_running = True

    def _worker():
        while _janitor_running:
            try:
                time.sleep(interval_seconds)
                cleaned = clean_expired_sessions(max_age_hours=max_age_hours)
                if cleaned > 0:
                    logger.info(f"会话清理守护进程已回收 {cleaned} 个过期会话沙箱")
            except Exception as e:
                logger.error(f"会话清理守护进程异常: {e}")

    _janitor_thread = threading.Thread(target=_worker, daemon=True, name="SessionJanitor")
    _janitor_thread.start()


# 模块加载时自动启动后台清理守护线程 (默认每小时扫描一次，清理超过 7 天的闲置沙箱)
start_session_janitor(interval_seconds=3600, max_age_hours=168)
