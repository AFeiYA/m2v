"""
微信视频号 (WeChat Channels) 视频一键发布与扫码鉴权服务模块
基于 Playwright + macOS Chrome 本地浏览器，支持视频号助手自动发布。

功能：
1. 扫码登录 (网页截取视频号二维码、自动轮询状态、持久化微信会话)
2. 浏览器辅助登录 (支持打开本地 Chrome 窗口进行微信扫码登录)
3. 账号状态检查 (获取视频号名称、头像)
4. 视频全自动发布 (上传 MP4、填写标题、添加动态话题、设置封面并发表)
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

logger = logging.getLogger("wechat_uploader")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

RECOMMENDED_WECHAT_TAGS = ["AI音乐", "Suno", "音乐分享", "每日一歌", "治愈系"]


class WeChatChannelsUploader:
    """管理微信视频号助手平台鉴权与视频自动发布"""

    def __init__(
        self,
        profile_dir: Optional[Union[str, Path]] = None,
        cookies_path: Optional[Union[str, Path]] = None,
    ):
        root = Path(__file__).resolve().parent.parent
        self.profile_dir = Path(profile_dir) if profile_dir else root / "work" / "wechat_profile"
        self.cookies_path = Path(cookies_path) if cookies_path else root / "work" / "wechat_cookies.json"

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
                logger.warning(f"读取微信视频号 cookies 失败: {e}")

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
        """检查当前视频号登录状态"""
        if self.user_info and self.user_info.get("is_logged_in"):
            return self.user_info

        # 检查持久化 profile 是否存在
        if (self.profile_dir / "Default").exists():
            return {
                "is_logged_in": True,
                "is_login": True,
                "uname": self.user_info.get("uname", "微信视频号创作者"),
                "avatar": self.user_info.get("avatar", ""),
                "message": "已连接微信视频号助手",
            }

        return {
            "is_logged_in": False,
            "is_login": False,
            "uname": "",
            "avatar": "",
            "message": "未登录微信视频号，请先扫码登录",
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
            logger.warning(f"清理视频号 profile 失败: {e}")

        with self._qr_lock:
            if self._qr_session:
                try:
                    self._qr_session["context"].close()
                    self._qr_session["playwright"].stop()
                except Exception:
                    pass
                self._qr_session = None

        return {"success": True, "message": "已成功退出微信视频号登录"}

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
        """获取微信视频号助手扫码登录二维码"""
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
                page.goto("https://channels.weixin.qq.com/login.html", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)

                # 截取二维码区域
                qr_wrap = page.locator('.login-qrcode-wrap, .qrcode-wrap, .qrcode-area').first
                if qr_wrap.count() == 0:
                    qr_wrap = page.locator('canvas, img[src*="qrcode"]').first

                if qr_wrap.count() == 0:
                    ctx.close()
                    pw.stop()
                    return {"success": False, "message": "未能加载视频号登录二维码"}

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
                    "message": "请使用微信扫描屏幕二维码并确认登录视频号助手",
                }
            except Exception as e:
                logger.error(f"获取微信视频号二维码异常: {e}")
                return {"success": False, "message": f"获取二维码失败: {str(e)}"}

    def poll_qrcode(self, session_id: str) -> dict:
        """轮询微信视频号扫码状态"""
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
                # 登录成功后会跳转离开 login.html
                if "login.html" not in current_url and "channels.weixin.qq.com" in current_url:
                    page.wait_for_timeout(2000)

                    # 尝试读取创作者昵称
                    uname = "微信视频号创作者"
                    try:
                        name_el = page.locator('.finder-nickname, .user-name, [class*="nickname"]').first
                        if name_el.count() > 0:
                            uname = name_el.inner_text().strip() or uname
                    except Exception:
                        pass

                    cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                    user_data = {
                        "is_logged_in": True,
                        "is_login": True,
                        "uname": uname,
                        "avatar": "",
                        "message": f"🎉 微信视频号 [{uname}] 登录成功！",
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
                        "message": f"🎉 微信视频号 [{uname}] 登录成功！",
                    }

                # 检查二维码是否刷新或失效
                refresh_btn = page.locator('text="点击刷新", .refresh-btn').first
                if refresh_btn.count() > 0 and refresh_btn.is_visible():
                    return {"status": "expired", "message": "二维码已失效，请重新刷新"}

                return {"status": "waiting", "message": "等待微信扫描确认登录..."}
            except Exception as e:
                logger.warning(f"轮询微信视频号状态异常: {e}")
                return {"status": "waiting", "message": "正在确认登录状态..."}

    def launch_browser_login(self) -> dict:
        """打开 Chrome 窗口供创作者扫码登录"""
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
                page.goto("https://channels.weixin.qq.com/login.html", wait_until="domcontentloaded")

                start_time = time.time()
                while time.time() - start_time < 180:
                    try:
                        if page.is_closed():
                            break
                        if "login.html" not in page.url and "channels.weixin.qq.com" in page.url:
                            cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                            self._save_cookies(cookies, {"is_logged_in": True, "uname": "微信视频号创作者"})
                            logger.info("微信视频号前台窗口登录成功并已捕获凭据")
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
        return {"success": True, "message": "已打开 Chrome 浏览器窗口，请使用微信扫码完成登录"}

    def publish_video(
        self,
        video_source: str,
        title: str,
        desc: str = "",
        tags: Optional[list[str]] = None,
        cover_source: str = "",
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict:
        """自动化发布视频到微信视频号"""
        from playwright.sync_api import sync_playwright

        def _notify(pct: float, msg: str):
            if progress_callback:
                progress_callback(pct, msg)

        temp_video_file = None
        temp_cover_file = None
        local_video_path = video_source

        # 处理远程 URL
        if video_source.startswith("http://") or video_source.startswith("https://"):
            _notify(0.05, "正在从云端下载视频文件...")
            temp_dir = self.profile_dir.parent / "temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_video_file = temp_dir / f"wx_video_{int(time.time()*1000)}.mp4"

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
                temp_cover_file = temp_dir / f"wx_cover_{int(time.time()*1000)}.jpg"
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
                logger.warning(f"提取视频号封面失败: {e}")

        clean_title = title.strip()
        tag_list = tags or RECOMMENDED_WECHAT_TAGS
        tag_text = " ".join([f"#{t.strip('#')}#" for t in tag_list if t.strip()])
        final_desc = f"{clean_title}\n\n{desc.strip()}\n\n{tag_text}".strip()

        _notify(0.15, "正在启动浏览器并连接微信视频号助手...")

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

                _notify(0.25, "正在打开视频号发表页面...")
                page.goto("https://channels.weixin.qq.com/platform/post/create", wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(3000)

                if "login.html" in page.url:
                    raise RuntimeError("微信视频号未登录或登录已失效，请先扫码登录")

                _notify(0.35, "正在上传视频文件...")
                file_input = page.locator('input[type="file"]').first
                if file_input.count() == 0:
                    raise RuntimeError("未找到视频上传控件")

                file_input.set_input_files(local_video_path)
                page.wait_for_timeout(3000)

                _notify(0.55, "正在等待视频上传处理完成...")
                upload_start = time.time()
                while time.time() - upload_start < 120:
                    # 检查是否有发表按钮并处于可用状态
                    submit_btn = page.locator('button:has-text("发表"), .weui-desktop-btn_primary:has-text("发表")').first
                    if submit_btn.count() > 0 and not submit_btn.is_disabled():
                        break
                    page.wait_for_timeout(2000)

                _notify(0.75, "正在填写动态文案与话题标签...")
                desc_input = page.locator('.post-desc-input, textarea, [contenteditable="true"]').first
                if desc_input.count() > 0:
                    desc_input.click()
                    if desc_input.evaluate('e => e.tagName') == 'TEXTAREA':
                        desc_input.fill(final_desc)
                    else:
                        page.keyboard.type(final_desc, delay=20)
                    page.wait_for_timeout(1000)

                # 设置封面
                if cover_source and Path(cover_source).exists():
                    try:
                        cover_btn = page.locator('text="选择封面", text="更换封面"').first
                        if cover_btn.count() > 0:
                            cover_btn.click()
                            page.wait_for_timeout(1000)
                            cover_file_input = page.locator('input[type="file"][accept*="image"]').first
                            if cover_file_input.count() > 0:
                                cover_file_input.set_input_files(cover_source)
                                page.wait_for_timeout(1500)
                                confirm_btn = page.locator('button:has-text("确定"), button:has-text("完成")').first
                                if confirm_btn.count() > 0:
                                    confirm_btn.click()
                                    page.wait_for_timeout(1000)
                    except Exception as e:
                        logger.warning(f"设置视频号封面帧失败: {e}")

                _notify(0.92, "正在提交发表到视频号...")
                publish_btn = page.locator('button:has-text("发表"), .weui-desktop-btn_primary:has-text("发表")').first
                if publish_btn.count() == 0:
                    raise RuntimeError("未找到视频号【发表】按钮")

                publish_btn.click()
                page.wait_for_timeout(4000)

                _notify(1.0, f"🎉 微信视频号发布成功！标题: {clean_title}")
                return {
                    "success": True,
                    "platform": "wechat",
                    "title": clean_title,
                    "message": "视频已成功提交至微信视频号！",
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
wechat_uploader = WeChatChannelsUploader()


# ── FastAPI 路由与后台任务管理器 ────────────────────────
wechat_router = APIRouter(prefix="/api/wechat", tags=["WeChatChannels"])

wx_publish_tasks: dict[str, dict] = {}
wx_tasks_lock = threading.Lock()


class WeChatPublishRequest(BaseModel):
    video_source: str
    title: str
    desc: str = ""
    tags: list[str] = Field(default_factory=lambda: RECOMMENDED_WECHAT_TAGS)
    cover_source: str = ""


@wechat_router.get("/status")
def get_wx_status():
    """获取微信视频号登录状态"""
    return wechat_uploader.get_account_status()


@wechat_router.get("/qrcode")
def get_wx_qrcode():
    """生成微信视频号扫码二维码"""
    return wechat_uploader.generate_qrcode()


@wechat_router.get("/qrcode/poll")
def poll_wx_qrcode(session_id: str):
    """轮询微信视频号扫码状态"""
    return wechat_uploader.poll_qrcode(session_id)


@wechat_router.post("/browser-login")
def open_wx_browser_login():
    """打开本地 Chrome 浏览器窗口完成微信视频号登录"""
    return wechat_uploader.launch_browser_login()


@wechat_router.post("/logout")
def logout_wx():
    """退出微信视频号登录"""
    return wechat_uploader.logout()


@wechat_router.post("/publish")
def start_wx_publish_task(req: WeChatPublishRequest, background_tasks: BackgroundTasks):
    """创建异步发布微信视频号任务"""
    if not wechat_uploader.is_configured:
        raise HTTPException(400, "尚未登录微信视频号，请先扫码登录")

    task_id = uuid.uuid4().hex[:12]
    with wx_tasks_lock:
        wx_publish_tasks[task_id] = {
            "id": task_id,
            "status": "pending",
            "progress": 0.01,
            "message": "视频号发布任务排队中...",
            "created_at": time.time(),
            "result": None,
            "error": None,
        }

    def _worker():
        def _cb(pct: float, msg: str):
            with wx_tasks_lock:
                if task_id in wx_publish_tasks:
                    wx_publish_tasks[task_id]["progress"] = round(pct, 2)
                    wx_publish_tasks[task_id]["message"] = msg
                    wx_publish_tasks[task_id]["status"] = "uploading" if pct < 0.95 else "submitting"

        try:
            res = wechat_uploader.publish_video(
                video_source=req.video_source,
                title=req.title,
                desc=req.desc,
                tags=req.tags,
                cover_source=req.cover_source,
                progress_callback=_cb,
            )
            with wx_tasks_lock:
                wx_publish_tasks[task_id]["status"] = "completed"
                wx_publish_tasks[task_id]["progress"] = 1.0
                wx_publish_tasks[task_id]["message"] = res.get("message", "发布成功")
                wx_publish_tasks[task_id]["result"] = res
        except Exception as e:
            logger.error(f"微信视频号任务 {task_id} 异常: {e}")
            with wx_tasks_lock:
                wx_publish_tasks[task_id]["status"] = "error"
                wx_publish_tasks[task_id]["message"] = f"发布失败: {str(e)}"
                wx_publish_tasks[task_id]["error"] = str(e)

    background_tasks.add_task(_worker)
    return {"task_id": task_id, "status": "pending"}


@wechat_router.get("/tasks/{task_id}")
def get_wx_publish_task(task_id: str):
    """获取微信视频号发布任务进度"""
    with wx_tasks_lock:
        if task_id not in wx_publish_tasks:
            raise HTTPException(404, "任务不存在")
        return wx_publish_tasks[task_id]
