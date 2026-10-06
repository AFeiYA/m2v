"""
抖音 (Douyin) 视频一键发布与扫码鉴权服务模块
基于 Playwright + macOS Chrome 本地浏览器，支持抖音创作者中心自动发布。

功能：
1. 扫码登录 (网页截取抖音登录二维码、自动轮询状态、持久化会话)
2. 浏览器辅助登录 (支持打开本地 Chrome 窗口进行扫码登录)
3. 账号状态检查 (获取抖音昵称、头像)
4. 视频全自动发布 (上传 MP4、填写标题、添加热门话题标签并一键发布)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional, Union

import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("douyin_uploader")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

RECOMMENDED_DOUYIN_TAGS = ["AI音乐", "Suno", "自制MV", "听歌推荐", "治愈系", "好歌分享"]


class DouyinUploader:
    """管理抖音创作者平台鉴权与视频自动发布"""

    def __init__(
        self,
        profile_dir: Optional[Union[str, Path]] = None,
        cookies_path: Optional[Union[str, Path]] = None,
    ):
        root = Path(__file__).resolve().parent.parent
        self.profile_dir = Path(profile_dir) if profile_dir else root / "work" / "douyin_profile"
        self.cookies_path = Path(cookies_path) if cookies_path else root / "work" / "douyin_cookies.json"

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.cookies_path.parent.mkdir(parents=True, exist_ok=True)

        self.cookies: dict[str, str] = {}
        self.user_info: dict = {}
        self._load_cookies()

        self._qr_lock = threading.Lock()
        self._qr_session: Optional[dict] = None

    def _load_cookies(self):
        """从本地文件加载 Cookies 与用户信息"""
        self.cookies = {}
        self.user_info = {}
        if self.cookies_path.exists():
            try:
                data = json.loads(self.cookies_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.cookies = data.get("cookies", {})
                    self.user_info = data.get("user", {})
            except Exception as e:
                logger.warning(f"读取抖音 cookies 失败: {e}")

    def _save_cookies(self, cookies: dict, user_info: Optional[dict] = None):
        """持久化 Cookies 到本地文件"""
        self.cookies = cookies
        if user_info:
            self.user_info = user_info
        data = {
            "cookies": self.cookies,
            "user": self.user_info,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.cookies_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def is_configured(self) -> bool:
        """检查是否有基本登录凭证"""
        return bool(self.user_info.get("is_logged_in") or (self.profile_dir / "Default").exists())

    def get_account_status(self) -> dict:
        """检查当前抖音登录状态"""
        if self.user_info and self.user_info.get("is_logged_in"):
            return self.user_info

        if (self.profile_dir / "Default").exists():
            return {
                "is_logged_in": True,
                "is_login": True,
                "uname": self.user_info.get("uname", "抖音创作者"),
                "avatar": self.user_info.get("avatar", ""),
                "message": "已连接抖音创作者中心",
            }

        return {
            "is_logged_in": False,
            "is_login": False,
            "uname": "",
            "avatar": "",
            "message": "未登录抖音账号，请先扫码登录",
        }

    def logout(self) -> dict:
        """退出登录并清理凭证"""
        self.cookies = {}
        self.user_info = {}
        if self.cookies_path.exists():
            try:
                self.cookies_path.unlink()
            except Exception:
                pass
        try:
            if self.profile_dir.exists():
                shutil.rmtree(self.profile_dir, ignore_errors=True)
                self.profile_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"清理抖音 profile 失败: {e}")

        with self._qr_lock:
            if self._qr_session:
                try:
                    self._qr_session["context"].close()
                    self._qr_session["playwright"].stop()
                except Exception:
                    pass
                self._qr_session = None

        return {"success": True, "message": "已成功退出抖音登录"}

    def _clean_locks(self):
        """清理 Chromium 异常退出残留的单例锁文件"""
        for name in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
            f = self.profile_dir / name
            if f.exists():
                try:
                    f.unlink()
                except Exception:
                    pass

    def _run_threaded(self, fn, *args, **kwargs):
        """在独立后台线程中执行 Playwright 操作，彻底避免与 FastAPI asyncio 循环冲突"""
        container = {}
        err = []
        def _worker():
            try:
                container["val"] = fn(*args, **kwargs)
            except Exception as e:
                err.append(e)
        t = threading.Thread(target=_worker)
        t.start()
        t.join()
        if err:
            raise err[0]
        return container.get("val")

    def generate_qrcode(self) -> dict:
        """获取抖音创作者中心扫码登录二维码"""
        return self._run_threaded(self._generate_qrcode_impl)

    def _generate_qrcode_impl(self) -> dict:
        from playwright.sync_api import sync_playwright

        with self._qr_lock:
            if self._qr_session:
                try:
                    self._qr_session["context"].close()
                    self._qr_session["playwright"].stop()
                except Exception:
                    pass
                self._qr_session = None

            self._clean_locks()
            try:
                pw = sync_playwright().start()
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir.resolve()),
                    channel="chrome",
                    headless=True,
                    viewport={"width": 1280, "height": 800},
                    user_agent=DEFAULT_USER_AGENT,
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto("https://creator.douyin.com/", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)

                current_url = page.url
                cookies_list = ctx.cookies()
                cookies_dict = {c["name"]: c["value"] for c in cookies_list}
                if ("/login" not in current_url and "creator.douyin.com" in current_url) or "sessionid" in cookies_dict:
                    self._save_cookies(cookies_dict, {"is_logged_in": True, "uname": "抖音创作者"})
                    try:
                        ctx.close()
                        pw.stop()
                    except Exception:
                        pass
                    return {
                        "success": True,
                        "is_logged_in": True,
                        "uname": "抖音创作者",
                        "message": "🎉 抖音创作者平台已登录！",
                    }

                # 查找扫码区域
                qr_wrap = page.locator('.login-panel-qrcode, [class*="qrcode-box"], [class*="qrcode"]').first
                if qr_wrap.count() == 0:
                    qr_wrap = page.locator('canvas, img[src*="qrcode"]').first

                if qr_wrap.count() == 0:
                    # 备选：截取右侧登录卡片
                    qr_wrap = page.locator('[class*="login"]').first

                if qr_wrap.count() == 0:
                    ctx.close()
                    pw.stop()
                    return {"success": False, "message": "未能加载抖音登录二维码"}

                qr_bytes = qr_wrap.screenshot()
                qr_data_url = "data:image/png;base64," + base64.b64encode(qr_bytes).decode("utf-8")

                session_id = uuid.uuid4().hex[:12]
                self._qr_session = {
                    "id": session_id,
                    "playwright": pw,
                    "context": ctx,
                    "page": page,
                    "created_at": time.time(),
                }

                return {
                    "success": True,
                    "session_id": session_id,
                    "qrcode_image": qr_data_url,
                    "message": "请使用抖音 App 扫描屏幕二维码并确认登录",
                }
            except Exception as e:
                logger.error(f"获取抖音二维码异常: {e}")
                return {"success": False, "message": f"获取二维码失败: {str(e)}"}

    def poll_qrcode(self, session_id: str) -> dict:
        """轮询抖音扫码状态"""
        return self._run_threaded(self._poll_qrcode_impl, session_id)

    def _poll_qrcode_impl(self, session_id: str) -> dict:
        with self._qr_lock:
            if not self._qr_session or self._qr_session.get("id") != session_id:
                return {"status": "expired", "message": "扫码会话已过期，请重新获取二维码"}

            ctx = self._qr_session["context"]
            page = self._qr_session["page"]
            pw = self._qr_session["playwright"]

            try:
                current_url = page.url
                # 检查是否成功登录并进入创作者后台
                is_logged_in = "creator-micro" in current_url or page.locator('.header-avatar, .creator-avatar').count() > 0

                cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                if "sessionid" in cookies:
                    is_logged_in = True

                if is_logged_in:
                    page.wait_for_timeout(2000)
                    uname = "抖音创作者"
                    try:
                        name_el = page.locator('.name-text, [class*="nickname"], [class*="user-name"]').first
                        if name_el.count() > 0:
                            uname = name_el.inner_text().strip() or uname
                    except Exception:
                        pass

                    user_data = {
                        "is_logged_in": True,
                        "is_login": True,
                        "uname": uname,
                        "avatar": "",
                        "message": f"🎉 抖音账号 [{uname}] 登录成功！",
                    }
                    self._save_cookies(cookies, user_data)

                    try:
                        ctx.close()
                        pw.stop()
                    except Exception:
                        pass
                    self._qr_session = None

                    return {
                        "status": "success",
                        "is_logged_in": True,
                        "uname": uname,
                        "message": f"🎉 抖音账号 [{uname}] 登录成功！",
                    }

                # 检查二维码是否刷新或失效
                refresh_btn = page.locator('text="点击刷新", .refresh-btn').first
                if refresh_btn.count() > 0 and refresh_btn.is_visible():
                    return {"status": "expired", "message": "二维码已失效，请重新刷新"}

                return {"status": "waiting", "message": "等待抖音 App 扫描确认登录..."}
            except Exception as e:
                logger.warning(f"轮询抖音状态异常: {e}")
                return {"status": "waiting", "message": "正在确认登录状态..."}

    def launch_browser_login(self) -> dict:
        """打开 Chrome 窗口供创作者登录抖音"""
        from playwright.sync_api import sync_playwright

        def _run():
            self._clean_locks()
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir.resolve()),
                    channel="chrome",
                    headless=False,
                    viewport={"width": 1280, "height": 850},
                    user_agent=DEFAULT_USER_AGENT,
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto("https://creator.douyin.com/", wait_until="domcontentloaded")

                start_time = time.time()
                while time.time() - start_time < 180:
                    try:
                        if page.is_closed():
                            break
                        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                        if "sessionid" in cookies or "creator-micro" in page.url:
                            self._save_cookies(cookies, {"is_logged_in": True, "uname": "抖音创作者"})
                            logger.info("抖音前台窗口登录成功并已捕获凭据")
                            page.wait_for_timeout(3000)
                            break
                    except Exception:
                        pass
                    time.sleep(2)
                try:
                    ctx.close()
                except Exception:
                    pass

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return {"success": True, "message": "已打开 Chrome 浏览器窗口，请使用抖音扫码或验证码登录"}

    def publish_video(
        self,
        video_source: str,
        title: str,
        desc: str = "",
        tags: Optional[list[str]] = None,
        cover_source: str = "",
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict:
        """自动化发布视频到抖音"""
        from playwright.sync_api import sync_playwright

        def _notify(pct: float, msg: str):
            if progress_callback:
                progress_callback(pct, msg)

        temp_video_file = None
        temp_cover_file = None
        local_video_path = video_source

        if video_source.startswith("http://") or video_source.startswith("https://"):
            _notify(0.05, "正在从云端下载视频文件...")
            temp_dir = self.profile_dir.parent / "temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_video_file = temp_dir / f"dy_video_{int(time.time()*1000)}.mp4"

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

        # 提取封面
        if not cover_source:
            try:
                temp_dir = self.profile_dir.parent / "temp"
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_cover_file = temp_dir / f"dy_cover_{int(time.time()*1000)}.jpg"
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-ss", "00:00:01",
                        "-i", local_video_path,
                        "-vframes", "1", "-q:v", "2",
                        str(temp_cover_file)
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if temp_cover_file.exists():
                    cover_source = str(temp_cover_file.resolve())
            except Exception as e:
                logger.warning(f"提取抖音封面失败: {e}")

        clean_title = title.strip()
        tag_list = tags or RECOMMENDED_DOUYIN_TAGS
        tag_text = " ".join([f"#{t.strip('#')}" for t in tag_list if t.strip()])
        final_desc = f"{clean_title} {desc.strip()} {tag_text}".strip()

        _notify(0.15, "正在启动浏览器并连接抖音创作者中心...")

        try:
            self._clean_locks()
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir.resolve()),
                    channel="chrome",
                    headless=True,
                    viewport={"width": 1280, "height": 850},
                    user_agent=DEFAULT_USER_AGENT,
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()

                _notify(0.25, "正在打开抖音视频发布页面...")
                page.goto("https://creator.douyin.com/creator-micro/content/upload", wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(3000)

                # 检查是否未登录
                if "creator-micro" not in page.url:
                    raise RuntimeError("抖音未登录或登录态失效，请先扫码登录")

                _notify(0.35, "正在等待抖音上传控件就绪...")
                file_input = page.locator('input[type="file"]').first
                try:
                    file_input.wait_for(state="attached", timeout=30000)
                except Exception:
                    inputs = page.locator('input[type="file"]').all()
                    if not inputs:
                        raise RuntimeError("未找到抖音视频上传控件，页面加载超时或尚未完成登录")
                    file_input = inputs[0]

                _notify(0.40, "正在上传视频文件到抖音...")
                file_input.set_input_files(local_video_path)
                page.wait_for_timeout(3000)

                _notify(0.55, "正在等待视频上传处理完成...")
                upload_start = time.time()
                while time.time() - upload_start < 120:
                    # 检查是否有发布按钮
                    submit_btn = page.locator('button:has-text("发布"), .button-primary:has-text("发布")').first
                    if submit_btn.count() > 0 and not submit_btn.is_disabled():
                        break
                    page.wait_for_timeout(2000)

                _notify(0.75, "正在填写作品标题与话题标签...")
                title_input = page.locator('.zone-container, [contenteditable="true"], textarea, input[placeholder*="标题"]').first
                if title_input.count() > 0:
                    title_input.click()
                    if title_input.evaluate('e => e.tagName') in ['TEXTAREA', 'INPUT']:
                        title_input.fill(final_desc)
                    else:
                        page.keyboard.type(final_desc, delay=20)
                    page.wait_for_timeout(1000)

                _notify(0.92, "正在点击发布作品...")
                publish_btn = page.locator('button:has-text("发布"), .button-primary:has-text("发布")').first
                if publish_btn.count() == 0:
                    raise RuntimeError("未找到抖音【发布】按钮")

                publish_btn.click()
                page.wait_for_timeout(4000)

                _notify(1.0, f"🎉 抖音作品发布成功！标题: {clean_title}")
                return {
                    "success": True,
                    "platform": "douyin",
                    "title": clean_title,
                    "message": "作品已成功提交至抖音！",
                }
        finally:
            if temp_video_file and temp_video_file.exists():
                try:
                    temp_video_file.unlink()
                except Exception:
                    pass
            if temp_cover_file and temp_cover_file.exists():
                try:
                    temp_cover_file.unlink()
                except Exception:
                    pass


# 单例实例
douyin_uploader = DouyinUploader()


# ── FastAPI 路由与后台任务管理器 ────────────────────────
douyin_router = APIRouter(prefix="/api/douyin", tags=["Douyin"])

dy_publish_tasks: dict[str, dict] = {}
dy_tasks_lock = threading.Lock()


class DouyinPublishRequest(BaseModel):
    video_source: str
    title: str
    desc: str = ""
    tags: list[str] = Field(default_factory=lambda: RECOMMENDED_DOUYIN_TAGS)
    cover_source: str = ""


@douyin_router.get("/status")
def get_dy_status():
    """获取抖音登录状态"""
    return douyin_uploader.get_account_status()


@douyin_router.get("/qrcode")
def get_dy_qrcode():
    """生成抖音扫码二维码"""
    return douyin_uploader.generate_qrcode()


@douyin_router.get("/qrcode/poll")
def poll_dy_qrcode(session_id: str):
    """轮询抖音扫码状态"""
    return douyin_uploader.poll_qrcode(session_id)


@douyin_router.post("/browser-login")
def open_dy_browser_login():
    """打开本地 Chrome 浏览器窗口完成抖音登录"""
    return douyin_uploader.launch_browser_login()


@douyin_router.post("/logout")
def logout_dy():
    """退出抖音登录"""
    return douyin_uploader.logout()


@douyin_router.post("/publish")
def start_dy_publish_task(req: DouyinPublishRequest, background_tasks: BackgroundTasks):
    """创建异步发布抖音任务"""
    if not douyin_uploader.is_configured:
        raise HTTPException(400, "尚未登录抖音账号，请先扫码登录")

    task_id = uuid.uuid4().hex[:12]
    with dy_tasks_lock:
        dy_publish_tasks[task_id] = {
            "id": task_id,
            "status": "pending",
            "progress": 0.01,
            "message": "抖音发布任务排队中...",
            "created_at": time.time(),
            "result": None,
            "error": None,
        }

    def _worker():
        def _cb(pct: float, msg: str):
            with dy_tasks_lock:
                if task_id in dy_publish_tasks:
                    dy_publish_tasks[task_id]["progress"] = round(pct, 2)
                    dy_publish_tasks[task_id]["message"] = msg
                    dy_publish_tasks[task_id]["status"] = "uploading" if pct < 0.95 else "submitting"

        try:
            res = douyin_uploader.publish_video(
                video_source=req.video_source,
                title=req.title,
                desc=req.desc,
                tags=req.tags,
                cover_source=req.cover_source,
                progress_callback=_cb,
            )
            with dy_tasks_lock:
                dy_publish_tasks[task_id]["status"] = "completed"
                dy_publish_tasks[task_id]["progress"] = 1.0
                dy_publish_tasks[task_id]["message"] = res.get("message", "发布成功")
                dy_publish_tasks[task_id]["result"] = res
        except Exception as e:
            logger.error(f"抖音任务 {task_id} 异常: {e}")
            with dy_tasks_lock:
                dy_publish_tasks[task_id]["status"] = "error"
                dy_publish_tasks[task_id]["message"] = f"发布失败: {str(e)}"
                dy_publish_tasks[task_id]["error"] = str(e)

    background_tasks.add_task(_worker)
    return {"task_id": task_id, "status": "pending"}


@douyin_router.get("/tasks/{task_id}")
def get_dy_publish_task(task_id: str):
    """获取抖音发布任务进度"""
    with dy_tasks_lock:
        if task_id not in dy_publish_tasks:
            raise HTTPException(404, "任务不存在")
        return dy_publish_tasks[task_id]
