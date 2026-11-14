"""
Meta Business Suite (Instagram Reels + Facebook Reels) 本地自动化发布模块
基于 Playwright + macOS Chrome 持久化会话，一次上传可同步勾选发布至 Instagram 与 Facebook。

功能：
1. 浏览器辅助登录 (launch_browser_login): 弹出 Chrome 窗口登录 Meta Business Suite，持久化会话至 work/meta_profile
2. 登录状态检查 (get_account_status): 检查本地会话凭据
3. 视频同步发布 (publish_video): 在 Meta Business Suite 创建 Reel，上传 MP4、填写文案并发布
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Union

logger = logging.getLogger("meta_uploader")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
META_REEL_COMPOSER_URL = "https://business.facebook.com/latest/reels_composer"
META_HOME_URL = "https://business.facebook.com/"


def format_meta_caption(title: str, desc: str = "", tags: Optional[list[str]] = None) -> str:
    """组合 Instagram / Facebook Reels 文案与 #hashtag 标签"""
    parts = [p.strip() for p in (title, desc) if p and p.strip()]
    body = "\n\n".join(parts)
    if tags:
        hashtags = " ".join(
            f"#{t.strip().lstrip('#').replace(' ', '')}" for t in tags if t and t.strip()
        )
        if hashtags:
            body = f"{body}\n\n{hashtags}".strip()
    return body[:2200]


class MetaReelsUploader:
    """管理 Meta Business Suite (Instagram Reels & Facebook Reels) 本地会话与发布"""

    def __init__(
        self,
        profile_dir: Optional[Union[str, Path]] = None,
        cookies_path: Optional[Union[str, Path]] = None,
    ):
        root = Path(__file__).resolve().parent.parent
        self.profile_dir = Path(profile_dir) if profile_dir else root / "work" / "meta_profile"
        self.cookies_path = Path(cookies_path) if cookies_path else root / "work" / "meta_cookies.json"
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.cookies_path.parent.mkdir(parents=True, exist_ok=True)
        self.cookies: dict[str, str] = {}
        self.user_info: dict = {}
        self._load_cookies()

    def _load_cookies(self):
        self.cookies = {}
        self.user_info = {}
        if self.cookies_path.exists():
            try:
                data = json.loads(self.cookies_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.cookies = data.get("cookies", {})
                    self.user_info = data.get("user", {})
            except Exception as e:
                logger.warning(f"读取 Meta cookies 失败: {e}")

    def _save_cookies(self, cookies: dict, user_info: Optional[dict] = None):
        self.cookies = cookies
        if user_info:
            self.user_info = user_info
        payload = {
            "cookies": self.cookies,
            "user": self.user_info,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.cookies_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _clean_locks(self):
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lp = self.profile_dir / lock_name
            if lp.exists() or lp.is_symlink():
                try:
                    lp.unlink()
                except Exception:
                    pass

    def get_account_status(self) -> dict:
        """检查本地 Meta Business Suite 会话凭据是否存在"""
        self._load_cookies()
        has_session = any(k in self.cookies for k in ("c_user", "xs", "ds_user_id"))
        if has_session:
            return {
                "is_logged_in": True,
                "is_login": True,
                "uname": self.user_info.get("uname", "Meta Business (IG/FB)"),
                "message": "已保存 Meta Business Suite 本地会话",
            }
        return {
            "is_logged_in": False,
            "is_login": False,
            "uname": "",
            "message": "尚未登录 Meta Business Suite，请先运行授权登录",
        }

    def launch_browser_login(self, wait_seconds: int = 180) -> dict:
        """打开 Chrome 窗口供用户登录 Meta Business Suite 并持久化会话"""
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
                page.goto(META_HOME_URL, wait_until="domcontentloaded", timeout=30000)

                start_time = time.time()
                while time.time() - start_time < wait_seconds:
                    try:
                        if page.is_closed():
                            break
                        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                        has_session = any(k in cookies for k in ("c_user", "xs", "ds_user_id"))
                        if has_session and "loginpage" not in page.url:
                            self._save_cookies(cookies, {"uname": "Meta Business (IG/FB)"})
                            logger.info("Meta Business Suite 登录成功并已保存本地会话")
                            page.wait_for_timeout(2000)
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
        return {"success": True, "message": "已打开 Meta Business Chrome 登录窗口，请在浏览器中完成登录"}

    def publish_video(
        self,
        video_source: str,
        title: str,
        desc: str = "",
        tags: Optional[list[str]] = None,
        targets: Optional[list[str]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        headless: bool = False,
        dry_run: bool = False,
    ) -> dict:
        """在 Meta Business Suite 发布 Reel 至 Instagram / Facebook"""
        def _notify(pct: float, msg: str):
            if progress_callback:
                progress_callback(pct, msg)

        video_path = Path(video_source).expanduser().resolve()
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        target_list = [t.lower() for t in (targets or ["instagram", "facebook"])]
        caption = format_meta_caption(title, desc, tags)

        if dry_run:
            _notify(1.0, f"【演练通过】Meta Reels ({','.join(target_list)}) 就绪: {video_path.name}")
            return {
                "success": True,
                "dry_run": True,
                "platform": "meta",
                "targets": target_list,
                "title": title,
                "caption": caption,
                "message": f"【演练通过】Meta Reels 就绪 ({video_path.name})",
            }

        from playwright.sync_api import sync_playwright

        self._clean_locks()
        self._load_cookies()

        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir.resolve()),
                channel="chrome",
                headless=headless,
                viewport={"width": 1280, "height": 900},
                user_agent=DEFAULT_USER_AGENT,
            )
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                _notify(0.2, "正在打开 Meta Business Suite Reel 发布台...")
                page.goto(META_REEL_COMPOSER_URL, wait_until="domcontentloaded", timeout=35000)
                page.wait_for_timeout(4000)

                if "loginpage" in page.url or "login.php" in page.url:
                    raise RuntimeError("Meta Business Suite 未登录或会话已过期，请先运行登录向导")

                _notify(0.4, "正在上传视频文件到 Meta Business Suite...")
                file_input = page.locator('input[type="file"]').first
                file_input.set_input_files(str(video_path))
                page.wait_for_timeout(5000)

                _notify(0.6, "正在填写 Reels 文案与标签...")
                textbox = page.locator('[role="textbox"][contenteditable="true"]').first
                textbox.click()
                textbox.fill(caption)

                _notify(0.8, "正在推进发布步骤并提交...")
                for btn_label in ("Next", "下一步"):
                    nxt = page.locator(f'div[role="button"]:has-text("{btn_label}")').first
                    if nxt.count() > 0 and nxt.is_visible():
                        nxt.click()
                        page.wait_for_timeout(2000)

                for pub_label in ("Share", "Publish", "分享", "发布"):
                    pub = page.locator(f'div[role="button"]:has-text("{pub_label}")').last
                    if pub.count() > 0 and pub.is_visible():
                        pub.click()
                        break

                page.wait_for_timeout(5000)
                cookies = {c["name"]: c["value"] for c in ctx.cookies()}
                if cookies:
                    self._save_cookies(cookies, self.user_info or {"uname": "Meta Business (IG/FB)"})

                _notify(1.0, "🎉 Meta Reels (IG/FB) 发布已提交！")
                return {
                    "success": True,
                    "platform": "meta",
                    "targets": target_list,
                    "title": title,
                    "message": "Meta Reels 已成功提交发布！",
                }
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass


meta_uploader = MetaReelsUploader()
