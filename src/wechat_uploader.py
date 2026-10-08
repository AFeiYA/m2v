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
import re
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

logger = logging.getLogger("wechat_uploader")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

RECOMMENDED_WECHAT_TAGS = ["AI音乐", "Suno", "音乐分享", "每日一歌", "治愈系"]


def sanitize_wechat_short_title(title: str, max_len: int = 16, min_len: int = 6) -> str:
    """
    微信视频号短标题清洗与格式化 (严格遵循微信视频号助手发布规则):
    1. 长度限制: 必须在 6 ~ 16 个字符之间
       - 超过 16 字: 禁用发表按钮并报红字“标题超过16字限制”
       - 低于 6 字: 报错“标题至少6个字”
    2. 符号限制: 官方仅支持 书名号《》、引号“”‘’、冒号:：、加号+、问号?？、百分号%、摄氏度℃
    3. 逗号替换: 逗号可用空格代替
    4. 其它符号剔除或转换:
       - '|', '-', '–', '—', '·', '_', '~', '～', '/', '\\', '#', '@', '*', '^', '$' -> 空格
       - '!', '！' -> 剔除
       - 括号 '【】', '[]', '（）', '()' -> 剔除
       - 句号与分号 -> 剔除
       - 连续空格合并为一个空格
    5. 长度补齐与截断:
       - 截断至最多 16 字符 (若切在英文词中，优先在词界截断)
       - 若清理后不足 6 字符，自动追加后缀 (如 " 音乐MV") 保证达到 6 字符
    """
    if not title:
        return "AI音乐MV精选"

    t = title.strip()
    t = t.replace("，", " ").replace(",", " ")
    t = re.sub(r"[\|\-–—·_~～/\\#@\*\^$]+", " ", t)
    t = re.sub(r"[\[\]【】\(\)（）\{\}]", " ", t)
    t = re.sub(r"[!！\.。;；、]", " ", t)

    # 严格白名单: 汉字、字母、数字、空格 以及 允许的符号: 《》〈〉“”‘’\"\'：:\+\?？%℃
    allowed = r"[^\u4e00-\u9fffa-zA-Z0-9\s《》〈〉“”‘’\"\'：:\+\?？%℃]"
    t = re.sub(allowed, "", t)
    t = re.sub(r"\s+", " ", t).strip()

    # 处理过长 (截断到 16 字符以内)
    if len(t) > max_len:
        t_trunc = t[:max_len].strip()
        if " " in t_trunc:
            word_trunc = t_trunc.rsplit(" ", 1)[0].strip()
            if len(word_trunc) >= min_len:
                t = word_trunc
            else:
                t = t_trunc
        else:
            t = t_trunc

    # 处理过短 (< 6 字符)
    if len(t) < min_len:
        for suffix in [" 音乐MV", " 歌曲精选", " AI音乐", " MV分享"]:
            candidate = (t + suffix).strip()
            if min_len <= len(candidate) <= max_len:
                t = candidate
                break
        else:
            if len(t) < min_len:
                t = (t + " 音乐MV分享")[:max_len].strip()
            if len(t) < min_len:
                t = "AI音乐MV精选"

    return t


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
        return bool(self.cookies.get("sessionid") or self.user_info.get("is_logged_in"))

    def get_account_status(self) -> dict:
        """检查当前视频号登录状态"""
        if self.cookies_path.exists() and (self.cookies.get("sessionid") or self.user_info.get("is_logged_in")):
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
        from playwright.sync_api import sync_playwright

        with self._qr_lock:
            if self._qr_session:
                self._qr_session["cancelled"] = True
                self._qr_session = None

        self._clean_locks()
        ready_event = threading.Event()
        result_box = {}
        session_id = uuid.uuid4().hex[:12]

        def _worker():
            try:
                with sync_playwright() as pw:
                    ctx = pw.chromium.launch_persistent_context(
                        user_data_dir=str(self.profile_dir.resolve()),
                        channel="chrome",
                        headless=True,
                        viewport={"width": 1280, "height": 800},
                        user_agent=DEFAULT_USER_AGENT,
                    )
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    page.goto("https://channels.weixin.qq.com/login.html", wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(3000)

                    current_url = page.url
                    if "login.html" not in current_url and "channels.weixin.qq.com" in current_url:
                        cookies_list = ctx.cookies()
                        cookies_dict = {c["name"]: c["value"] for c in cookies_list}
                        self._save_cookies(cookies_dict, {"is_logged_in": True, "uname": "微信视频号创作者"})
                        result_box["data"] = {
                            "success": True,
                            "is_logged_in": True,
                            "uname": "微信视频号创作者",
                            "message": "🎉 微信视频号助手已登录！",
                        }
                        ready_event.set()
                        ctx.close()
                        return

                    # 截取二维码区域
                    qr_wrap = page.locator('.login-qrcode-wrap, .qrcode-wrap, .qrcode-area').first
                    if qr_wrap.count() == 0:
                        qr_wrap = page.locator('canvas, img[src*="qrcode"]').first

                    if qr_wrap.count() == 0:
                        result_box["data"] = {"success": False, "message": "未能加载视频号登录二维码"}
                        ready_event.set()
                        ctx.close()
                        return

                    qr_bytes = qr_wrap.screenshot()
                    qr_data_url = "data:image/png;base64," + base64.b64encode(qr_bytes).decode("utf-8")

                    session_data = {
                        "id": session_id,
                        "status": "waiting",
                        "is_logged_in": False,
                        "uname": "",
                        "avatar": "",
                        "message": "请使用微信扫描屏幕二维码并确认登录视频号助手",
                        "cancelled": False,
                    }
                    with self._qr_lock:
                        self._qr_session = session_data

                    result_box["data"] = {
                        "success": True,
                        "session_id": session_id,
                        "qrcode_image": qr_data_url,
                        "message": "请使用微信扫描屏幕二维码并确认登录视频号助手",
                    }
                    ready_event.set()

                    # 在本线程内独立持续轮询，直到登录成功、失效或关闭
                    loop_start = time.time()
                    while time.time() - loop_start < 180:
                        if session_data.get("cancelled"):
                            break
                        page.wait_for_timeout(1500)
                        try:
                            cur_url = page.url
                            if "login.html" not in cur_url and "channels.weixin.qq.com" in cur_url:
                                page.wait_for_timeout(2000)
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
                                with self._qr_lock:
                                    session_data["status"] = "success"
                                    session_data["is_logged_in"] = True
                                    session_data["uname"] = uname
                                    session_data["message"] = f"🎉 微信视频号 [{uname}] 登录成功！"
                                break

                            refresh_btn = page.locator(':has-text("点击刷新"), .refresh-btn').first
                            if refresh_btn.count() > 0 and refresh_btn.is_visible():
                                with self._qr_lock:
                                    session_data["status"] = "expired"
                                    session_data["message"] = "二维码已失效，请重新刷新"
                                break
                        except Exception as e:
                            logger.debug(f"微信扫码监控异常: {e}")

                    ctx.close()
            except Exception as e:
                logger.error(f"微信扫码线程异常: {e}")
                if not ready_event.is_set():
                    result_box["data"] = {"success": False, "message": f"获取二维码失败: {str(e)}"}
                    ready_event.set()

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        ready_event.wait(timeout=25)
        return result_box.get("data", {"success": False, "message": "获取二维码超时，请重试"})

    def poll_qrcode(self, session_id: str) -> dict:
        """轮询微信视频号扫码状态 (纯内存读，彻底避免跨线程 greenlet 冲突)"""
        st = self.get_account_status()
        if st.get("is_logged_in"):
            return {
                "status": "success",
                "is_logged_in": True,
                "uname": st.get("uname", "微信视频号创作者"),
                "avatar": "",
                "message": f"🎉 微信视频号 [{st.get('uname')}] 登录成功！",
            }

        with self._qr_lock:
            if not self._qr_session or self._qr_session.get("id") != session_id:
                return {"status": "expired", "message": "扫码会话已过期，请重新获取二维码"}
            return {
                "status": self._qr_session.get("status", "waiting"),
                "is_logged_in": self._qr_session.get("is_logged_in", False),
                "uname": self._qr_session.get("uname", ""),
                "avatar": self._qr_session.get("avatar", ""),
                "message": self._qr_session.get("message", "等待微信扫码确认..."),
            }

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

        self._load_cookies()
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
                # 注入 Hook: 强制所有 Shadow Root 以 open 模式创建，使 Playwright 能够穿透定位微前端内部元素
                ctx.add_init_script("""(() => {
                    const orig = Element.prototype.attachShadow;
                    Element.prototype.attachShadow = function(init) {
                        return orig.call(this, { ...init, mode: 'open' });
                    };
                })();""")
                if self.cookies:
                    try:
                        ctx.add_cookies([
                            {"name": k, "value": v, "domain": ".weixin.qq.com", "path": "/"}
                            for k, v in self.cookies.items()
                        ])
                    except Exception:
                        pass

                page = ctx.pages[0] if ctx.pages else ctx.new_page()

                _notify(0.25, "正在打开视频号发表页面...")
                page.goto("https://channels.weixin.qq.com/platform/post/create", wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(3000)

                login_el = page.locator('.login-panel:visible, .qrcode-wrap:visible, :has-text("登录视频号助手"):visible')
                if "login.html" in page.url or login_el.count() > 0:
                    raise RuntimeError("微信视频号未登录或登录已失效，请先扫码登录")

                # 如果有弹出的指引或协议弹窗，自动点击“我知道了”
                notice_btn = page.locator('button:has-text("我知道了")').first
                if notice_btn.count() > 0 and notice_btn.is_visible():
                    try:
                        notice_btn.click()
                        page.wait_for_timeout(1000)
                    except Exception:
                        pass

                _notify(0.35, "正在等待视频上传控件就绪...")
                # 微信视频号基于无界微前端架构，需等待 input[type="file"] 注入 DOM
                file_input = page.locator('input[type="file"]').first
                try:
                    file_input.wait_for(state="attached", timeout=30000)
                except Exception:
                    inputs = page.locator('input[type="file"]').all()
                    if not inputs:
                        raise RuntimeError("未找到视频上传控件，页面加载超时或尚未完成登录")
                    file_input = inputs[0]

                _notify(0.40, "正在上传视频文件到微信视频号...")
                file_input.set_input_files(local_video_path)
                page.wait_for_timeout(2000)

                # 等待视频文件上传和转码初步完成
                _notify(0.55, "正在上传并处理视频文件...")
                upload_start = time.time()
                while time.time() - upload_start < 180:
                    cancel_btn = page.locator(':has-text("取消上传")').first
                    proc_tip = page.locator(':has-text("正在处理文件"), :has-text("上传中")').first
                    is_uploading = (cancel_btn.count() > 0 and cancel_btn.is_visible()) or (
                        proc_tip.count() > 0 and proc_tip.is_visible()
                    )
                    pub_btn = page.locator('button:has-text("发表"), .weui-desktop-btn_primary:has-text("发表")').first
                    is_btn_ready = False
                    if pub_btn.count() > 0:
                        btn_cls = pub_btn.get_attribute("class") or ""
                        is_btn_ready = "disabled" not in btn_cls and not pub_btn.is_disabled()

                    if is_btn_ready and not is_uploading and time.time() - upload_start > 5:
                        break
                    page.wait_for_timeout(2000)

                _notify(0.75, "正在填写动态文案与短标题...")
                # 微信视频号描述框为富文本编辑器：.input-editor 或 [data-placeholder*="描述"]
                desc_input = page.locator('.input-editor, [data-placeholder*="描述"], div[contenteditable="true"], div[contenteditable=""]').first
                if desc_input.count() > 0:
                    try:
                        desc_input.scroll_into_view_if_needed()
                        desc_input.click()
                        page.keyboard.press("Meta+A")
                        page.keyboard.press("Backspace")
                        page.keyboard.type(final_desc, delay=10)
                        page.wait_for_timeout(500)
                    except Exception as e:
                        logger.warning(f"输入视频号描述异常: {e}")

                # 填写短标题 (微信视频号硬性限制最多16个字)
                short_title_input = page.locator('input[placeholder*="短标题"], .form-item:has-text("短标题") input').first
                if short_title_input.count() > 0 and short_title_input.is_visible():
                    try:
                        short_title = sanitize_wechat_short_title(clean_title, max_len=16)
                        logger.info(f"微信视频号短标题清洗: '{clean_title}' -> '{short_title}' (字数: {len(short_title)})")
                        short_title_input.scroll_into_view_if_needed()
                        short_title_input.click()
                        short_title_input.fill("")
                        short_title_input.fill(short_title)
                        short_title_input.dispatch_event("input")
                        short_title_input.dispatch_event("change")
                        page.wait_for_timeout(500)
                    except Exception as e:
                        logger.warning(f"输入短标题异常: {e}")

                # 设置封面 (可选)
                if cover_source and Path(cover_source).exists():
                    try:
                        cover_edit_btn = page.locator('.form-item:has-text("封面"), :has-text("封面预览")').locator('button:has-text("编辑"), :has-text("编辑"), :has-text("选择封面")').first
                        if cover_edit_btn.count() > 0 and cover_edit_btn.is_visible():
                            _notify(0.85, "正在设置视频封面...")
                            cover_edit_btn.click()
                            page.wait_for_timeout(1000)
                            cover_file_input = page.locator('input[type="file"][accept*="image"]').first
                            if cover_file_input.count() > 0:
                                cover_file_input.set_input_files(cover_source)
                                page.wait_for_timeout(1500)
                                confirm_btn = page.locator('button:has-text("确定"), button:has-text("完成")').first
                                if confirm_btn.count() > 0 and confirm_btn.is_visible():
                                    confirm_btn.click()
                                    page.wait_for_timeout(1000)
                    except Exception as e:
                        logger.warning(f"设置视频号封面帧失败，保留默认封面: {e}")

                _notify(0.92, "正在提交发表到微信视频号...")
                publish_btn = page.locator('button:has-text("发表"), .weui-desktop-btn_primary:has-text("发表")').first
                if publish_btn.count() == 0:
                    raise RuntimeError("未找到视频号【发表】按钮")

                # 等待发表按钮变为可点击状态 (防止视频转码未完成或正在校验)
                for _ in range(15):
                    btn_cls = publish_btn.get_attribute("class") or ""
                    if not publish_btn.is_disabled() and "disabled" not in btn_cls:
                        break
                    page.wait_for_timeout(1000)

                publish_btn.scroll_into_view_if_needed()
                publish_btn.click()
                page.wait_for_timeout(2500)

                # 严密确认发布结果 (支持自动确认二次弹窗与权限校验)
                _notify(0.96, "正在确认发布结果...")
                publish_ok = False
                confirm_start = time.time()
                while time.time() - confirm_start < 35:
                    # 1. 检查是否有弹窗/模态框出现
                    dialogs = page.locator('.weui-desktop-dialog:visible, .weui-desktop-modal:visible, [role="dialog"]:visible').all()
                    for dlg in dialogs:
                        dlg_text = dlg.inner_text().strip()
                        if not dlg_text:
                            continue

                        # 权限拦截 / 管理员拦截
                        if "你还不能发表视频" in dlg_text or ("不是视频号" in dlg_text and "管理员" in dlg_text):
                            raise RuntimeError("微信视频号权限不足: 当前微信号不是视频号管理员或运营者，请在视频号助手添加管理权限后继续发表")
                        if "管理员本人验证" in dlg_text or "需管理员扫码验证" in dlg_text:
                            raise RuntimeError("微信视频号触发安全风控: 需要管理员本人在手机微信端扫码验证后方可发表")
                        if "实名信息核验" in dlg_text or "实名认证" in dlg_text:
                            raise RuntimeError("微信视频号提示: 需先完成微信实名信息核验方可发表视频")

                        # 成功弹窗
                        if any(k in dlg_text for k in ["发表成功", "动态已发表", "已发表", "审核中", "已提交"]):
                            publish_ok = True
                            break

                        # 二次声明 / 注意事项 / 协议弹窗 -> 自动勾选并确认
                        if any(k in dlg_text for k in ["注意", "声明", "原创", "协议", "确认发表", "将此次编辑保留"]):
                            chk = dlg.locator('input[type="checkbox"]:not(:checked), .weui-desktop-form__checkbox:not([class*="checked"])').first
                            if chk.count() > 0:
                                try:
                                    chk.click()
                                    page.wait_for_timeout(500)
                                except Exception:
                                    pass
                            confirm_btn = dlg.locator('button:has-text("同意"), button:has-text("确定"), button:has-text("确认"), button:has-text("我知道了"), button:has-text("继续发表"), button:has-text("发表")').first
                            if confirm_btn.count() > 0 and confirm_btn.is_visible():
                                logger.info("自动确认视频号弹窗: %s", dlg_text[:60].replace("\n", " "))
                                confirm_btn.click()
                                page.wait_for_timeout(2000)

                    if publish_ok:
                        break

                    # 2. 检查页面 URL 跳转
                    cur = page.url
                    if "create" not in cur or "/post/list" in cur:
                        publish_ok = True
                        break

                    # 3. 检查全局成功提示
                    if page.locator(':has-text("发表成功"), :has-text("动态已发表"), :has-text("审核中"), :has-text("内容已提交"), :has-text("提交成功")').count() > 0:
                        publish_ok = True
                        break

                    # 4. 检查表单错误提示
                    err_box = page.locator('.error-title:visible, .weui-desktop-form__extra-error:visible, .weui-desktop-tooltip_error:visible, [class*="error-message"]:visible, [class*="error-title"]:visible').first
                    if err_box.count() > 0:
                        err_msg = err_box.inner_text().strip()
                        if err_msg:
                            raise RuntimeError(f"视频号平台提示: {err_msg}")

                    page.wait_for_timeout(1500)

                if not publish_ok:
                    # 截图保留案发现场
                    try:
                        err_shot = self.profile_dir.parent / "temp" / f"wechat_err_{int(time.time())}.png"
                        err_shot.parent.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(err_shot))
                    except Exception:
                        pass

                    # 提取当前可见的提示或弹窗文本
                    active_dialog = page.locator('.weui-desktop-dialog:visible, .weui-desktop-modal:visible, [role="dialog"]:visible').first
                    if active_dialog.count() > 0:
                        d_text = active_dialog.inner_text().strip().replace("\n", " ")
                        if d_text:
                            raise RuntimeError(f"视频号发表弹窗提示: {d_text}")

                    err_box = page.locator('.error-title:visible, .weui-desktop-form__extra-error:visible, .weui-desktop-tooltip_error:visible, [class*="error-message"]:visible, [class*="error-title"]:visible').first
                    if err_box.count() > 0:
                        err_msg = err_box.inner_text().strip()
                        if err_msg:
                            raise RuntimeError(f"视频号发表未通过: {err_msg}")
                    raise RuntimeError("视频号发表未在规定时间内确认成功（页面仍停留在编辑页），未检测到发布完成")

                # 二次真实检查：进入发表记录列表验证最新状态
                _notify(0.99, "正在查询视频号发表记录真实审核状态...")
                post_status = "审核中"
                try:
                    page.goto("https://channels.weixin.qq.com/platform/post/list", wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(2500)
                    first_post = page.locator('.post-item, .weui-desktop-table tr, [class*="post-card"]').first
                    if first_post.count() > 0:
                        first_text = first_post.inner_text()
                        if "已发表" in first_text:
                            post_status = "已发表"
                        elif "审核中" in first_text or "处理中" in first_text:
                            post_status = "审核中"
                except Exception as e:
                    logger.debug(f"二次获取视频号列表状态跳过: {e}")

                _notify(1.0, f"🎉 微信视频号发布成功！当前状态: {post_status}，标题: {clean_title}")
                return {
                    "success": True,
                    "platform": "wechat",
                    "title": clean_title,
                    "status": post_status,
                    "message": f"视频已成功提交至微信视频号！当前状态为【{post_status}】",
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
def get_wx_status(sid: str = Depends(resolve_session_id)):
    """获取微信视频号登录状态"""
    uploader = get_uploader_for_session("wechat", sid)
    return uploader.get_account_status()


@wechat_router.get("/qrcode")
def get_wx_qrcode(sid: str = Depends(resolve_session_id)):
    """生成微信视频号扫码二维码"""
    uploader = get_uploader_for_session("wechat", sid)
    return uploader.generate_qrcode()


@wechat_router.get("/qrcode/poll")
def poll_wx_qrcode(session_id: str, sid: str = Depends(resolve_session_id)):
    """轮询微信视频号扫码状态"""
    uploader = get_uploader_for_session("wechat", sid)
    return uploader.poll_qrcode(session_id)


@wechat_router.post("/browser-login")
def open_wx_browser_login(sid: str = Depends(resolve_session_id)):
    """打开本地 Chrome 浏览器窗口完成微信视频号登录"""
    uploader = get_uploader_for_session("wechat", sid)
    return uploader.launch_browser_login()


@wechat_router.post("/logout")
def logout_wx(sid: str = Depends(resolve_session_id)):
    """退出微信视频号登录"""
    uploader = get_uploader_for_session("wechat", sid)
    return uploader.logout()


@wechat_router.post("/publish")
def start_wx_publish_task(
    req: WeChatPublishRequest,
    background_tasks: BackgroundTasks,
    sid: str = Depends(resolve_session_id),
):
    """创建异步发布微信视频号任务"""
    uploader = get_uploader_for_session("wechat", sid)
    if not uploader.is_configured:
        raise HTTPException(400, "尚未登录微信视频号，请先扫码登录")

    if not acquire_publish_lock(sid, "wechat", video_source=req.video_source):
        raise HTTPException(409, "微信视频号已有任务正在发布中，请勿重复提交")

    task_id = uuid.uuid4().hex[:12]
    with wx_tasks_lock:
        wx_publish_tasks[task_id] = {
            "id": task_id,
            "session_id": sid,
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

            with wx_tasks_lock:
                wx_publish_tasks[task_id]["progress"] = 1.0
                wx_publish_tasks[task_id]["result"] = res
                if is_failed:
                    wx_publish_tasks[task_id]["status"] = "error"
                    wx_publish_tasks[task_id]["message"] = res.get("message", "发布失败")
                    wx_publish_tasks[task_id]["error"] = res.get("message", "平台返回失败")
                elif is_review:
                    wx_publish_tasks[task_id]["status"] = "under_review"
                    wx_publish_tasks[task_id]["message"] = res.get("message", "提交成功，正在审核中")
                else:
                    wx_publish_tasks[task_id]["status"] = "completed"
                    wx_publish_tasks[task_id]["message"] = res.get("message", "发布成功")

        except Exception as e:
            logger.error(f"微信视频号任务 {task_id} 异常: {e}")
            with wx_tasks_lock:
                wx_publish_tasks[task_id]["status"] = "error"
                wx_publish_tasks[task_id]["message"] = f"发布失败: {str(e)}"
                wx_publish_tasks[task_id]["error"] = str(e)
        finally:
            release_publish_lock(sid, "wechat")

    background_tasks.add_task(_worker)
    return {"task_id": task_id, "status": "pending"}


@wechat_router.get("/tasks/{task_id}")
def get_wx_publish_task(task_id: str, sid: str = Depends(resolve_session_id)):
    """获取微信视频号发布任务进度 (防越权访问)"""
    with wx_tasks_lock:
        if task_id not in wx_publish_tasks:
            raise HTTPException(404, "任务不存在")
        task = wx_publish_tasks[task_id]
        task_owner = task.get("session_id")
        if task_owner and task_owner != sid and sid != "default":
            raise HTTPException(404, "任务不存在或无权访问")
        safe_copy = dict(task)
        safe_copy.pop("session_id", None)
        return safe_copy
