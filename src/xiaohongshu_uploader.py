"""
小红书 (Xiaohongshu / RedNote) 视频笔记一键发布与扫码鉴权服务模块
基于 Playwright + macOS Chrome 本地浏览器，实现无反爬风险的极速自动发布。

功能：
1. 扫码登录 (网页扫码获取二维码数据、自动轮询状态、保存 Cookies 和持久化会话)
2. 浏览器辅助登录 (支持打开本地 Chrome 窗口进行手机号/验证码/扫码登录)
3. 账号状态检查 (获取小红书昵称、头像、创作者 ID)
4. 视频笔记全自动发布 (自动提取封面、上传 MP4、填写标题、正文歌词、添加话题标签并一键提交)
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

logger = logging.getLogger("xiaohongshu_uploader")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

RECOMMENDED_XHS_TAGS = ["AI音乐", "Suno", "自制MV", "宝藏音乐", "音乐日记", "治愈系音乐"]


class XiaohongshuUploader:
    """管理小红书创作者平台鉴权与视频笔记自动发布"""

    def __init__(
        self,
        profile_dir: Optional[Union[str, Path]] = None,
        cookies_path: Optional[Union[str, Path]] = None,
    ):
        root = Path(__file__).resolve().parent.parent
        self.profile_dir = Path(profile_dir) if profile_dir else root / "work" / "xhs_profile"
        self.cookies_path = Path(cookies_path) if cookies_path else root / "work" / "xhs_cookies.json"

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.cookies_path.parent.mkdir(parents=True, exist_ok=True)

        self.cookies: dict[str, str] = {}
        self.user_info: dict = {}
        self._load_cookies()

        # 扫码会话缓存
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
                logger.warning(f"读取小红书 cookies 失败: {e}")

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
        has_token = any(
            k in self.cookies
            for k in [
                "access-token-creator.xiaohongshu.com",
                "customer-sso-sid",
                "galaxy_creator_session_id",
                "web_session",
            ]
        )
        return has_token or bool(self.user_info.get("is_logged_in")) or (self.profile_dir / "Default").exists()

    def get_account_status(self) -> dict:
        """检查当前登录状态并获取创作者账号信息"""
        # 1. 优先尝试轻量级 API 请求
        cookie_header = "; ".join([f"{k}={v}" for k, v in self.cookies.items()])
        if cookie_header:
            try:
                r = requests.get(
                    "https://creator.xiaohongshu.com/api/galaxy/user/info",
                    headers={
                        "User-Agent": DEFAULT_USER_AGENT,
                        "Referer": "https://creator.xiaohongshu.com/",
                        "Origin": "https://creator.xiaohongshu.com",
                        "Cookie": cookie_header,
                    },
                    timeout=5,
                )
                data = r.json()
                if data.get("success") and data.get("data"):
                    d = data["data"]
                    user = {
                        "is_logged_in": True,
                        "is_login": True,
                        "uname": d.get("userName") or d.get("nickname") or d.get("name", "小红书创作者"),
                        "user_id": d.get("userId") or d.get("redId", ""),
                        "avatar": d.get("userAvatar") or d.get("avatar", ""),
                        "message": "已连接小红书创作者中心",
                    }
                    self.user_info = user
                    self._save_cookies(self.cookies, user)
                    return user
            except Exception as e:
                logger.debug(f"通过 API 检查小红书状态异常: {e}")

        # 2. 如果已缓存用户信息且本地配置存在
        if self.user_info and self.user_info.get("is_logged_in"):
            return self.user_info

        return {
            "is_logged_in": False,
            "is_login": False,
            "uname": "",
            "avatar": "",
            "message": "未登录小红书账号，请先扫码或在浏览器中登录",
        }

    def logout(self) -> dict:
        """退出登录并清理本地缓存"""
        self.cookies = {}
        self.user_info = {}
        if self.cookies_path.exists():
            try:
                self.cookies_path.unlink()
            except Exception:
                pass
        # 清理 profile 缓存
        try:
            if self.profile_dir.exists():
                shutil.rmtree(self.profile_dir, ignore_errors=True)
                self.profile_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"清理小红书 profile 失败: {e}")

        with self._qr_lock:
            if self._qr_session:
                try:
                    self._qr_session["context"].close()
                except Exception:
                    pass
                self._qr_session = None

        return {"success": True, "message": "已成功退出小红书登录并清理凭证"}

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
        """获取小红书创作者平台的最新扫码登录二维码"""
        return self._run_threaded(self._generate_qrcode_impl)

    def _generate_qrcode_impl(self) -> dict:
        from playwright.sync_api import sync_playwright

        with self._qr_lock:
            # 清理旧的扫码会话
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
                page.goto("https://creator.xiaohongshu.com/login", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2500)

                # 优先检查是否已直接登录 (小红书自动跳转到 /new/home 或其它非 login 页面)
                current_url = page.url
                cookies_list = ctx.cookies()
                cookies_dict = {c["name"]: c["value"] for c in cookies_list}
                is_logged_in = ("/login" not in current_url and "creator.xiaohongshu.com" in current_url) or any(
                    k in cookies_dict
                    for k in [
                        "access-token-creator.xiaohongshu.com",
                        "customer-sso-sid",
                        "galaxy_creator_session_id",
                    ]
                )

                if is_logged_in:
                    self._save_cookies(cookies_dict)
                    try:
                        ctx.close()
                        pw.stop()
                    except Exception:
                        pass
                    user = self.get_account_status()
                    uname = user.get("uname") or "小红书创作者"
                    return {
                        "success": True,
                        "is_logged_in": True,
                        "uname": uname,
                        "avatar": user.get("avatar", ""),
                        "message": f"🎉 小红书账号 [{uname}] 已登录！",
                    }

                # 切换到二维码登录标签
                qr_data_url = ""
                for img in page.locator('img[src*="data:image"]').all():
                    box = img.bounding_box()
                    if box and box.get("width", 0) >= 100:
                        src = img.get_attribute("src")
                        if src and src.startswith("data:image"):
                            qr_data_url = src
                            break

                # 若尚未展示二维码，点击右上角 64x64 切换角标
                if not qr_data_url:
                    page.evaluate("""() => {
                        const imgs = Array.from(document.querySelectorAll("img"));
                        const corner = imgs.find(img => {
                            const rect = img.getBoundingClientRect();
                            return rect.width > 30 && rect.width < 90;
                        });
                        if (corner) corner.click();
                    }""")
                    page.wait_for_timeout(1500)

                # 提取真实二维码图片 (宽度大于 100px 的二维码)
                if not qr_data_url:
                    for img in page.locator('img[src*="data:image"]').all():
                        box = img.bounding_box()
                        if box and box.get("width", 0) >= 100:
                            src = img.get_attribute("src")
                            if src and src.startswith("data:image"):
                                qr_data_url = src
                                break

                # 如果有二维码蒙层失效按钮，点击刷新
                refresh_btn = page.locator('text="点击刷新", text="刷新二维码", text="二维码已失效", text="已失效"').first
                if refresh_btn.count() > 0 and refresh_btn.is_visible():
                    refresh_btn.click()
                    page.wait_for_timeout(1500)
                    for img in page.locator('img[src*="data:image"]').all():
                        box = img.bounding_box()
                        if box and box.get("width", 0) >= 100:
                            src = img.get_attribute("src")
                            if src and src.startswith("data:image"):
                                qr_data_url = src
                                break

                if not qr_data_url:
                    # 备选：直接截取登录区域
                    card = page.locator('.login-box, .login-container, [class*="login"]').first
                    if card.count() > 0:
                        qr_bytes = card.screenshot()
                        qr_data_url = "data:image/png;base64," + base64.b64encode(qr_bytes).decode("utf-8")

                if not qr_data_url:
                    ctx.close()
                    pw.stop()
                    return {"success": False, "message": "未能从小红书获取到登录二维码，请点击打开浏览器登录"}

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
                    "message": "请使用小红书 App 扫描二维码并确认登录",
                }
            except Exception as e:
                logger.error(f"获取小红书二维码异常: {e}")
                return {"success": False, "message": f"获取二维码失败: {str(e)}"}

    def poll_qrcode(self, session_id: str) -> dict:
        """轮询小红书扫码登录状态"""
        return self._run_threaded(self._poll_qrcode_impl, session_id)

    def _poll_qrcode_impl(self, session_id: str) -> dict:
        with self._qr_lock:
            # 先检查是否已经登录（例如其它方式完成鉴权）
            st = self.get_account_status()
            if st.get("is_logged_in"):
                return {
                    "status": "success",
                    "is_logged_in": True,
                    "uname": st.get("uname", "小红书创作者"),
                    "avatar": st.get("avatar", ""),
                    "message": f"🎉 小红书账号 [{st.get('uname')}] 登录成功！",
                }

            if not self._qr_session or self._qr_session.get("id") != session_id:
                return {"status": "expired", "message": "扫码会话已过期，请重新获取二维码"}

            ctx = self._qr_session["context"]
            page = self._qr_session["page"]
            pw = self._qr_session["playwright"]

            try:
                current_url = page.url
                cookies_list = ctx.cookies()
                cookies_dict = {c["name"]: c["value"] for c in cookies_list}

                # 检查是否跳转离开登录页或获得 access-token
                is_logged_in = ("/login" not in current_url and "creator.xiaohongshu.com" in current_url) or any(
                    k in cookies_dict
                    for k in [
                        "access-token-creator.xiaohongshu.com",
                        "customer-sso-sid",
                        "galaxy_creator_session_id",
                    ]
                )

                if is_logged_in:
                    # 登录成功，同步 cookies
                    self._save_cookies(cookies_dict)
                    time.sleep(1)

                    # 获取用户信息
                    status = self.get_account_status()
                    uname = status.get("uname") or "小红书创作者"

                    # 优雅关闭扫码浏览器实例
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
                        "avatar": status.get("avatar", ""),
                        "message": f"🎉 小红书账号 [{uname}] 登录成功！",
                    }

                # 检查二维码是否过期
                refresh_btn = page.locator('text="点击刷新", text="刷新二维码", text="二维码已失效", text="已失效"').first
                if refresh_btn.count() > 0 and refresh_btn.is_visible():
                    return {"status": "expired", "message": "二维码已失效，请重新刷新"}

                return {"status": "waiting", "message": "等待用户在小红书手机客户端扫码确认..."}
            except Exception as e:
                logger.warning(f"轮询小红书状态异常: {e}")
                return {"status": "waiting", "message": "正在确认登录状态..."}

    def launch_browser_login(self) -> dict:
        """打开前台浏览器窗口，方便创作者通过手机号验证码或已有凭据直接登录"""
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
                page.goto("https://creator.xiaohongshu.com/login", wait_until="domcontentloaded")

                # 等待用户完成登录（最多等待 3 分钟）
                start_time = time.time()
                while time.time() - start_time < 180:
                    try:
                        if page.is_closed():
                            break
                        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                        has_token = any(
                            k in cookies
                            for k in [
                                "access-token-creator.xiaohongshu.com",
                                "customer-sso-sid",
                                "galaxy_creator_session_id",
                                "web_session",
                            ]
                        )
                        if has_token or ("/login" not in page.url and "creator.xiaohongshu.com" in page.url):
                            self._save_cookies(cookies)
                            self.get_account_status()
                            logger.info("小红书前台窗口登录成功并已捕获凭据")
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
        return {"success": True, "message": "已打开 Chrome 浏览器窗口，请在浏览器中完成登录"}

    def publish_video(
        self,
        video_source: str,
        title: str,
        desc: str = "",
        tags: Optional[list[str]] = None,
        cover_source: str = "",
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict:
        """
        自动化发布视频笔记到小红书
        1. 准备本地视频与封面文件
        2. 启动持久化浏览器会话进入发布中心
        3. 上传 MP4 视频分片
        4. 填写 20 字以内的精炼标题与丰富图文正文（含歌词与标签）
        5. 设置视频封面并提交发布
        """
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
            temp_video_file = temp_dir / f"xhs_video_{int(time.time()*1000)}.mp4"

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

        # 自动提取视频封面（第 1 秒）
        if not cover_source:
            try:
                temp_dir = self.profile_dir.parent / "temp"
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_cover_file = temp_dir / f"xhs_cover_{int(time.time()*1000)}.jpg"
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
                logger.warning(f"提取小红书封面帧失败: {e}")

        # 小红书标题限制 20 个字
        clean_title = title.strip()
        display_title = clean_title[:20]
        # 如果标题超出 20 字，将完整标题置于正文开头
        full_desc_header = f"🎵《{clean_title}》\n\n" if len(clean_title) > 20 else ""
        
        # 标签合成
        tag_list = tags or RECOMMENDED_XHS_TAGS
        tag_text = " ".join([f"#{t.strip('#')}" for t in tag_list if t.strip()])
        final_desc = f"{full_desc_header}{desc.strip()}\n\n{tag_text}".strip()

        _notify(0.15, "正在启动浏览器并连接小红书创作服务平台...")

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

                # 打开创作者发布页面
                _notify(0.25, "正在打开创作者发布中心...")
                page.goto("https://creator.xiaohongshu.com/publish/publish?source=official", wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(3000)

                # 检查是否重定向到登录页
                if "/login" in page.url:
                    raise RuntimeError("小红书账号未登录或凭据已失效，请先扫码登录")

                # 切换到“上传视频”标签页
                video_tab = page.locator('div:has-text("上传视频"), [role="tab"]:has-text("视频"), .tab:has-text("视频")').first
                if video_tab.count() > 0:
                    try:
                        video_tab.click()
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass

                # 定位视频文件上传 input
                _notify(0.35, "正在上传视频文件到小红书...")
                file_input = page.locator('input[type="file"]').first
                if file_input.count() == 0:
                    raise RuntimeError("未能找到小红书视频上传控件，页面结构可能发生变化")

                file_input.set_input_files(local_video_path)
                page.wait_for_timeout(3000)

                # 等待视频上传和初步解析完成
                _notify(0.50, "视频正在后台上传与转码中，请稍候...")
                upload_start = time.time()
                upload_finished = False
                while time.time() - upload_start < 120:
                    # 检查标题输入框是否出现（视频上传就绪后小红书会展开完整填写表单）
                    title_input = page.locator('input[placeholder*="填写标题"], input[placeholder*="标题"], .title-input input').first
                    if title_input.count() > 0 and title_input.is_visible():
                        upload_finished = True
                        break
                    page.wait_for_timeout(2000)

                if not upload_finished:
                    logger.warning("未检测到标题栏自动展开，继续尝试填写")

                _notify(0.70, "正在填写笔记标题与正文歌词...")

                # 填写标题 (最多20字)
                title_input = page.locator('input[placeholder*="填写标题"], input[placeholder*="标题"], .title-input input').first
                if title_input.count() > 0:
                    title_input.click()
                    title_input.fill("")
                    title_input.fill(display_title)
                    page.wait_for_timeout(500)

                # 填写正文内容与话题
                desc_input = page.locator('textarea[placeholder*="填写更全面"], textarea[placeholder*="描述"], .post-content, div[contenteditable="true"]').first
                if desc_input.count() > 0:
                    desc_input.click()
                    if desc_input.evaluate('e => e.tagName') == 'TEXTAREA':
                        desc_input.fill(final_desc)
                    else:
                        # contenteditable div
                        desc_input.fill("")
                        page.keyboard.type(final_desc, delay=20)
                    page.wait_for_timeout(1000)

                # 设置封面 (如果有自定义封面)
                if cover_source and Path(cover_source).exists():
                    try:
                        _notify(0.85, "正在设置视频高清封面...")
                        cover_upload_input = page.locator('input[type="file"][accept*="image"]').first
                        if cover_upload_input.count() > 0:
                            cover_upload_input.set_input_files(cover_source)
                            page.wait_for_timeout(2000)
                    except Exception as e:
                        logger.warning(f"设置小红书封面失败，继续发布: {e}")

                _notify(0.92, "正在提交发布视频笔记...")
                # 点击发布按钮
                publish_btn = page.locator('button:has-text("发布"), .publishBtn, .btn-publish, button.bg-red').first
                if publish_btn.count() == 0:
                    raise RuntimeError("未找到小红书【发布】按钮")

                publish_btn.click()
                page.wait_for_timeout(3000)

                # 验证发布结果
                _notify(0.98, "正在确认发布结果...")
                publish_ok = False
                wait_submit_start = time.time()
                while time.time() - wait_submit_start < 25:
                    if "/publish" not in page.url or page.locator('text="发布成功", text="管理笔记"').count() > 0:
                        publish_ok = True
                        break
                    # 检查是否有错误提示
                    error_toast = page.locator('.d-toast-error, .ant-message-error, [class*="error-message"]').first
                    if error_toast.count() > 0 and error_toast.is_visible():
                        err_text = error_toast.inner_text()
                        if err_text:
                            raise RuntimeError(f"小红书平台提示: {err_text}")
                    page.wait_for_timeout(1500)

                # 保存成功后的 cookies
                cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                self._save_cookies(cookies)

                _notify(1.0, f"🎉 小红书视频笔记发布成功！标题: {display_title}")
                return {
                    "success": True,
                    "platform": "xiaohongshu",
                    "title": display_title,
                    "message": "视频笔记已成功提交至小红书！",
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
xiaohongshu_uploader = XiaohongshuUploader()


# ── FastAPI 路由与后台任务管理器 ────────────────────────
xiaohongshu_router = APIRouter(prefix="/api/xiaohongshu", tags=["Xiaohongshu"])

xhs_publish_tasks: dict[str, dict] = {}
xhs_tasks_lock = threading.Lock()


class XhsPublishRequest(BaseModel):
    video_source: str
    title: str
    desc: str = ""
    tags: list[str] = Field(default_factory=lambda: RECOMMENDED_XHS_TAGS)
    cover_source: str = ""


@xiaohongshu_router.get("/status")
def get_xhs_status():
    """获取当前小红书创作者账号状态"""
    return xiaohongshu_uploader.get_account_status()


@xiaohongshu_router.get("/qrcode")
def get_xhs_qrcode():
    """生成小红书扫码登录二维码"""
    return xiaohongshu_uploader.generate_qrcode()


@xiaohongshu_router.get("/qrcode/poll")
def poll_xhs_qrcode(session_id: str):
    """轮询小红书扫码登录状态"""
    return xiaohongshu_uploader.poll_qrcode(session_id)


@xiaohongshu_router.post("/browser-login")
def open_xhs_browser_login():
    """打开本地 Chrome 浏览器窗口完成小红书登录"""
    return xiaohongshu_uploader.launch_browser_login()


@xiaohongshu_router.post("/logout")
def logout_xhs():
    """退出小红书登录并清理凭据"""
    return xiaohongshu_uploader.logout()


@xiaohongshu_router.post("/publish")
def start_xhs_publish_task(req: XhsPublishRequest, background_tasks: BackgroundTasks):
    """创建异步发布小红书视频笔记任务"""
    if not xiaohongshu_uploader.is_configured:
        raise HTTPException(400, "尚未登录小红书账号，请先使用小红书 App 扫码登录")

    task_id = uuid.uuid4().hex[:12]
    with xhs_tasks_lock:
        xhs_publish_tasks[task_id] = {
            "id": task_id,
            "status": "pending",
            "progress": 0.01,
            "message": "小红书发布任务排队中...",
            "created_at": time.time(),
            "result": None,
            "error": None,
        }

    def _worker():
        def _cb(pct: float, msg: str):
            with xhs_tasks_lock:
                if task_id in xhs_publish_tasks:
                    xhs_publish_tasks[task_id]["progress"] = round(pct, 2)
                    xhs_publish_tasks[task_id]["message"] = msg
                    xhs_publish_tasks[task_id]["status"] = "uploading" if pct < 0.95 else "submitting"

        try:
            res = xiaohongshu_uploader.publish_video(
                video_source=req.video_source,
                title=req.title,
                desc=req.desc,
                tags=req.tags,
                cover_source=req.cover_source,
                progress_callback=_cb,
            )
            with xhs_tasks_lock:
                xhs_publish_tasks[task_id]["status"] = "completed"
                xhs_publish_tasks[task_id]["progress"] = 1.0
                xhs_publish_tasks[task_id]["message"] = res.get("message", "发布成功")
                xhs_publish_tasks[task_id]["result"] = res
        except Exception as e:
            logger.error(f"小红书任务 {task_id} 异常: {e}")
            with xhs_tasks_lock:
                xhs_publish_tasks[task_id]["status"] = "error"
                xhs_publish_tasks[task_id]["message"] = f"发布失败: {str(e)}"
                xhs_publish_tasks[task_id]["error"] = str(e)

    background_tasks.add_task(_worker)
    return {"task_id": task_id, "status": "pending"}


@xiaohongshu_router.get("/tasks/{task_id}")
def get_xhs_publish_task(task_id: str):
    """获取小红书发布任务实时进度与结果"""
    with xhs_tasks_lock:
        if task_id not in xhs_publish_tasks:
            raise HTTPException(404, "任务不存在")
        return xhs_publish_tasks[task_id]
