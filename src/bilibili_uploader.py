"""
Bilibili 视频一键发布与扫码鉴权服务模块
采用 requests 实现（已内置于 requirements.txt，零新加外部依赖）。
支持 macOS/Linux IPv4 优先解析，防止 IPv6 握手超时。

功能：
1. 扫码登录 (生成二维码、轮询状态、本地持久化 Cookie)
2. 账号状态检查与登出 (获取 UP 主头像、昵称、MID)
3. 封面图上传 (支持网络直链或本地文件)
4. 视频分片流式上传 (UPOS 协议)
5. 稿件信息提交 (原创投稿、标题、简介、标签、分区)
"""
from __future__ import annotations

import base64
import json
import logging
import math
import os
import shutil
import socket
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional, Union
from urllib.parse import parse_qs, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 优先解析 IPv4，避免在特定 macOS 网络下 IPv6 握手挂起
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_first_getaddrinfo(*args, **kwargs):
    responses = _orig_getaddrinfo(*args, **kwargs)
    ipv4 = [r for r in responses if r[0] == socket.AF_INET]
    return ipv4 or responses


socket.getaddrinfo = _ipv4_first_getaddrinfo

logger = logging.getLogger("bilibili_uploader")

# 常用投稿分区列表
POPULAR_TIDS = [
    {"id": 28, "name": "音乐 · 原创音乐 (推荐)"},
    {"id": 31, "name": "音乐 · 音乐综合 / 翻唱"},
    {"id": 278, "name": "科技 · AI音乐 / 人工智能"},
    {"id": 130, "name": "音乐 · 音乐现场 / 官方MV"},
    {"id": 21, "name": "动画 · MAD·AMV"},
    {"id": 138, "name": "生活 · 搞笑 / 综合日常"},
]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class BilibiliUploader:
    """管理 B 站账号认证与视频投稿上传流程"""

    def __init__(self, cookies_path: Optional[Union[str, Path]] = None):
        if cookies_path:
            self.cookies_path = Path(cookies_path)
        else:
            root = Path(__file__).resolve().parent.parent
            self.cookies_path = root / "work" / "bilibili_cookies.json"

        self.cookies_path.parent.mkdir(parents=True, exist_ok=True)
        self.cookies: dict[str, str] = {}
        self.user_info: dict = {}
        self.session = self._create_session()
        self._load_cookies()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
        return session

    def _load_cookies(self):
        """从本地文件或环境变量加载 Cookies"""
        self.cookies = {}
        if self.cookies_path.exists():
            try:
                data = json.loads(self.cookies_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.cookies = data.get("cookies", {})
                    self.user_info = data.get("user", {})
            except Exception as e:
                logger.warning(f"读取 B 站 cookies 失败: {e}")

        # 环境变量降级
        if not self.cookies.get("SESSDATA"):
            sessdata = os.getenv("BILIBILI_SESSDATA", "").strip()
            bili_jct = os.getenv("BILIBILI_BILI_JCT", "").strip()
            mid = os.getenv("BILIBILI_DEDEUSERID", "").strip()
            if sessdata and bili_jct:
                self.cookies = {
                    "SESSDATA": sessdata,
                    "bili_jct": bili_jct,
                    "DedeUserID": mid,
                }

        self._sync_session_cookies()

    def _sync_session_cookies(self):
        self.session.cookies.clear()
        for k, v in self.cookies.items():
            self.session.cookies.set(k, v, domain=".bilibili.com")

    def _save_cookies(self, cookies: dict[str, str], user_info: Optional[dict] = None):
        """持久化 Cookies 到本地文件"""
        self.cookies = cookies
        if user_info is not None:
            self.user_info = user_info
        data = {
            "cookies": self.cookies,
            "user": self.user_info,
            "updated_at": int(time.time()),
        }
        self.cookies_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._sync_session_cookies()

    @property
    def is_configured(self) -> bool:
        return bool(self.cookies.get("SESSDATA") and self.cookies.get("bili_jct"))

    @property
    def csrf(self) -> str:
        return self.cookies.get("bili_jct", "")

    def _get_headers(self, referer: str = "https://www.bilibili.com/") -> dict[str, str]:
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": referer,
            "Accept": "application/json, text/plain, */*",
        }
        cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if cookie_str:
            headers["Cookie"] = cookie_str
        return headers

    def get_account_status(self) -> dict:
        """检查当前登录状态并获取用户信息"""
        self._load_cookies()
        if not self.is_configured:
            return {"is_logged_in": False, "is_login": False, "uname": "", "message": "未登录 B 站账号"}

        try:
            r = self.session.get(
                "https://api.bilibili.com/x/web-interface/nav",
                headers=self._get_headers("https://member.bilibili.com/"),
                timeout=8,
            )
            data = r.json()
            if data.get("code") == 0 and data.get("data", {}).get("isLogin"):
                d = data["data"]
                user = {
                    "is_logged_in": True,
                    "is_login": True,
                    "uname": d.get("uname", ""),
                    "mid": d.get("mid", 0),
                    "face": d.get("face", ""),
                    "level": d.get("level_info", {}).get("current_level", 0),
                    "vip_type": d.get("vipType", 0),
                }
                self.user_info = user
                self._save_cookies(self.cookies, user)
                return user
            else:
                return {
                    "is_logged_in": False,
                    "is_login": False,
                    "uname": "",
                    "message": data.get("message", "登录凭证已失效"),
                }
        except Exception as e:
            logger.error(f"检查 B 站登录状态异常: {e}")
            if self.user_info.get("is_logged_in") and self.cookies.get("SESSDATA"):
                return self.user_info
            return {"is_logged_in": False, "is_login": False, "uname": "", "message": str(e)}

    def logout(self) -> dict:
        """登出并清理本地持久化信息"""
        self.cookies = {}
        self.user_info = {}
        self._sync_session_cookies()
        if self.cookies_path.exists():
            try:
                self.cookies_path.unlink()
            except Exception as e:
                logger.warning(f"删除 cookies 文件失败: {e}")
        return {"success": True, "message": "已成功退出 B 站登录"}

    def generate_qrcode(self) -> dict:
        """生成 B 站手机客户端扫码登录二维码"""
        try:
            r = self.session.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=8,
            )
            res = r.json()
            if res.get("code") == 0:
                d = res["data"]
                return {
                    "success": True,
                    "url": d["url"],
                    "qrcode_key": d["qrcode_key"],
                }
            return {"success": False, "message": res.get("message", "生成二维码失败")}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def poll_qrcode(self, qrcode_key: str) -> dict:
        """轮询扫码登录状态"""
        try:
            r = self.session.get(
                f"https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key={qrcode_key}",
                headers={"User-Agent": DEFAULT_USER_AGENT},
                timeout=8,
            )
            res = r.json()
            data = res.get("data", {})
            code = data.get("code", -1)

            if code == 0:
                extracted_cookies = {}
                for k, v in r.cookies.items():
                    extracted_cookies[k] = v

                redirect_url = data.get("url", "")
                if redirect_url:
                    query = parse_qs(urlparse(redirect_url).query)
                    for qk in ["bili_jct", "DedeUserID", "DedeUserID__ckMd5", "SESSDATA"]:
                        if qk in query and qk not in extracted_cookies:
                            extracted_cookies[qk] = query[qk][0]

                if not extracted_cookies.get("SESSDATA"):
                    extracted_cookies.update(self.cookies)

                self.cookies = extracted_cookies
                self._save_cookies(self.cookies)

                status = self.get_account_status()

                # 本地单机开发模式下同步至全局默认配置，避免丢失
                try:
                    from src.session_manager import is_default_session_allowed, _WORK_DIR
                    if (
                        is_default_session_allowed()
                        and self.cookies_path != (_WORK_DIR / "bilibili_cookies.json")
                        and self.cookies_path.parent.name.startswith("m2v_s_")
                    ):
                        shutil.copy2(self.cookies_path, _WORK_DIR / "bilibili_cookies.json")

                except Exception:
                    pass
                return {
                    "status": "success",
                    "code": 0,
                    "is_login": True,
                    "is_logged_in": True,
                    "message": "登录成功！",
                    "user": status,
                }
            elif code == 86101:
                return {"status": "waiting", "code": 86101, "is_login": False, "is_logged_in": False, "message": "等待手机扫码"}
            elif code == 86090:
                return {"status": "scanned", "code": 86090, "is_login": False, "is_logged_in": False, "message": "已扫码，请在手机上确认"}
            elif code == 86038:
                return {"status": "expired", "code": 86038, "is_login": False, "is_logged_in": False, "message": "二维码已失效，请刷新"}
            else:
                return {
                    "status": "error",
                    "code": code,
                    "is_login": False,
                    "is_logged_in": False,
                    "message": data.get("message", res.get("message", "登录失败")),
                }
        except Exception as e:
            return {"status": "error", "code": -1, "is_login": False, "is_logged_in": False, "message": str(e)}

    def upload_cover(self, cover_source: str) -> str:
        """上传封面图片到 B 站图床"""
        if not self.is_configured:
            raise RuntimeError("未登录 B 站账号，无法上传封面")

        img_bytes: bytes
        if cover_source.startswith("http://") or cover_source.startswith("https://"):
            r = requests.get(cover_source, timeout=15)
            r.raise_for_status()
            img_bytes = r.content
        elif cover_source.startswith("data:image"):
            b64_data = cover_source.split(",", 1)[-1]
            img_bytes = base64.b64decode(b64_data)
        elif os.path.exists(cover_source):
            with open(cover_source, "rb") as f:
                img_bytes = f.read()
        else:
            raise ValueError(f"无效的封面源: {cover_source}")

        b64_str = base64.b64encode(img_bytes).decode("ascii")
        data_uri = f"data:image/jpeg;base64,{b64_str}"

        headers = self._get_headers("https://member.bilibili.com/platform/upload/video/frame")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        r = self.session.post(
            "https://member.bilibili.com/x/vu/web/cover/up",
            data={"cover": data_uri, "csrf": self.csrf},
            headers=headers,
            timeout=20,
        )
        res = r.json()
        if res.get("code") == 0:
            return res["data"]["url"]
        raise RuntimeError(f"封面上传失败: {res.get('message', res)}")

    def upload_video_file(
        self,
        file_path: Union[str, Path],
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> str:
        """分片上传视频文件到 B 站 UPOS 服务器"""
        if not self.is_configured:
            raise RuntimeError("未登录 B 站账号，无法上传视频")

        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"找不到视频文件: {file_path}")

        file_size = path.stat().st_size
        file_name = path.name

        def _notify(pct: float, msg: str):
            if progress_callback:
                progress_callback(pct, msg)

        _notify(0.05, "正在协商 B 站上传线路...")

        preupload_info = None
        cdns = ["bda2", "ws", "kodo", "cos"]
        headers = self._get_headers("https://member.bilibili.com/platform/upload/video/frame")

        for cdn in cdns:
            try:
                params = {
                    "os": "upos",
                    "upcdn": cdn,
                    "name": file_name,
                    "size": file_size,
                    "r": "upos",
                    "profile": "ugcupos/bup",
                    "ssl": "0",
                    "version": "2.14.0",
                    "build": "2140000",
                }
                r = self.session.get("https://member.bilibili.com/preupload", params=params, headers=headers, timeout=12)
                j = r.json()
                if j.get("OK") == 1 or "upos_uri" in j:
                    preupload_info = j
                    break
            except Exception as e:
                logger.warning(f"尝试线路 {cdn} 失败: {e}")

        if not preupload_info:
            raise RuntimeError("获取 B 站视频上传线路失败，请检查登录凭据是否失效")

        upos_uri = preupload_info["upos_uri"]
        endpoint = preupload_info["endpoint"]
        auth = preupload_info["auth"]
        biz_id = preupload_info.get("biz_id", 0)
        chunk_size = preupload_info.get("chunk_size", 4 * 1024 * 1024)

        upos_path = upos_uri.replace("upos://", "")
        upos_headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "X-Upos-Auth": auth,
            "Referer": "https://member.bilibili.com/",
        }

        # 2. 初始化分片上传会话
        _notify(0.12, "正在初始化分片上传会话...")
        init_url = f"https:{endpoint}/{upos_path}?uploads&output=json"
        r = self.session.post(init_url, headers=upos_headers, timeout=15)
        init_json = r.json()
        upload_id = init_json.get("upload_id")
        if not upload_id:
            raise RuntimeError(f"初始化分片失败: {r.text}")

        # 3. 循环分片上传
        total_chunks = math.ceil(file_size / chunk_size)
        parts = []

        with open(path, "rb") as f:
            for chunk_idx in range(total_chunks):
                chunk_data = f.read(chunk_size)
                if not chunk_data:
                    break
                part_num = chunk_idx + 1
                start_byte = chunk_idx * chunk_size
                end_byte = start_byte + len(chunk_data)

                pct = 0.15 + (chunk_idx / total_chunks) * 0.75
                _notify(pct, f"正在分片上传中 ({part_num}/{total_chunks})...")

                put_url = (
                    f"https:{endpoint}/{upos_path}?"
                    f"partNumber={part_num}&uploadId={upload_id}&chunk={chunk_idx}&chunks={total_chunks}&"
                    f"size={len(chunk_data)}&start={start_byte}&end={end_byte}&total={file_size}"
                )

                success = False
                for retry in range(4):
                    try:
                        res = self.session.put(put_url, data=chunk_data, headers=upos_headers, timeout=60)
                        if res.status_code == 200:
                            success = True
                            break
                    except Exception as err:
                        logger.warning(f"分片 {part_num} 上传重试 {retry+1}/4: {err}")
                        time.sleep(1 + retry)

                if not success:
                    raise RuntimeError(f"分片 {part_num} 上传多次重试失败，已中止")

                parts.append({"partNumber": part_num, "eTag": "etag"})

        # 4. 通知完成合并
        _notify(0.92, "正在通知 B 站合并视频分片...")
        complete_url = (
            f"https:{endpoint}/{upos_path}?"
            f"output=json&name={file_name}&profile=ugcupos/bup&uploadId={upload_id}&biz_id={biz_id}"
        )
        r = self.session.post(complete_url, json={"parts": parts}, headers=upos_headers, timeout=25)
        if r.status_code != 200:
            raise RuntimeError(f"合并视频分片失败: {r.text}")

        _notify(0.95, "分片合并成功！准备提交稿件...")
        # 等待 1.5 秒让 B 站存储节点完成合并索引
        time.sleep(1.5)
        # 提取文件名主体（例如 n261006a23inzdmbisgp4g21gk6vxyfq，去除协议和目录前缀）
        bili_filename = upos_uri.split("/")[-1].split(".")[0]
        return bili_filename

    def submit_archive(
        self,
        filename: str,
        title: str,
        desc: str = "",
        tags: Optional[list[str]] = None,
        tid: int = 28,
        cover_url: str = "",
        dynamic: str = "",
    ) -> dict:
        """提交稿件信息"""
        if not self.is_configured:
            raise RuntimeError("未登录 B 站账号，无法提交稿件")

        tags = tags or ["Suno", "AI音乐", "音乐MV", "原创音乐", "音乐日记"]
        tag_str = ",".join([t.strip() for t in tags if t.strip()])[:200]

        payload = {
            "copyright": 1,
            "source": "",
            "title": title.strip()[:80],
            "tid": tid,
            "tag": tag_str,
            "no_reprint": 1,
            "desc": desc.strip()[:2000],
            "cover": cover_url,
            "mission_id": 0,
            "order_id": 0,
            "videos": [{"filename": filename, "title": title.strip()[:80], "desc": ""}],
            "dtime": 0,
            "open_elec": 1,
            "dynamic": dynamic,
            "subtitle": {"lan": "", "open": 0},
            "csrf": self.csrf,
        }

        headers = self._get_headers("https://member.bilibili.com/platform/upload/video/frame")
        headers["Content-Type"] = "application/json; charset=utf-8"

        for retry in range(3):
            r = self.session.post(
                f"https://member.bilibili.com/x/vu/web/add/v3?csrf={self.csrf}",
                json=payload,
                headers=headers,
                timeout=25,
            )
            data = r.json()
            if data.get("code") == 0:
                res_data = data.get("data", {})
                bvid = res_data.get("bvid", "")
                aid = res_data.get("aid", 0)
                return {
                    "success": True,
                    "bvid": bvid,
                    "aid": aid,
                    "video_url": f"https://www.bilibili.com/video/{bvid}" if bvid else "",
                    "message": "稿件提交成功，正在审核中！",
                }
            msg = data.get("message", "")
            if retry < 2 and ("上传过程出现问题" in msg or "稍后再试" in msg or "未就绪" in msg):
                logger.info(f"B站稿件提交稍候重试 ({retry+1}/3): {msg}")
                time.sleep(2.5)
                continue
            raise RuntimeError(f"稿件提交失败: {data.get('message', data)}")

    def publish_video(
        self,
        video_source: str,
        title: str,
        desc: str = "",
        tags: Optional[list[str]] = None,
        tid: int = 28,
        cover_source: str = "",
        dynamic: str = "",
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict:
        """一键发布高层流程 (支持本地文件或远程 MP4 URL)"""
        def _notify(pct: float, msg: str):
            if progress_callback:
                progress_callback(pct, msg)

        temp_video_file = None
        temp_cover_file = None
        local_video_path = video_source

        if video_source.startswith("http://") or video_source.startswith("https://"):
            _notify(0.02, "正在从云端下载 MP4 视频...")
            temp_dir = self.cookies_path.parent / "temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_video_file = temp_dir / f"bili_upload_{int(time.time()*1000)}.mp4"

            with requests.get(video_source, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(temp_video_file, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
            local_video_path = temp_video_file

        try:
            # 自动提取视频高清封面（第 1 秒画面）
            if not cover_source and local_video_path and Path(local_video_path).exists():
                try:
                    import subprocess
                    temp_dir = self.cookies_path.parent / "temp"
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    temp_cover_file = temp_dir / f"cover_{int(time.time()*1000)}.jpg"
                    subprocess.run(
                        [
                            "ffmpeg", "-y", "-ss", "00:00:01",
                            "-i", str(local_video_path),
                            "-vframes", "1", "-q:v", "2",
                            str(temp_cover_file)
                        ],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    if temp_cover_file.exists():
                        cover_source = str(temp_cover_file)
                except Exception as e:
                    logger.warning(f"自动提取视频封面帧失败: {e}")

            bili_cover_url = ""
            if cover_source:
                try:
                    _notify(0.08, "正在上传视频封面到 B 站...")
                    bili_cover_url = self.upload_cover(cover_source)
                except Exception as e:
                    logger.warning(f"封面上传未成功，继续发布视频: {e}")

            bili_filename = self.upload_video_file(local_video_path, progress_callback)

            _notify(0.98, "正在向 B 站提交稿件资料...")
            result = self.submit_archive(
                filename=bili_filename,
                title=title,
                desc=desc,
                tags=tags,
                tid=tid,
                cover_url=bili_cover_url,
                dynamic=dynamic,
            )
            _notify(1.0, f"🎉 稿件发布成功！BV号: {result.get('bvid')}")
            return result
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
bilibili_uploader = BilibiliUploader()


# ── FastAPI 路由与后台任务管理器 ────────────────────────
import threading
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from src.session_manager import (
    GLOBAL_PUBLISH_SEMAPHORE,
    acquire_publish_lock,
    get_uploader_for_session,
    release_publish_lock,
    resolve_session_id,
)

bilibili_router = APIRouter(prefix="/api/bilibili", tags=["Bilibili"])

publish_tasks: dict[str, dict] = {}
tasks_lock = threading.Lock()


class BiliPublishRequest(BaseModel):
    video_source: str
    title: str
    desc: str = ""
    tags: list[str] = Field(default_factory=lambda: ["Suno", "AI音乐", "音乐MV", "原创音乐", "音乐日记"])
    tid: int = 28
    cover_source: str = ""
    dynamic: str = ""


@bilibili_router.get("/status")
def get_bilibili_status(sid: str = Depends(resolve_session_id)):
    """获取当前 B 站登录状态"""
    uploader = get_uploader_for_session("bilibili", sid)
    return uploader.get_account_status()


@bilibili_router.get("/tids")
def get_popular_tids():
    """获取推荐投稿分区列表"""
    return {"tids": POPULAR_TIDS}


@bilibili_router.get("/qrcode")
def get_bilibili_qrcode(sid: str = Depends(resolve_session_id)):
    """生成扫码登录二维码数据"""
    uploader = get_uploader_for_session("bilibili", sid)
    return uploader.generate_qrcode()


@bilibili_router.get("/qrcode/poll")
def poll_bilibili_qrcode(key: str, sid: str = Depends(resolve_session_id)):
    """轮询扫码登录状态"""
    uploader = get_uploader_for_session("bilibili", sid)
    return uploader.poll_qrcode(key)


@bilibili_router.post("/logout")
def logout_bilibili(sid: str = Depends(resolve_session_id)):
    """退出登录并清理凭证"""
    uploader = get_uploader_for_session("bilibili", sid)
    return uploader.logout()


@bilibili_router.post("/publish")
def start_publish_task(
    req: BiliPublishRequest,
    background_tasks: BackgroundTasks,
    sid: str = Depends(resolve_session_id),
):
    """创建异步发布稿件任务"""
    uploader = get_uploader_for_session("bilibili", sid)
    if not uploader.is_configured:
        raise HTTPException(400, "尚未登录 B 站账号，请先使用哔哩哔哩 App 扫码登录")

    if not acquire_publish_lock(sid, "bilibili", video_source=req.video_source):
        raise HTTPException(409, "B站已有任务正在发布中，请勿重复提交")

    task_id = uuid.uuid4().hex[:12]
    with tasks_lock:
        publish_tasks[task_id] = {
            "id": task_id,
            "session_id": sid,
            "status": "pending",
            "progress": 0.01,
            "message": "发布任务排队中...",
            "created_at": time.time(),
            "result": None,
            "error": None,
        }

    def _worker():
        def _cb(pct: float, msg: str):
            with tasks_lock:
                if task_id in publish_tasks:
                    publish_tasks[task_id]["progress"] = round(pct, 2)
                    publish_tasks[task_id]["message"] = msg
                    publish_tasks[task_id]["status"] = "uploading" if pct < 0.95 else "submitting"

        try:
            with GLOBAL_PUBLISH_SEMAPHORE:
                res = uploader.publish_video(
                    video_source=req.video_source,
                    title=req.title,
                    desc=req.desc,
                    tags=req.tags,
                    tid=req.tid,
                    cover_source=req.cover_source,
                    dynamic=req.dynamic,
                    progress_callback=_cb,
                )
            res = res or {}
            is_failed = res.get("success") is False or res.get("status") == "error"
            is_review = (
                res.get("status") in ["under_review", "reviewing", "pending_review"]
                or res.get("is_review") is True
                or ("审核" in str(res.get("message", "")))
            )

            with tasks_lock:
                publish_tasks[task_id]["progress"] = 1.0
                publish_tasks[task_id]["result"] = res
                if is_failed:
                    publish_tasks[task_id]["status"] = "error"
                    publish_tasks[task_id]["message"] = res.get("message", "发布失败")
                    publish_tasks[task_id]["error"] = res.get("message", "平台返回失败")
                elif is_review:
                    publish_tasks[task_id]["status"] = "under_review"
                    publish_tasks[task_id]["message"] = res.get("message", "提交成功，正在审核中")
                else:
                    publish_tasks[task_id]["status"] = "completed"
                    publish_tasks[task_id]["message"] = f"发布成功！BV号: {res.get('bvid', '')}"

        except Exception as e:
            logger.error(f"B站任务 {task_id} 异常: {e}")
            with tasks_lock:
                publish_tasks[task_id]["status"] = "error"
                publish_tasks[task_id]["message"] = f"发布失败: {str(e)}"
                publish_tasks[task_id]["error"] = str(e)
        finally:
            release_publish_lock(sid, "bilibili")

    background_tasks.add_task(_worker)
    return {"task_id": task_id, "status": "pending"}


@bilibili_router.get("/tasks/{task_id}")
def get_publish_task(task_id: str, sid: str = Depends(resolve_session_id)):
    """获取发布任务实时进度与结果 (防越权访问)"""
    with tasks_lock:
        if task_id not in publish_tasks:
            raise HTTPException(404, "任务不存在")
        task = publish_tasks[task_id]
        task_owner = task.get("session_id")
        if task_owner and task_owner != sid and sid != "default":
            raise HTTPException(404, "任务不存在或无权访问")
        safe_copy = dict(task)
        safe_copy.pop("session_id", None)
        return safe_copy

