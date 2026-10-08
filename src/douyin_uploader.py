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
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from src.session_manager import (
    GLOBAL_PUBLISH_SEMAPHORE,
    acquire_publish_lock,
    get_uploader_for_session,
    release_publish_lock,
    resolve_session_id,
)

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
        self.cookies.update(cookies)
        if user_info:
            self.user_info.update(user_info)
        data = {
            "cookies": self.cookies,
            "user": self.user_info,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.cookies_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            from src.session_manager import is_default_session_allowed, _WORK_DIR
            if (
                is_default_session_allowed()
                and self.cookies_path != (_WORK_DIR / "douyin_cookies.json")
                and self.cookies_path.parent.name.startswith("m2v_s_")
            ):
                shutil.copy2(self.cookies_path, _WORK_DIR / "douyin_cookies.json")

        except Exception:
            pass

    def _has_session(self) -> bool:
        """检查是否具有有效的抖音登录态"""
        if not self.cookies:
            return False
        # 兼容原生 sessionid、安全域 sessionid_ss 或 sid_guard + uid_tt/passport
        return bool(
            self.cookies.get("sessionid")
            or self.cookies.get("sessionid_ss")
            or (self.cookies.get("sid_guard") and (self.cookies.get("uid_tt") or self.cookies.get("uid_tt_ss")))
            or self.cookies.get("passport_auth_status") == "verified"
        )

    @property
    def is_configured(self) -> bool:
        """检查是否有基本登录凭证"""
        self._load_cookies()
        return self._has_session()

    def _fetch_user_info_http(self) -> dict:
        """通过轻量 HTTP API 获取最新的抖音创作者昵称与头像"""
        if not self._has_session():
            return {}
        try:
            s = requests.Session()
            s.headers.update({
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": "https://creator.douyin.com/",
            })
            for k, v in self.cookies.items():
                if v:
                    s.cookies.set(k, str(v), domain=".douyin.com")
            r = s.get("https://creator.douyin.com/web/api/media/user/info/", timeout=6)
            if r.status_code == 200:
                data = r.json()
                if data.get("status_code") == 0:
                    u = data.get("user", {})
                    nick = u.get("nickname", "").strip()
                    avatars = u.get("avatar_thumb", {}).get("url_list", [])
                    avatar = avatars[0] if avatars else ""
                    if nick:
                        info = {"is_logged_in": True, "uname": nick, "avatar": avatar}
                        self._save_cookies({}, info)
                        return info
        except Exception as e:
            logger.debug(f"HTTP 获取抖音用户信息失败: {e}")
        return {}

    def get_account_status(self) -> dict:
        """检查当前抖音登录状态"""
        self._load_cookies()
        if self._has_session():
            uname = self.user_info.get("uname")
            avatar = self.user_info.get("avatar", "")
            if not uname or uname == "抖音创作者" or not avatar:
                fetched = self._fetch_user_info_http()
                if fetched:
                    uname = fetched.get("uname", uname)
                    avatar = fetched.get("avatar", avatar)
            uname = uname or "抖音创作者"
            return {
                "is_logged_in": True,
                "is_login": True,
                "uname": uname,
                "avatar": avatar,
                "message": f"已连接抖音创作者中心 ({uname})",
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
        self._stop_qr_session()
        self.cookies = {}
        self.user_info = {}
        if self.cookies_path.exists():
            try:
                self.cookies_path.unlink()
            except Exception:
                pass
        try:
            from src.session_manager import is_default_session_allowed, _WORK_DIR
            if is_default_session_allowed() and (_WORK_DIR / "douyin_cookies.json").exists():
                (_WORK_DIR / "douyin_cookies.json").unlink()
        except Exception:
            pass
        try:
            if self.profile_dir.exists():
                shutil.rmtree(self.profile_dir, ignore_errors=True)
                self.profile_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"清理抖音 profile 失败: {e}")

        return {"success": True, "message": "已成功退出抖音登录"}

    def _clean_locks(self):
        """清理 Chromium 异常退出残留的单例锁文件与僵尸进程"""
        pdir_str = str(self.profile_dir.resolve())
        try:
            res = subprocess.run(["pgrep", "-f", f"--user-data-dir={pdir_str}"], capture_output=True, text=True)
            if res.stdout.strip():
                for pid_str in res.stdout.strip().split():
                    try:
                        os.kill(int(pid_str), 9)
                    except Exception:
                        pass
        except Exception:
            pass
        for name in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
            f = self.profile_dir / name
            try:
                if f.is_symlink() or f.exists() or os.path.lexists(str(f)):
                    f.unlink(missing_ok=True)
            except Exception:
                pass

    def _stop_qr_session(self):
        """安全停止当前的扫码后台会话，释放资源并避免 Profile 目录锁竞争"""
        with self._qr_lock:
            if self._qr_session:
                self._qr_session["cancelled"] = True
                close_fn = self._qr_session.get("close_fn")
                if callable(close_fn):
                    try:
                        close_fn()
                    except Exception:
                        pass
                self._qr_session = None

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
        """获取抖音创作者中心扫码登录二维码并启动多级状态监听"""
        from playwright.sync_api import sync_playwright

        self._stop_qr_session()
        time.sleep(0.5)
        self._clean_locks()

        ready_event = threading.Event()
        result_box = {}
        session_id = uuid.uuid4().hex[:12]

        def _worker():
            playwright_instance = None
            browser_context = None
            try:
                playwright_instance = sync_playwright().start()
                browser_context = playwright_instance.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir.resolve()),
                    channel="chrome",
                    headless=True,
                    viewport={"width": 1280, "height": 800},
                    user_agent=DEFAULT_USER_AGENT,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                    ],
                    ignore_default_args=["--enable-automation"],
                )
                browser_context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """)

                # 注入已有 Cookies（如果有）
                self._load_cookies()
                if self.cookies:
                    c_list = []
                    for k, v in self.cookies.items():
                        if v:
                            c_list.append({"name": k, "value": str(v), "domain": ".douyin.com", "path": "/"})
                            c_list.append({"name": k, "value": str(v), "domain": ".creator.douyin.com", "path": "/"})
                    try:
                        browser_context.add_cookies(c_list)
                    except Exception:
                        pass

                page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()

                def _safe_close():
                    try:
                        browser_context.close()
                    except Exception:
                        pass
                    try:
                        playwright_instance.stop()
                    except Exception:
                        pass

                session_data = {
                    "id": session_id,
                    "status": "waiting",
                    "is_logged_in": False,
                    "uname": "",
                    "avatar": "",
                    "message": "请使用抖音 App 扫描屏幕二维码并确认登录",
                    "cancelled": False,
                    "close_fn": _safe_close,
                }
                with self._qr_lock:
                    self._qr_session = session_data

                # 监听抖音 passport 的 check_qrconnect 接口响应（秒级感知已扫码/已确认）
                def _handle_response(resp):
                    try:
                        if "check_qrconnect" in resp.url and resp.status == 200:
                            data = resp.json().get("data", {})
                            st = data.get("status")
                            if st == "scanned":
                                with self._qr_lock:
                                    if self._qr_session and self._qr_session.get("status") != "success":
                                        self._qr_session["status"] = "scanned"
                                        self._qr_session["message"] = "📱 手机已扫描，请在抖音 App 上点击【确认登录】"
                            elif st == "confirmed":
                                with self._qr_lock:
                                    if self._qr_session:
                                        self._qr_session["status"] = "confirmed"
                                        self._qr_session["message"] = "🎉 手机端已确认授权，正在同步创作者凭据..."
                            elif st == "expired":
                                with self._qr_lock:
                                    if self._qr_session and self._qr_session.get("status") != "success":
                                        self._qr_session["status"] = "expired"
                                        self._qr_session["message"] = "⌛ 二维码已失效，请重新刷新"
                    except Exception:
                        pass

                page.on("response", _handle_response)

                page.goto("https://creator.douyin.com/", wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(3000)

                # 检查页面是否已处于登录态
                current_url = page.url
                cur_cookies = {c["name"]: c["value"] for c in browser_context.cookies()}
                has_login_cookie = bool(cur_cookies.get("sessionid") or cur_cookies.get("sessionid_ss") or cur_cookies.get("sid_guard"))
                if has_login_cookie or "creator-micro" in current_url:
                    uname = "抖音创作者"
                    try:
                        name_el = page.locator('.name-text, [class*="nickname"], [class*="user-name"], [class*="avatar-name"]').first
                        if name_el.count() > 0:
                            uname = name_el.inner_text().strip() or uname
                    except Exception:
                        pass
                    self._save_cookies(cur_cookies, {"is_logged_in": True, "uname": uname})
                    result_box["data"] = {
                        "success": True,
                        "is_logged_in": True,
                        "uname": uname,
                        "message": f"🎉 抖音创作者平台已登录 ({uname})！",
                    }
                    ready_event.set()
                    _safe_close()
                    return

                # 提取纯高清 512x512 二维码图片源
                qr_data_url = ""
                for img in page.locator('[class*="login"] img, img').all():
                    try:
                        src = img.get_attribute("src") or ""
                        box = img.bounding_box()
                        if src.startswith("data:image") and box:
                            w, h = box.get("width", 0), box.get("height", 0)
                            if 120 <= w <= 260 and abs(w - h) <= 25:
                                qr_data_url = src
                                break
                    except Exception:
                        continue

                # 兜底截取纯方形二维码
                if not qr_data_url:
                    for img in page.locator('[class*="login"] img, img').all():
                        try:
                            box = img.bounding_box()
                            if box:
                                w, h = box.get("width", 0), box.get("height", 0)
                                if 120 <= w <= 260 and abs(w - h) <= 25:
                                    qr_bytes = img.screenshot()
                                    qr_data_url = "data:image/png;base64," + base64.b64encode(qr_bytes).decode("utf-8")
                                    break
                        except Exception:
                            continue

                if not qr_data_url:
                    for sel in ['.login-panel-qrcode', '[class*="qrcode-box"]', '[class*="qrcode"]']:
                        loc = page.locator(sel).first
                        if loc.count() > 0:
                            box = loc.bounding_box()
                            if box and 100 <= box.get("width", 0) <= 300:
                                qr_bytes = loc.screenshot()
                                qr_data_url = "data:image/png;base64," + base64.b64encode(qr_bytes).decode("utf-8")
                                break

                if not qr_data_url:
                    result_box["data"] = {"success": False, "message": "未能加载抖音登录二维码"}
                    ready_event.set()
                    _safe_close()
                    return

                result_box["data"] = {
                    "success": True,
                    "session_id": session_id,
                    "qrcode_image": qr_data_url,
                    "message": "请使用抖音 App 扫描屏幕二维码并确认登录",
                }
                ready_event.set()

                # 后台轮询扫码结果，结合 check_qrconnect 与页面 DOM、Cookies 判定
                loop_start = time.time()
                while time.time() - loop_start < 180:
                    if session_data.get("cancelled"):
                        break
                    page.wait_for_timeout(1500)
                    try:
                        cur_url = page.url
                        cur_cookies = {c["name"]: c["value"] for c in browser_context.cookies()}
                        has_login_cookie = bool(cur_cookies.get("sessionid") or cur_cookies.get("sessionid_ss") or cur_cookies.get("sid_guard"))
                        is_confirmed = session_data.get("status") == "confirmed"
                        is_micro = "creator-micro" in cur_url

                        if has_login_cookie or is_confirmed or is_micro:
                            page.wait_for_timeout(2500)
                            cur_cookies = {c["name"]: c["value"] for c in browser_context.cookies()}
                            uname = "抖音创作者"
                            try:
                                name_el = page.locator('.name-text, [class*="nickname"], [class*="user-name"], [class*="avatar-name"]').first
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
                            self._save_cookies(cur_cookies, user_data)
                            with self._qr_lock:
                                session_data["status"] = "success"
                                session_data["is_logged_in"] = True
                                session_data["uname"] = uname
                                session_data["message"] = f"🎉 抖音账号 [{uname}] 登录成功！"
                            break

                        # 检查失效刷新按钮
                        refresh_btn = page.locator(':has-text("点击刷新"), .refresh-btn').first
                        if refresh_btn.count() > 0 and refresh_btn.is_visible():
                            with self._qr_lock:
                                session_data["status"] = "expired"
                                session_data["message"] = "二维码已失效，请重新刷新"
                            break
                    except Exception as e:
                        logger.debug(f"抖音扫码监控循环异常: {e}")
                        break

                _safe_close()
            except Exception as e:
                logger.error(f"抖音扫码线程异常: {e}")
                if not ready_event.is_set():
                    result_box["data"] = {"success": False, "message": f"获取二维码失败: {str(e)}"}
                    ready_event.set()
                if browser_context:
                    try:
                        browser_context.close()
                    except Exception:
                        pass
                if playwright_instance:
                    try:
                        playwright_instance.stop()
                    except Exception:
                        pass

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        ready_event.wait(timeout=25)
        return result_box.get("data", {"success": False, "message": "获取二维码超时，请重试"})

    def poll_qrcode(self, session_id: str) -> dict:
        """轮询抖音扫码状态 (纯内存读，彻底避免跨线程 greenlet 冲突)"""
        st = self.get_account_status()
        if st.get("is_logged_in"):
            return {
                "status": "success",
                "is_logged_in": True,
                "uname": st.get("uname", "抖音创作者"),
                "avatar": "",
                "message": f"🎉 抖音账号 [{st.get('uname')}] 登录成功！",
            }

        with self._qr_lock:
            if not self._qr_session or self._qr_session.get("id") != session_id:
                return {"status": "expired", "message": "扫码会话已过期，请重新获取二维码"}
            return {
                "status": self._qr_session.get("status", "waiting"),
                "is_logged_in": self._qr_session.get("is_logged_in", False),
                "uname": self._qr_session.get("uname", ""),
                "avatar": self._qr_session.get("avatar", ""),
                "message": self._qr_session.get("message", "等待用户扫码确认..."),
            }

    def launch_browser_login(self) -> dict:
        """打开 Chrome 窗口供创作者登录抖音"""
        from playwright.sync_api import sync_playwright

        self._stop_qr_session()
        time.sleep(0.5)
        self._clean_locks()

        def _run():
            playwright_instance = None
            browser_context = None
            try:
                playwright_instance = sync_playwright().start()
                browser_context = playwright_instance.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir.resolve()),
                    channel="chrome",
                    headless=False,
                    viewport={"width": 1280, "height": 850},
                    user_agent=DEFAULT_USER_AGENT,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                    ],
                    ignore_default_args=["--enable-automation"],
                )
                browser_context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """)
                page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()
                page.goto("https://creator.douyin.com/", wait_until="domcontentloaded")

                start_time = time.time()
                while time.time() - start_time < 240:
                    try:
                        if page.is_closed():
                            break
                        cookies = {c["name"]: c["value"] for c in browser_context.cookies()}
                        has_login = bool(cookies.get("sessionid") or cookies.get("sessionid_ss") or cookies.get("sid_guard"))
                        if has_login or "creator-micro" in page.url:
                            uname = "抖音创作者"
                            try:
                                name_el = page.locator('.name-text, [class*="nickname"], [class*="user-name"], [class*="avatar-name"]').first
                                if name_el.count() > 0:
                                    uname = name_el.inner_text().strip() or uname
                            except Exception:
                                pass
                            self._save_cookies(cookies, {"is_logged_in": True, "uname": uname})
                            logger.info(f"抖音前台窗口登录成功 [{uname}] 并已捕获凭据")
                            page.wait_for_timeout(3000)
                            break
                    except Exception:
                        pass
                    time.sleep(2)
                browser_context.close()
                playwright_instance.stop()
            except Exception as e:
                logger.error(f"抖音浏览器前台登录异常: {e}")
                if browser_context:
                    try:
                        browser_context.close()
                    except Exception:
                        pass
                if playwright_instance:
                    try:
                        playwright_instance.stop()
                    except Exception:
                        pass

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return {"success": True, "message": "已打开系统 Chrome 窗口，请在浏览器中扫码或验证码登录"}

    def publish_video(
        self,
        video_source: str,
        title: str,
        desc: str = "",
        tags: Optional[list[str]] = None,
        cover_source: str = "",
        progress_callback: Optional[Callable[..., None]] = None,
        headless: bool = True,
    ) -> dict:
        """自动化发布视频到抖音 (支持上传等待、多重表单填写与风控扫码验证)"""
        from playwright.sync_api import sync_playwright

        def _notify(pct: float, msg: str, **kwargs):
            if progress_callback:
                try:
                    progress_callback(pct, msg, **kwargs)
                except TypeError:
                    progress_callback(pct, msg)

        temp_video_file = None
        temp_cover_file = None
        local_video_path = video_source

        # 1. 确保释放 QR 锁与单例锁
        self._stop_qr_session()
        time.sleep(0.5)
        self._clean_locks()
        self._load_cookies()

        # 检查是否已存在登录凭证
        if not self._has_session():
            raise RuntimeError("尚未登录抖音账号或登录凭证已失效，请先扫码或在浏览器窗口中登录")

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
        final_desc = f"{desc.strip()} {tag_text}".strip()

        _notify(0.15, "正在启动浏览器并连接抖音创作者中心...")
        playwright_instance = None
        browser_context = None
        try:
            playwright_instance = sync_playwright().start()
            browser_context = playwright_instance.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir.resolve()),
                channel="chrome",
                headless=headless,
                viewport={"width": 1280, "height": 900},
                user_agent=DEFAULT_USER_AGENT,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ],
                ignore_default_args=["--enable-automation"],
            )
            browser_context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = {
                    runtime: {},
                    loadTimes: function() {},
                    csi: function() {},
                    app: {}
                };
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['zh-CN', 'zh', 'en']
                });
            """)


            # 注入所有抖音 Cookies 确保会话就绪
            if self.cookies:
                cookie_items = []
                for k, v in self.cookies.items():
                    if not v:
                        continue
                    cookie_items.append({
                        "name": k,
                        "value": str(v),
                        "domain": ".douyin.com",
                        "path": "/",
                    })
                    cookie_items.append({
                        "name": k,
                        "value": str(v),
                        "domain": ".creator.douyin.com",
                        "path": "/",
                    })
                try:
                    browser_context.add_cookies(cookie_items)
                except Exception as ce:
                    logger.warning(f"注入抖音 Cookies 异常: {ce}")

            page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()

            _notify(0.25, "正在打开抖音视频发布页面...")
            page.goto("https://creator.douyin.com/creator-micro/content/upload", wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(3000)

            # 检查是否展示登录表单
            login_box = page.locator('.web-login-area-code-input, .login-panel, [class*="login-card"], [class*="login-panel"], :has-text("手机号登录")')
            if login_box.count() > 0 and login_box.first.is_visible():
                raise RuntimeError("抖音未登录或登录凭据已失效，请重新扫码登录")

            # 自动关闭常见阻挡弹窗与提示
            for btn_text in ["我知道了", "同意并继续", "同意", "好的", "知道了", "跳过"]:
                try:
                    btn = page.locator(f'button:has-text("{btn_text}"), div[role="button"]:has-text("{btn_text}")').first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(800)
                except Exception:
                    pass

            _notify(0.35, "正在等待抖音上传控件就绪...")
            file_input = page.locator('input[type="file"]').first
            try:
                file_input.wait_for(state="attached", timeout=25000)
            except Exception:
                if login_box.count() > 0 and login_box.first.is_visible():
                    raise RuntimeError("抖音未登录或登录凭据已失效，请重新扫码登录")
                inputs = page.locator('input[type="file"]').all()
                if not inputs:
                    raise RuntimeError("未找到抖音视频上传控件，页面加载超时或尚未完成登录")
                file_input = inputs[0]

            _notify(0.40, "正在上传视频文件到抖音并等待云端转码解析...")
            file_input.set_input_files(local_video_path)

            upload_start = time.time()
            upload_ready = False
            while time.time() - upload_start < 180:
                # 严格判定真实完成指标：“重新上传”按钮可见代表视频已 100% 成功解析
                reupload_btn = page.locator(':text-is("重新上传")')
                if reupload_btn.count() > 0 and reupload_btn.first.is_visible():
                    upload_ready = True
                    break
                page.wait_for_timeout(1500)
                elapsed = int(time.time() - upload_start)
                if elapsed % 5 == 0:
                    pct = min(0.40 + elapsed * 0.003, 0.70)
                    _notify(pct, f"视频正在上传并解析中 ({elapsed}s)...")

            if not upload_ready:
                raise RuntimeError("抖音视频上传或转码超时 (超过180秒)")

            _notify(0.75, "视频上传及解析完成！正在填写标题与描述标签...")
            page.wait_for_timeout(1000)

            # 填写标题 (优先独立的标题输入框)
            title_input = page.locator('input[placeholder*="作品标题"], input[placeholder*="标题"]').first
            if title_input.count() > 0 and title_input.is_visible():
                try:
                    title_input.click()
                    page.wait_for_timeout(200)
                    page.keyboard.press("Meta+A")
                    page.keyboard.press("Backspace")
                    title_input.fill(clean_title[:30])
                    page.wait_for_timeout(500)
                except Exception as te:
                    logger.warning(f"填写标题输入框异常: {te}")

            # 填写作品描述与话题 (富文本区)
            desc_input = page.locator('.zone-container, [contenteditable="true"]').first
            if desc_input.count() > 0 and desc_input.is_visible():
                try:
                    desc_input.click()
                    page.wait_for_timeout(300)
                    page.keyboard.press("Meta+A")
                    page.keyboard.press("Backspace")
                    page.keyboard.type(final_desc, delay=15)
                    page.wait_for_timeout(1000)
                except Exception as de:
                    logger.warning(f"填写描述与话题异常: {de}")

            # 再次清理可能弹出的新手引导或提醒气泡
            for btn_text in ["我知道了", "好的", "知道了"]:
                try:
                    btn = page.locator(f'button:has-text("{btn_text}")').first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(500)
                except Exception:
                    pass

            _notify(0.88, "正在定位抖音【发布】提交按钮...")
            # 严格筛选：排除导航栏的“作品发布”，精确定位表单底部的“发布”操作按钮
            pub_btn = page.locator('button.button-dhlUZE:text-is("发布"), button:text-is("发布")').last
            if pub_btn.count() == 0:
                raise RuntimeError("未在抖音发布页面找到【发布】提交按钮")

            pub_btn.scroll_into_view_if_needed()
            page.wait_for_timeout(500)

            _notify(0.92, "正在点击提交发布...")
            pub_btn.click()

            # 监控提交后响应（防虚假成功，严格验证重定向、Toast 或风控验证弹窗）
            _notify(0.94, "已提交发布，正在等待抖音平台确认处理结果...")
            submit_start = time.time()
            verified_success = False

            while time.time() - submit_start < 60:
                page.wait_for_timeout(1500)
                cur_url = page.url

                # 1. 成功重定向至作品管理页
                if "creator-micro/content/manage" in cur_url:
                    verified_success = True
                    break

                # 2. 检查轻提示 Toast (使用 text_content 兼容 SVG/各种节点，并做安全捕获)
                try:
                    toast_loc = page.locator('.semi-toast-content, .semi-toast, div[class*="toast"]')
                    for idx in range(min(toast_loc.count(), 10)):
                        try:
                            t = toast_loc.nth(idx)
                            if t.is_visible():
                                tt = (t.text_content() or "").strip()
                                if "发布成功" in tt or "作品发布成功" in tt:
                                    verified_success = True
                                    break
                                elif any(k in tt for k in ["违规", "频繁", "错误", "失败"]):
                                    raise RuntimeError(f"抖音发布拒绝: {tt}")
                        except RuntimeError:
                            raise
                        except Exception:
                            pass
                except RuntimeError:
                    raise
                except Exception:
                    pass

                if verified_success:
                    break

                # 3. 检查是否触发安全风控二次验证弹窗
                verify_modal = page.locator('.semi-modal, [class*="modal"], [class*="verify"]').first
                is_modal_vis = False
                try:
                    is_modal_vis = verify_modal.count() > 0 and verify_modal.is_visible()
                except Exception:
                    pass

                has_verify_text = False
                try:
                    has_verify_text = page.locator(':text-is("身份验证"), :text-is("接收短信验证码"), :text-is("使用原设备扫码"), :text-is("选择其他验证方式")').count() > 0
                except Exception:
                    pass

                if is_modal_vis and has_verify_text:

                    _notify(0.95, "⚠️ 触发抖音安全风控验证，正在准备扫码确认...")
                    # 尝试切换为原设备扫码验证
                    other_btn = page.locator('text=选择其他验证方式').first
                    if other_btn.count() > 0 and other_btn.is_visible():
                        try:
                            other_btn.click()
                            page.wait_for_timeout(1000)
                            qr_opt = page.locator('text=扫码验证').first
                            if qr_opt.count() > 0 and qr_opt.is_visible():
                                qr_opt.click()
                                page.wait_for_timeout(2000)
                        except Exception:
                            pass

                    # 提取验证二维码图片
                    qr_img_loc = page.locator('.uc-ui-verify_qr-verify_main_qr-img, .semi-modal img[src*="base64"], [class*="modal"] img[src*="base64"]').first
                    qr_data_url = ""
                    if qr_img_loc.count() > 0 and qr_img_loc.is_visible():
                        qr_data_url = qr_img_loc.get_attribute("src") or ""

                    _notify(
                        0.95,
                        "⚠️ 首次在此设备发布作品需安全授信：请使用【抖音APP】扫描屏幕二维码确认（仅需一次）",
                        qr_image=qr_data_url,
                        status="needs_verification",
                    )

                    # 循环等待用户在手机端扫码确认授信 (最多等待 120 秒)
                    v_start = time.time()
                    while time.time() - v_start < 120:
                        page.wait_for_timeout(2000)
                        try:
                            if "creator-micro/content/manage" in page.url:
                                verified_success = True
                                break
                            if verify_modal.count() == 0 or not verify_modal.is_visible():
                                page.wait_for_timeout(3000)
                                if "creator-micro/content/manage" in page.url or page.locator(':text-is("发布成功")').count() > 0:
                                    verified_success = True
                                    break
                        except Exception:
                            pass
                    if verified_success:
                        break

                    raise RuntimeError("抖音安全风控验证超时 (未在120秒内完成扫码确认)。请点击【打开浏览器登录】在 Chrome 窗口中操作一次以授信当前设备。")


            if not verified_success:
                # 兜底访问作品管理页检查最新作品标题是否存在
                try:
                    page.goto("https://creator.douyin.com/creator-micro/content/manage", wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(2500)
                    if clean_title in page.content():
                        verified_success = True
                except Exception:
                    pass

            if not verified_success:
                raise RuntimeError("抖音未能确认发布结果，未在作品管理列表中检索到该视频。请重试或在浏览器窗口中发布。")

            # 同步更新持久化 Cookies
            try:
                new_cookies = {c["name"]: c["value"] for c in browser_context.cookies()}
                if new_cookies:
                    self._save_cookies(new_cookies)
            except Exception:
                pass

            _notify(1.0, f"🎉 抖音作品发布成功！标题: {clean_title}")
            return {
                "success": True,
                "platform": "douyin",
                "title": clean_title,
                "message": "作品已成功发布至抖音创作者中心！",
            }
        finally:
            if browser_context:
                try:
                    browser_context.close()
                except Exception:
                    pass
            if playwright_instance:
                try:
                    playwright_instance.stop()
                except Exception:
                    pass
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
def get_dy_status(sid: str = Depends(resolve_session_id)):
    """获取抖音登录状态"""
    uploader = get_uploader_for_session("douyin", sid)
    return uploader.get_account_status()


@douyin_router.get("/qrcode")
def get_dy_qrcode(sid: str = Depends(resolve_session_id)):
    """生成抖音扫码二维码"""
    uploader = get_uploader_for_session("douyin", sid)
    return uploader.generate_qrcode()


@douyin_router.get("/qrcode/poll")
def poll_dy_qrcode(session_id: str, sid: str = Depends(resolve_session_id)):
    """轮询抖音扫码状态"""
    uploader = get_uploader_for_session("douyin", sid)
    return uploader.poll_qrcode(session_id)


@douyin_router.post("/browser-login")
def open_dy_browser_login(sid: str = Depends(resolve_session_id)):
    """打开本地 Chrome 浏览器窗口完成抖音登录"""
    uploader = get_uploader_for_session("douyin", sid)
    return uploader.launch_browser_login()


@douyin_router.post("/logout")
def logout_dy(sid: str = Depends(resolve_session_id)):
    """退出抖音登录"""
    uploader = get_uploader_for_session("douyin", sid)
    return uploader.logout()


@douyin_router.post("/publish")
def start_dy_publish_task(
    req: DouyinPublishRequest,
    background_tasks: BackgroundTasks,
    sid: str = Depends(resolve_session_id),
):
    """创建异步发布抖音任务"""
    uploader = get_uploader_for_session("douyin", sid)
    if not uploader.is_configured:
        raise HTTPException(400, "尚未登录抖音账号，请先扫码登录")

    if not acquire_publish_lock(sid, "douyin", video_source=req.video_source):
        raise HTTPException(409, "抖音已有任务正在发布中，请勿重复提交")

    task_id = uuid.uuid4().hex[:12]
    with dy_tasks_lock:
        dy_publish_tasks[task_id] = {
            "id": task_id,
            "session_id": sid,
            "status": "pending",
            "progress": 0.01,
            "message": "抖音发布任务排队中...",
            "created_at": time.time(),
            "result": None,
            "error": None,
        }

    def _worker():
        def _cb(pct: float, msg: str, **kwargs):
            with dy_tasks_lock:
                if task_id in dy_publish_tasks:
                    dy_publish_tasks[task_id]["progress"] = round(pct, 2)
                    dy_publish_tasks[task_id]["message"] = msg
                    qr = kwargs.get("qr_image") or kwargs.get("extra", {}).get("qr_image")
                    if qr:
                        dy_publish_tasks[task_id]["qr_image"] = qr
                        dy_publish_tasks[task_id]["status"] = "needs_verification"
                    else:
                        dy_publish_tasks[task_id]["status"] = "uploading" if pct < 0.95 else "submitting"


        try:
            with GLOBAL_PUBLISH_SEMAPHORE:
                res = uploader.publish_video(
                    video_source=req.video_source,
                    title=req.title,
                    desc=req.desc,
                    tags=req.tags,
                    cover_source=req.cover_source,
                    progress_callback=_cb,
                )
            res = res or {}
            is_failed = res.get("success") is False or res.get("status") == "error"
            is_review = (
                res.get("status") in ["under_review", "reviewing", "pending_review"]
                or res.get("is_review") is True
                or ("审核" in str(res.get("message", "")))
            )

            with dy_tasks_lock:
                dy_publish_tasks[task_id]["progress"] = 1.0
                dy_publish_tasks[task_id]["result"] = res
                if is_failed:
                    dy_publish_tasks[task_id]["status"] = "error"
                    dy_publish_tasks[task_id]["message"] = res.get("message", "发布失败")
                    dy_publish_tasks[task_id]["error"] = res.get("message", "平台返回失败")
                elif is_review:
                    dy_publish_tasks[task_id]["status"] = "under_review"
                    dy_publish_tasks[task_id]["message"] = res.get("message", "提交成功，正在审核中")
                else:
                    dy_publish_tasks[task_id]["status"] = "completed"
                    dy_publish_tasks[task_id]["message"] = res.get("message", "发布成功")

        except Exception as e:
            logger.error(f"抖音任务 {task_id} 异常: {e}")
            with dy_tasks_lock:
                dy_publish_tasks[task_id]["status"] = "error"
                dy_publish_tasks[task_id]["message"] = f"发布失败: {str(e)}"
                dy_publish_tasks[task_id]["error"] = str(e)
        finally:
            release_publish_lock(sid, "douyin")

    background_tasks.add_task(_worker)
    return {"task_id": task_id, "status": "pending"}


@douyin_router.get("/tasks/{task_id}")
def get_dy_publish_task(task_id: str, sid: str = Depends(resolve_session_id)):
    """获取抖音发布任务进度 (防越权访问)"""
    with dy_tasks_lock:
        if task_id not in dy_publish_tasks:
            raise HTTPException(404, "任务不存在")
        task = dy_publish_tasks[task_id]
        task_owner = task.get("session_id")
        if task_owner and task_owner != sid and sid != "default":
            raise HTTPException(404, "任务不存在或无权访问")
        safe_copy = dict(task)
        safe_copy.pop("session_id", None)
        return safe_copy
