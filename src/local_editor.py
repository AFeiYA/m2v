"""
本地时间轴编辑器 — 轻量 FastAPI 服务（无数据库）

用法:
    python -m src.local_editor
    python -m src.local_editor --dir E:/m2v/output --port 8765

功能:
    - 自动扫描目录内的 *_alignment.json 文件
    - 完整复刻 Web 编辑器 UI（波形图 + 行列表 + 字级时间轴）
    - 保存时自动备份 (.bak)，支持撤销/重做
    - 一键重新生成 .ass
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import threading
import uuid
import webbrowser
from pathlib import Path
from typing import Literal, Any

import uvicorn
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from src.storyboard_schema import (
    AlignmentProject,
    AlignmentResult,
    AlignedLine,
    MusicSection,
    ShotPlan,
    Take,
    WordTimestamp,
)
from src.subtitle import generate_ass
from src.config import PipelineConfig, SubtitleConfig
from src.utils import log
from src.task_store import TaskStore
from src.video_providers import get_comfyui_client

# ── 默认值 ────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR   = str(_PROJECT_ROOT / "output")
DEFAULT_HOST  = "127.0.0.1"
DEFAULT_PORT  = 8000
# ─────────────────────────────────────────────────────────

_alignment_write_lock = threading.Lock()
_plugin_export_lock = threading.Lock()

app = FastAPI(title="M2V 本地编辑器", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# ======================================================================
# API 数据模型 (Pydantic v2)
# ======================================================================

class SunoImportRequest(BaseModel):
    url: str = Field(..., description="Suno 歌曲分享链接")
    cookie: str | None = Field(default=None, description="可选 Suno 会话 Cookie")
    token: str | None = Field(default=None, description="可选 Suno Bearer Token")
    async_mode: bool = Field(default=True, description="是否以异步任务模式启动，避免网关超时")
    skip_separation: bool | None = Field(default=None, description="是否跳过人声分离 (None 则遵循配置文件)")
    use_gpu: bool | None = Field(default=None, description="是否启用 GPU 硬件加速 (None 则自动探测)")
    language: str | None = Field(default="auto", description="指定语言 (auto, en, zh, ja, ko)")




class RegenRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    audio_path: str | None = Field(default=None, description="音频路径")
    mode: Literal["ass", "video"] = Field(default="ass", description="生成模式")
    tag_type: Literal["k", "kf"] = Field(default="kf", description="卡拉OK标签类型")
    render_mode: Literal["apple", "tv"] = Field(default="apple", description="字幕渲染模式")


class RealignRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    line_indices: list[int] = Field(..., min_length=1, description="待重跑的行号列表")
    buffer: float = Field(default=2.0, ge=0.0, description="音频裁剪前后缓冲秒数")


def _get_scan_dir() -> Path:
    """获取扫描目录（从 app.state 中读取）"""
    return getattr(app.state, "scan_dir", Path(DEFAULT_DIR))


@app.get("/privacy/extension", response_class=HTMLResponse)
def extension_privacy():
    """Public privacy page usable in the Chrome Web Store listing."""
    return HTMLResponse((_PROJECT_ROOT / "chrome_extension" / "privacy.html").read_text(encoding="utf-8"))


def _validate_path(p: Path, must_exist: bool = True) -> Path:
    """校验路径在扫描目录内，防止任意文件读取"""
    scan_dir = _get_scan_dir()
    resolved = p.resolve()
    # 允许扫描目录本身及其父目录下的 input/ 目录
    allowed_roots = [scan_dir.resolve(), (scan_dir.parent / "input").resolve(), scan_dir.parent.resolve()]
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise HTTPException(403, f"路径越界: 仅允许访问项目目录内的文件")
    if must_exist and not resolved.exists():
        raise HTTPException(404, f"文件不存在: {resolved.name}")
    return resolved


# ======================================================================
# API
# ======================================================================

_suno_import_tasks: dict[str, dict[str, Any]] = {}


@app.post("/api/suno/import")
def import_suno_song(req: SunoImportRequest):
    """
    从 Suno / 网易云音乐 网址或 iframe 一键导入、自动分轨并完成词级时间轴对齐。
    默认启用异步任务模式 (async_mode=True)，彻底避免 Vercel/云端代理的 120 秒超时中断。
    """
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "请输入 Suno URL 或网易云歌曲链接/ID")

    scan_dir = _get_scan_dir()
    input_dir = scan_dir.parent / "input"
    output_dir = scan_dir

    is_netease = (
        "163.com" in url.lower()
        or "163cn.tv" in url.lower()
        or "<iframe" in url.lower()
        or "music.163" in url.lower()
        or (url.isdigit() and len(url) >= 5)
    )

    if not req.async_mode:
        try:
            if is_netease:
                from src.netease_fetch import auto_process_netease
                result = auto_process_netease(
                    url_or_id=url,
                    input_dir=input_dir,
                    output_dir=output_dir,
                    launch_editor=False,
                    skip_separation=req.skip_separation,
                    use_gpu=req.use_gpu,
                )
            else:
                from src.suno_fetch import auto_process_suno
                result = auto_process_suno(
                    url=url,
                    input_dir=input_dir,
                    output_dir=output_dir,
                    launch_editor=False,
                    cookie=req.cookie,
                    token=req.token,
                    skip_separation=req.skip_separation,
                    use_gpu=req.use_gpu,
                    language=req.language,
                )
            return result
        except Exception as e:
            log.error("歌曲导入失败: %s", e, exc_info=True)
            raise HTTPException(500, f"处理失败: {e}")

    task_id = f"netease_{uuid.uuid4().hex[:8]}" if is_netease else f"suno_{uuid.uuid4().hex[:8]}"
    _suno_import_tasks[task_id] = {
        "status": "pending",
        "progress": 5,
        "message": "任务已提交，准备解析网易云音乐歌曲..." if is_netease else "任务已提交，准备解析 Suno 歌曲...",
        "task_id": task_id,
        "result": None,
        "error": None,
    }

    def _worker():
        try:
            def _cb(prog: int, msg: str, extra: dict | None = None):
                if task_id in _suno_import_tasks:
                    _suno_import_tasks[task_id]["progress"] = prog
                    _suno_import_tasks[task_id]["message"] = msg
                    _suno_import_tasks[task_id]["status"] = "processing"
                    if extra:
                        _suno_import_tasks[task_id].update(extra)

            if is_netease:
                from src.netease_fetch import auto_process_netease
                res = auto_process_netease(
                    url_or_id=url,
                    input_dir=input_dir,
                    output_dir=output_dir,
                    launch_editor=False,
                    progress_callback=_cb,
                    skip_separation=req.skip_separation,
                    use_gpu=req.use_gpu,
                )
            else:
                from src.suno_fetch import auto_process_suno
                res = auto_process_suno(
                    url=url,
                    input_dir=input_dir,
                    output_dir=output_dir,
                    launch_editor=False,
                    cookie=req.cookie,
                    token=req.token,
                    progress_callback=_cb,
                    skip_separation=req.skip_separation,
                    use_gpu=req.use_gpu,
                    language=req.language,
                )
            _suno_import_tasks[task_id]["status"] = "done"
            _suno_import_tasks[task_id]["progress"] = 100
            _suno_import_tasks[task_id]["message"] = "全部处理完成！"
            _suno_import_tasks[task_id]["result"] = res
        except Exception as e:
            log.error("异步导入歌曲异常: %s", e, exc_info=True)
            _suno_import_tasks[task_id]["status"] = "error"
            _suno_import_tasks[task_id]["error"] = str(e)

    threading.Thread(target=_worker, daemon=True).start()
    return {
        "status": "pending",
        "task_id": task_id,
        "message": "网易云导入任务已提交..." if is_netease else "Suno 任务已提交...",
    }


@app.get("/api/suno/task_status")
def api_get_suno_task_status(task_id: str):
    """查询 Suno 异步导入进度与结果"""
    task = _suno_import_tasks.get(task_id)
    if not task:
        raise HTTPException(404, f"未找到任务: {task_id}")
    return task


@app.get("/api/gpu/status")
def api_get_gpu_status():
    """实时检测当前环境的 GPU 算力状态、型号与 ZeroGPU 配额健康度"""
    import torch
    from src.aligner import is_safe_cuda_available

    try:
        import spaces
        has_spaces = True
    except ImportError:
        spaces = None
        has_spaces = False

    device_type = "cpu"
    device_name = "CPU"
    gpu_available = False
    details = ""

    if has_spaces and hasattr(spaces, "GPU"):
        device_type = "zerogpu"
        device_name = "Hugging Face ZeroGPU (Dynamic A100)"
        gpu_available = True
        details = "云端动态共享 GPU 算力 (已配置 35s 轻量预占模式，节省 70% 配额并支持自动平滑回退 CPU)"
    elif is_safe_cuda_available():
        try:
            device_type = "cuda"
            device_name = torch.cuda.get_device_name(0)
            gpu_available = True
            mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            details = f"物理 CUDA 显卡 (显存: {mem:.1f} GB)"
        except Exception:
            device_type = "cpu"
            device_name = "CPU"
            gpu_available = False
            details = "物理 CUDA 设备初始化异常，回退至 CPU"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device_type = "mps"
        device_name = "Apple Silicon GPU (Metal MPS)"
        gpu_available = True
        details = "macOS 硬件级 Metal 加速 (本地 Demucs 分离约 15~20 秒)"
    else:
        device_type = "cpu"
        device_name = "CPU"
        gpu_available = False
        details = "当前无可用 GPU，使用多核 CPU 运算"

    return {
        "status": "ok",
        "has_spaces": has_spaces,
        "device_type": device_type,
        "device_name": device_name,
        "gpu_available": gpu_available,
        "details": details,
        "zerogpu_config": {
            "duration": 35,
            "fallback_to_cpu": True,
            "quota_refresh_cycle": "ZeroGPU 免费配额随时间平滑补充（通常每 1~2 小时刷新）",
            "tips": [
                "已将每次任务预占额度由 120s 优化为 35s，成功率提升 3 倍并节省 70% 配额",
                "若遇高峰期额度见底，系统会自动平滑降级至 CPU 运行，无需担心任务中断",
                "如需秒级极速响应且曲风伴奏简单，可随时在页面取消【分离伴奏】勾选"
            ]
        }
    }




@app.post("/api/plugin/export_audio")
async def plugin_export_audio(song_id: str = Form(...), title: str = Form("Suno_Track")):
    """Download the song's audio, including the existing MP4 fallback, without AI."""
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", song_id):
        raise HTTPException(400, "歌曲编号无效")
    scan_dir = _get_scan_dir()
    task_id = f"audio_{uuid.uuid4().hex}"
    _lyric_video_tasks[task_id] = {
        "task_id": task_id, "title": title, "status": "pending", "progress": 0,
        "phase": "audio", "message": "正在准备音频下载…", "result": None, "error": None,
    }

    def worker():
        import tempfile
        import subprocess
        from urllib.parse import quote
        from src.suno_fetch import download_song, _sanitize_filename
        from src.utils import get_ffmpeg_binary
        task = _lyric_video_tasks[task_id]
        try:
            task.update(status="running", progress=5, message="正在下载歌曲音频，直链不可用时从 MP4 提取音轨…")
            folder = scan_dir / "_plugin_audio" / task_id
            folder.mkdir(parents=True, exist_ok=True)
            filename = (_sanitize_filename(title) or "Suno_Track") + ".mp3"
            output = folder / filename
            route = "song" if re.fullmatch(r"[0-9a-fA-F-]{36}", song_id) else "s"
            with tempfile.TemporaryDirectory(prefix="source_", dir=folder) as tmp:
                source, _, _, _ = download_song(f"https://suno.com/{route}/{song_id}", Path(tmp), save_json=False)
                if source is None or not source.exists():
                    raise RuntimeError("未能获取可解码的歌曲音频或 MP4 音轨，请确认当前歌曲可访问。")
                with source.open("rb") as handle:
                    header = handle.read(4)
                mp3_header = header[:3] == b"ID3" or (
                    len(header) == 4 and header[0] == 255 and header[1] & 0xE0 == 0xE0
                    and header[1] & 6 == 2 and header[1] & 0x18 != 8
                )
                if mp3_header:
                    # download_song already encoded the MP4 audio to MP3.
                    # Preserve those bytes instead of adding another lossy encode.
                    task.update(progress=90, message="MP3 音频已提取，正在准备下载…")
                    shutil.copy2(source, output)
                else:
                    task.update(progress=75, message="正在将音轨转换为 MP3（不进行人声分离或歌词对齐）…")
                    result = subprocess.run(
                        [get_ffmpeg_binary(), "-y", "-i", str(source), "-map", "0:a:0",
                         "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(output)],
                        capture_output=True, text=True, timeout=180,
                    )
                    if result.returncode or not output.exists() or output.stat().st_size == 0:
                        raise RuntimeError(f"MP3 音轨转换失败: {result.stderr[-300:]}")
            task.update(result={
                "download_url": f"/api/asset_file?download=true&filename={quote(filename)}&path={encode_path(str(output.absolute()))}",
                "filename": filename,
            }, status="completed", progress=100, message="MP3 音频已就绪")
        except Exception as exc:
            log.exception("插件音频导出失败: %s", task_id)
            task.update(status="failed", error=str(exc), message=f"音频导出失败: {exc}")
    threading.Thread(target=worker, daemon=True).start()
    return {"status": "pending", "task_id": task_id}


@app.post("/api/plugin/export_video")
async def plugin_direct_export_video(
    audio_file: UploadFile = File(None),
    title: str = Form("Suno_Track"),
    lyrics: str = Form(""),
    prompt: str = Form(""),
    artist: str = Form("unknown"),
    song_id: str = Form(""),
    tags: str = Form(""),
    url: str = Form(""),
    is_public: bool = Form(True),
    aspect_ratio: str = Form("9:16"),
    template: str = Form("apple"),
    theme: str = Form("apple_white"),
    background_mode: str = Form("full_bleed"),
    cover_url: str = Form(""),
    section_name: str = Form(""),
    start_time: float = Form(0.0),
    duration_limit: float = Form(0.0),
    request_id: str = Form(""),
):
    """
    接收来自 Chrome 插件的一键动效短视频生成请求。
    暂存上传文件后立即返回任务编号；后台排队执行公开状态检查、
    音频准备、分离、歌词对齐和视频渲染，通过任务接口查询真实进度。
    """
    import subprocess
    from urllib.parse import quote
    from src.suno_fetch import (
        _sanitize_filename,
        _clean_lyrics,
        enrich_alignment_sections,
        fetch_song,
        download_song,
        SongNotPublishedError,
    )
    from src.main import process_one
    from src.config import PipelineConfig
    from src.utils import get_ffmpeg_binary
    from src.lyric_engine import export_lyric_video

    # 1. 严格检查公开状态 (Publish)
    if not is_public:
        raise HTTPException(
            status_code=400,
            detail="该曲目尚未公开 (Publish)，无法生成视频！\n💡 请在 Suno 歌曲右侧菜单（...）中点击【Publish】公开发布后再试。"
        )

    # Only stage request-owned uploads here. Network, inference and rendering
    # must run after returning the task ID, outside the ASGI event loop.
    import tempfile
    import os
    scan_dir = _get_scan_dir()
    if request_id:
        try:
            request_id = str(uuid.UUID(request_id))
        except ValueError:
            raise HTTPException(400, "Invalid request ID")
        task_id = f"lyric_{hashlib.sha256(request_id.encode()).hexdigest()}"
    else:
        task_id = f"lyric_{uuid.uuid4().hex}"
    fingerprint = hashlib.sha256(json.dumps(
        [song_id, url, title, section_name, start_time, duration_limit,
         aspect_ratio, template, theme, background_mode, lyrics, prompt, artist, cover_url],
        ensure_ascii=False).encode()).hexdigest()
    # Reserve before awaiting uploads so duplicate requests start one worker.
    with _lyric_video_tasks.lock:
        existing = _lyric_video_tasks.get(task_id)
        if existing:
            if existing.get("request_fingerprint") != fingerprint:
                raise HTTPException(409, "Request ID already belongs to a different video")
            return {"status": existing["status"], "task_id": task_id, "title": title}
        _lyric_video_tasks.cleanup()
        _lyric_video_tasks[task_id] = {
            "status": "pending", "phase": "queued", "progress": 0.0,
            "message": "Waiting in queue", "task_id": task_id,
            "title": title, "result": None, "error": None,
            "request_fingerprint": fingerprint,
        }
    staged_upload = None
    if audio_file is not None and audio_file.filename:
        staging_dir = scan_dir.parent / "work" / "plugin_uploads"
        staging_dir.mkdir(parents=True, exist_ok=True)
        fd, staging_path = tempfile.mkstemp(
            prefix="upload_", suffix=Path(audio_file.filename).suffix, dir=staging_dir,
        )
        staged_upload = Path(staging_path)
        try:
            with os.fdopen(fd, "wb") as destination:
                while chunk := await audio_file.read(1024 * 1024):
                    destination.write(chunk)
        except Exception:
            staged_upload.unlink(missing_ok=True)
            _lyric_video_tasks[task_id].update(status="failed", error="Audio upload failed")
            raise

    def _update(phase, progress, message):
        task = _lyric_video_tasks[task_id]
        task.update(phase=phase, progress=max(task["progress"], progress), message=message)

    def _worker():
        # Serialize plugin pipelines: model/GPU resources and song paths are
        # shared. Queued requests still return immediately and remain pollable.
        try:
            with _plugin_export_lock:
                _lyric_video_tasks[task_id]["status"] = "running"
                _update("fetching", 1, "正在获取歌曲信息…")
                artist_value, prompt_value, lyrics_value = artist, prompt, lyrics
                clean_title = _sanitize_filename(title) or f"suno_{uuid.uuid4().hex[:8]}"
                fetched_song = None
                target_url = url or (f"https://suno.com/song/{song_id}" if song_id else "")

                if target_url:
                    try:
                        fetched_song = fetch_song(target_url, require_public=True)
                        if fetched_song:
                            clean_title = _sanitize_filename(fetched_song.title) or clean_title
                            artist_value = fetched_song.artist or artist_value
                            prompt_value = fetched_song.raw_prompt or prompt_value
                            lyrics_value = fetched_song.lyrics or lyrics_value
                    except SongNotPublishedError as sne:
                        log.warning("检测到未公开曲目请求: %s", sne)
                        raise HTTPException(status_code=400, detail=str(sne))
                    except Exception as e:
                        log.warning("尝试在线拉取歌曲信息异常: %s", e)

                input_dir = scan_dir.parent / "input" / clean_title
                output_dir = scan_dir / clean_title
                input_dir.mkdir(parents=True, exist_ok=True)
                output_dir.mkdir(parents=True, exist_ok=True)
                _update("audio", 5, "正在准备歌曲音频…")
                # 2. 准备音频
                target_mp3 = input_dir / f"{clean_title}.mp3"
                if staged_upload is not None:
                    temp_upload = staged_upload

                    ffmpeg_bin = get_ffmpeg_binary()
                    cmd = [
                        ffmpeg_bin, "-y",
                        "-i", str(temp_upload),
                        "-vn",
                        "-c:a", "libmp3lame",
                        "-b:a", "192k",
                        str(target_mp3),
                    ]
                    res = subprocess.run(cmd, capture_output=True, text=True)
                    if res.returncode != 0 or not target_mp3.exists() or target_mp3.stat().st_size == 0:
                        if temp_upload.suffix.lower() in [".mp3", ".wav", ".m4a"]:
                            shutil.copy2(temp_upload, target_mp3)
                        else:
                            temp_upload.unlink(missing_ok=True)
                            raise HTTPException(500, f"音频转码失败: {res.stderr[-200:] if res.stderr else '未知错误'}")
                    temp_upload.unlink(missing_ok=True)
                elif fetched_song:
                    download_song(fetched_song, input_dir, song_name=clean_title, save_json=True)
                    cand_mp3 = input_dir / f"{clean_title}.mp3"
                    if cand_mp3.exists():
                        target_mp3 = cand_mp3

                if not target_mp3.exists() or target_mp3.stat().st_size == 0:
                    raise HTTPException(400, "未能获取到有效的音频流。请先在 Suno 页面点击【播放】试听这首歌曲。")

                # 3. 准备封面
                cover_file = input_dir / f"{clean_title}_cover.png"
                cand_cover_url = cover_url or (fetched_song.raw_clip.get("image_large_url") or fetched_song.raw_clip.get("image_url") if fetched_song else "")
                if cand_cover_url and not cover_file.exists():
                    try:
                        import requests
                        img_resp = requests.get(cand_cover_url, timeout=10)
                        if img_resp.status_code == 200:
                            cover_file.write_bytes(img_resp.content)
                    except Exception as e:
                        log.warning("下载封面失败: %s", e)

                # 4. 准备歌词
                clean_lyr = _clean_lyrics(lyrics_value)
                if not clean_lyr and prompt_value:
                    clean_lyr = _clean_lyrics(prompt_value)
                lyrics_path = input_dir / f"{clean_title}.txt"
                lyrics_path.write_text(clean_lyr, encoding="utf-8")

                meta_json = input_dir / f"{clean_title}_suno.json"
                meta_data = {
                    "id": song_id or clean_title,
                    "title": clean_title,
                    "artist": artist_value,
                    "is_public": True,
                    "metadata": {
                        "prompt": prompt_value,
                        "tags": tags,
                    },
                    "from_extension": True,
                }
                meta_json.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")

                # 5. 执行分离、歌词对齐和字幕生成
                cfg_file = scan_dir.parent / "pipeline.toml"
                config = PipelineConfig.from_file(cfg_file) if cfg_file.exists() else PipelineConfig()
                config.ass_only = True

                def _pipeline_progress(step, progress, message):
                    _update(step, 10 + min(100, max(0, progress)) * 0.65, message)

                process_one(target_mp3, lyrics_path, output_dir, None, config, on_progress=_pipeline_progress)

                alignment_json_path = output_dir / f"{clean_title}_alignment.json"
                if alignment_json_path.exists() and prompt_value:
                    try:
                        enrich_alignment_sections(alignment_json_path, prompt_value)
                    except Exception as e:
                        log.warning("乐段结构注入异常: %s", e)

                # 6. 计算乐段与裁剪起止时间
                seg_start = max(0.0, float(start_time or 0.0))
                seg_dur = float(duration_limit or 0.0) if duration_limit and duration_limit > 0 else None
                out_suffix = ""

                if alignment_json_path.exists():
                    try:
                        from src.aligner import AlignmentResult
                        al_obj = AlignmentResult.load_json(alignment_json_path)
                        sec_lower = (section_name or "").strip().lower()

                        if sec_lower in ("chorus", "verse1", "verse2", "intro"):
                            target_sec = None
                            if sec_lower == "chorus":
                                out_suffix = "_副歌"
                                for s in al_obj.sections:
                                    s_name = (getattr(s, "name", "") or "").lower()
                                    s_lbl = getattr(s, "label", "") or ""
                                    if "chorus" in s_name or "副歌" in s_lbl:
                                        target_sec = s
                                        break
                                if not target_sec:
                                    for line in getattr(al_obj, "lines", []):
                                        l_sec = getattr(line, "section", "") or ""
                                        if "chorus" in l_sec.lower() or "副歌" in l_sec:
                                            seg_start = line.start
                                            target_sec = True
                                            break
                                if not target_sec and al_obj.sections:
                                    target_sec = max(al_obj.sections, key=lambda x: getattr(x, "energy", 0.0))
                                if not target_sec and al_obj.duration > 35:
                                    seg_start = al_obj.duration * 0.35
                            elif sec_lower == "verse1":
                                out_suffix = "_主歌1"
                                for s in al_obj.sections:
                                    s_name = (getattr(s, "name", "") or "").lower()
                                    s_lbl = getattr(s, "label", "") or ""
                                    if "verse" in s_name or "主歌" in s_lbl:
                                        target_sec = s
                                        break
                                if not target_sec:
                                    for line in getattr(al_obj, "lines", []):
                                        l_sec = getattr(line, "section", "") or ""
                                        if "verse" in l_sec.lower() or "主歌" in l_sec:
                                            seg_start = line.start
                                            target_sec = True
                                            break
                            elif sec_lower == "intro":
                                out_suffix = "_前奏"
                                seg_start = 0.0
                                target_sec = True

                            if target_sec and hasattr(target_sec, "start"):
                                seg_start = target_sec.start
                                if not seg_dur or seg_dur <= 0:
                                    seg_dur = 30.0  # 自动向后截取 30 秒黄金短视频长度
                            elif not seg_dur or seg_dur <= 0:
                                if sec_lower != "full":
                                    seg_dur = 30.0
                    except Exception as e:
                        log.warning("解析乐段切片异常: %s", e)

                clean_ratio = aspect_ratio.replace(":", "x")
                out_mp4 = output_dir / f"{clean_title}_lyric_{clean_ratio}_{template}{out_suffix}.mp4"
                _lyric_video_tasks[task_id]["title"] = clean_title
                _update("rendering", 75, "正在渲染歌词视频…")

                def _on_prog(p_val: float, msg: str):
                    _update("rendering", 75 + min(100, max(0, p_val)) * 0.25, msg)

                res = export_lyric_video(
                    alignment_source=alignment_json_path,
                    audio_path=target_mp3,
                    output_path=out_mp4,
                    aspect_ratio=aspect_ratio,
                    template=template,
                    theme=theme,
                    background_mode=background_mode,
                    cover_path=cover_file if cover_file.exists() else None,
                    start_time=seg_start,
                    duration_limit=seg_dur,
                    progress_callback=_on_prog,
                )

                res["video_url"] = f"/api/asset_file?path={encode_path(str(out_mp4.absolute()))}"
                res["download_url"] = f"/api/asset_file?download=true&filename={quote(clean_title + out_suffix + '_' + clean_ratio + '.mp4')}&path={encode_path(str(out_mp4.absolute()))}"

                _lyric_video_tasks[task_id].update(
                    result=res, progress=100.0, phase="completed",
                    message=f"视频生成成功！耗时: {res.get('elapsed_seconds')}s",
                    status="completed",
                )
                log.info("Chrome 插件触发动效短视频生成完成: %s -> %s", task_id, out_mp4.name)
        except Exception as exc:
            error = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
            log.exception("Chrome 插件视频任务失败: %s", task_id)
            _lyric_video_tasks[task_id].update(status="failed", error=error, message=f"生成失败: {error}")
        finally:
            if staged_upload is not None:
                staged_upload.unlink(missing_ok=True)

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "pending", "task_id": task_id, "title": title,
            "message": "任务已提交，下载、分离、对齐和渲染将在后台完成。"}


@app.post("/api/plugin/import")
async def plugin_direct_import(
    audio_file: UploadFile = File(...),
    title: str = Form("Suno_Track"),
    lyrics: str = Form(""),
    prompt: str = Form(""),
    artist: str = Form("unknown"),
    song_id: str = Form(""),
    tags: str = Form(""),
):
    """
    接收来自 Chrome 扩展等外部插件直接捕获上传的音频流与歌词，
    自动执行音频转码、Demucs 分轨、时间轴对齐并返回编辑器访问链接。
    无需通过 Suno 官方下载接口，完全不消耗 Suno 25 首下载额度。
    """
    import subprocess
    from urllib.parse import quote
    from src.suno_fetch import _sanitize_filename, _clean_lyrics, enrich_alignment_sections
    from src.main import process_one
    from src.config import PipelineConfig
    from src.utils import get_ffmpeg_binary

    clean_title = _sanitize_filename(title) or f"suno_{uuid.uuid4().hex[:8]}"
    scan_dir = _get_scan_dir()
    input_dir = scan_dir.parent / "input" / clean_title
    output_dir = scan_dir / clean_title
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 保存上传的原始音频流 (可能是 webm, opus, mp3, wav, m4a 等)
    temp_upload = input_dir / f"temp_{clean_title}_{audio_file.filename}"
    with open(temp_upload, "wb") as f:
        shutil.copyfileobj(audio_file.file, f)

    # 2. 通过 FFmpeg 统一转码为标准高质量 MP3 (192kbps)
    target_mp3 = input_dir / f"{clean_title}.mp3"
    ffmpeg_bin = get_ffmpeg_binary()
    cmd = [
        ffmpeg_bin, "-y",
        "-i", str(temp_upload),
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        str(target_mp3),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not target_mp3.exists() or target_mp3.stat().st_size == 0:
        if temp_upload.suffix.lower() in [".mp3", ".wav", ".m4a"]:
            shutil.copy2(temp_upload, target_mp3)
        else:
            temp_upload.unlink(missing_ok=True)
            raise HTTPException(500, f"音频转码失败: {res.stderr[-200:] if res.stderr else '未知错误'}")
    temp_upload.unlink(missing_ok=True)

    # 3. 保存歌词与元数据
    clean_lyr = _clean_lyrics(lyrics)
    if not clean_lyr and prompt:
        clean_lyr = _clean_lyrics(prompt)
    lyrics_path = input_dir / f"{clean_title}.txt"
    lyrics_path.write_text(clean_lyr, encoding="utf-8")

    meta_json = input_dir / f"{clean_title}_suno.json"
    meta_data = {
        "id": song_id or clean_title,
        "title": clean_title,
        "artist": artist,
        "metadata": {
            "prompt": prompt,
            "tags": tags,
        },
        "from_extension": True,
    }
    meta_json.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 4. 执行自动分轨与时间轴对齐
    cfg_file = scan_dir.parent / "pipeline.toml"
    config = PipelineConfig.from_file(cfg_file) if cfg_file.exists() else PipelineConfig()
    config.ass_only = True

    process_one(target_mp3, lyrics_path, output_dir, None, config)

    # 5. 若有 prompt 段落标记，注入乐段结构
    alignment_json_path = output_dir / f"{clean_title}_alignment.json"
    if alignment_json_path.exists() and prompt:
        try:
            enrich_alignment_sections(alignment_json_path, prompt)
        except Exception as e:
            log.warning("乐段结构注入异常: %s", e)

    editor_url = f"/?song={quote(clean_title)}"
    return {
        "status": "ok",
        "title": clean_title,
        "editor_url": editor_url,
        "full_editor_url": f"http://127.0.0.1:8000{editor_url}",
    }


@app.get("/api/files")

def list_files():
    """列出 output/{song_name}/ 各专属子目录内的 *_alignment.json 文件"""
    scan_dir = _get_scan_dir()
    sub_files = list(scan_dir.glob("*/*_alignment.json"))
    
    seen_stems = set()
    result = []
    
    for f in sorted(sub_files, key=lambda x: x.stat().st_mtime, reverse=True):
        stem = f.stem.replace("_alignment", "")
        if stem in seen_stems:
            continue
        seen_stems.add(stem)
        audio = _find_audio(stem, song_output_dir=f.parent)
        tracks = _find_audio_tracks(stem, song_output_dir=f.parent)
        result.append({
            "name": stem,
            "json_path": str(f),
            "audio_path": str(audio) if audio else None,
            "audio_tracks": tracks,
        })
    return result


@app.get("/api/assets")
def list_assets():
    """列出可用图片/视频素材"""
    scan_dir = _get_scan_dir()
    input_dir = scan_dir.parent / "input"
    assets_dir = scan_dir.parent / "assets"
    
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".mp4"}
    result = []
    
    # 查找 input 和 assets 目录下的文件
    for d in [input_dir, assets_dir]:
        if d.exists():
            for f in d.iterdir():
                if f.suffix.lower() in extensions:
                    result.append({
                        "name": f.name,
                        "path": str(f.absolute()),
                        "url": f"/api/asset_file?path={encode_path(str(f.absolute()))}"
                    })
    return result


@app.get("/api/asset_file", operation_id="get_asset_file_get")
@app.head("/api/asset_file", operation_id="get_asset_file_head", include_in_schema=False)
def get_asset_file(path: str, json_path: str = "", download: bool = False, filename: str | None = None):
    """提供素材文件流（支持视频 Range 拖拽播放与 HEAD 嗅探，以及附件直接下载）"""
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        if json_path:
            cand = Path(json_path).parent / path
            if cand.exists():
                p = cand
        if not p.exists():
            scan_dir = _get_scan_dir()
            for sub in scan_dir.iterdir():
                if sub.is_dir() and (sub / path).exists():
                    p = sub / path
                    break
    p = _validate_path(p)
    suffix = p.suffix.lower()
    media_types = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    media_type = media_types.get(suffix, None)
    headers = {"Accept-Ranges": "bytes"}
    if download or filename:
        from urllib.parse import quote
        dl_name = filename or p.name
        quoted = quote(dl_name)
        headers["Content-Disposition"] = f"attachment; filename=\"{quoted}\"; filename*=UTF-8''{quoted}"
    return FileResponse(p, media_type=media_type, headers=headers)


def encode_path(p: str) -> str:
    import urllib.parse
    return urllib.parse.quote(p)


@app.get("/api/alignment")
def get_alignment(path: str):
    """读取 alignment.json"""
    p = _validate_path(Path(path))
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.put("/api/alignment")
def save_alignment(path: str, project: AlignmentProject):
    """保存编辑后的 alignment.json（先备份）"""
    p = _validate_path(Path(path))

    bak = p.with_suffix(".json.bak")
    with _alignment_write_lock:
        shutil.copy2(p, bak)
        project.save_json(p)

    log.info("保存完成: %s", p.name)
    return {"status": "ok", "backup": str(bak)}


class AudioAnalysisRequest(BaseModel):
    json_path: str
    force: bool = False


_audio_analysis_tasks: dict[str, dict[str, Any]] = {}
_audio_analysis_lock = threading.Lock()


@app.post("/api/audio/analyze")
def api_analyze_audio(req: AudioAnalysisRequest):
    """Analyze existing songs independently of alignment; reuse active work/cache."""
    import uuid
    json_path = _validate_path(Path(req.json_path))
    stem = json_path.stem.removesuffix("_alignment")
    audio = _find_audio(stem, song_output_dir=json_path.parent)
    if audio is None:
        raise HTTPException(404, "未找到原曲音频，不能用人声或伴奏代替")
    audio = _validate_path(audio)
    with _audio_analysis_lock:
        for task_id, task in _audio_analysis_tasks.items():
            if task["json_path"] == str(json_path) and task["status"] == "running":
                return {"task_id": task_id, "status": "running"}
        task_id = uuid.uuid4().hex
        _audio_analysis_tasks[task_id] = {"status": "running", "json_path": str(json_path)}

    def run():
        try:
            from src.audio_analyzer import cached_audio_analysis
            from src.storyboard_schema import MusicSection
            analysis = cached_audio_analysis(audio, json_path.parent / f"{stem}_analysis.json", force=req.force)
            with _alignment_write_lock:
                # Reload after analysis to retain lyric edits saved during the calculation.
                payload = json.loads(json_path.read_text(encoding="utf-8"))
                sections = [MusicSection.model_validate(s) for s in payload.get("sections", [])]
                from src.audio_analyzer import detect_cut_candidates
                analysis.sections = sections
                analysis.cut_candidates = detect_cut_candidates(analysis.duration, analysis.beats, analysis.downbeats, analysis.drum_hits, analysis.energy_curve, sections)
                payload["analysis"] = analysis.model_dump()
                payload["audio_path"] = str(audio)
                payload["duration"] = analysis.duration
                import tempfile
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=json_path.parent, suffix=".tmp", delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(payload, stream, ensure_ascii=False, indent=2)
                try:
                    temporary.replace(json_path)
                finally:
                    temporary.unlink(missing_ok=True)
            _audio_analysis_tasks[task_id] = {"status": "done", "json_path": str(json_path), "bpm": analysis.bpm, "duration": analysis.duration, "beats": len(analysis.beats), "samples": len(analysis.envelopes), "cache_hit": analysis.metadata["cache_hit"]}
        except Exception as exc:
            log.exception("音频分析失败")
            _audio_analysis_tasks[task_id] = {"status": "error", "json_path": str(json_path), "error": str(exc)}

    threading.Thread(target=run, daemon=True).start()
    return {"task_id": task_id, "status": "running"}


@app.get("/api/audio/analyze/{task_id}")
def api_audio_analysis_status(task_id: str):
    task = _audio_analysis_tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "音频分析任务不存在")
    return task


class AutoDirectRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    audio_path: str | None = Field(default=None, description="音频路径")


@app.post("/api/director/auto_direct")
def api_auto_direct(req: AutoDirectRequest):
    """
    一键运行 AI 导演与动态故事板 (Animatic) 生成流程
    """
    try:
        json_path = _validate_path(Path(req.json_path))
        project = AlignmentProject.load_json(json_path)

        # 查找可用音频
        song_dir = json_path.parent
        audio_path = None
        if req.audio_path:
            p = _validate_path(Path(req.audio_path))
            if p.exists():
                audio_path = p
        if not audio_path:
            stem = json_path.stem.replace("_alignment", "")
            audio_path = _find_audio(stem, song_output_dir=song_dir)

        analysis = None
        if audio_path and audio_path.exists():
            try:
                from src.audio_analyzer import cached_audio_analysis
                analysis = cached_audio_analysis(
                    audio_path=audio_path,
                    cache_path=song_dir / f"{json_path.stem.removesuffix('_alignment')}_analysis.json",
                    sections=project.sections,
                )
                project.analysis = analysis
            except Exception as e:
                log.warning("音频特征分析跳过或失败: %s", e)

        # 运行导演引擎
        from src.director_engine import direct_project
        project = direct_project(project, analysis=analysis)

        # 批量渲染动态分镜卡片
        sb_dir = song_dir / "storyboard"
        try:
            from src.storyboard_renderer import render_all_storyboard_frames
            render_all_storyboard_frames(project, output_dir=sb_dir)
        except Exception as e:
            log.warning("分镜卡片渲染跳过: %s", e)

        # 保存更新后的工程
        project.save_json(json_path)
        log.info("AI 导演处理完成: %d 个镜头已写入 %s", len(project.storyboard), json_path.name)

        return {
            "status": "ok",
            "shots_count": len(project.storyboard),
            "treatment": project.treatment.model_dump() if project.treatment else None,
            "visual_bible": project.visual_bible.model_dump() if project.visual_bible else None,
            "project": project.model_dump(),
        }
    except Exception as e:
        log.exception("AI 导演执行异常: %s", e)
        raise HTTPException(status_code=500, detail=f"离线导演编排失败: {str(e)}")


class LLMPromptRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    mode: str = Field(default="dual_track", description="提示词模式: dual_track, shot_director, typography_director")


@app.post("/api/director/llm_prompt")
def api_director_llm_prompt(req: LLMPromptRequest):
    """
    生成大模型导演结构化 Prompt，并保存到本地文件
    """
    json_path = _validate_path(Path(req.json_path))
    from src.llm_director import generate_llm_prompt
    song_dir = json_path.parent
    stem = json_path.stem.replace("_alignment", "")
    prompt_file = song_dir / f"{stem}_llm_prompt.txt"

    prompt_text = generate_llm_prompt(json_path, output_prompt_path=prompt_file, mode=req.mode)
    return {
        "status": "ok",
        "prompt": prompt_text,
        "prompt_path": str(prompt_file),
    }


class LLMMergeRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    response_data: Any = Field(..., description="大模型返回的 JSON 字符串或对象")


@app.post("/api/director/llm_merge")
def api_director_llm_merge(req: LLMMergeRequest):
    """
    接收大模型返回的 JSON 数据，回填到工程中并重新渲染分镜样片
    """
    json_path = _validate_path(Path(req.json_path))
    from src.llm_director import merge_llm_response, detect_payload_track_mode
    song_dir = json_path.parent
    clips_dir = song_dir / "clips"
    track_mode = detect_payload_track_mode(req.response_data)
    mode_names = {
        "dual_track": "影视级双轨联合数据",
        "shot_only": "纯画面分镜单轨数据",
        "typography_only": "歌词动效排版单轨数据",
    }
    mode_text = mode_names.get(track_mode, "分镜数据")

    try:
        project = merge_llm_response(
            alignment_source=json_path,
            response_source=req.response_data,
            output_path=json_path,
            clips_dir=clips_dir,
            render_frames=True,
        )
    except Exception as e:
        log.error("大模型回填失败: %s", e)
        raise HTTPException(status_code=400, detail=f"解析或回填大模型数据失败: {e}")

    # 保存原始回填响应到本地文件作为持久化缓存
    cached_file = song_dir / "llm_director_response.json"
    try:
        if isinstance(req.response_data, str):
            cached_file.write_text(req.response_data, encoding="utf-8")
        else:
            cached_file.write_text(json.dumps(req.response_data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as ce:
        log.warning("缓存大模型回填响应失败: %s", ce)

    return {
        "status": "ok",
        "track_mode": track_mode,
        "shots_count": len(project.storyboard),
        "message": f"成功识别 [{mode_text}] 并回填 {len(project.storyboard)} 个分镜数据",
        "project": project.model_dump(),
        "cached": True,
    }


@app.get("/api/director/llm_cached_response")
def api_director_get_cached_response(json_path: str):
    """
    获取当前工程历史保存的大模型回填 JSON 响应与元信息
    """
    jp = _validate_path(Path(json_path))
    cached_file = jp.parent / "llm_director_response.json"
    if not cached_file.exists():
        return {"exists": False, "data": None}

    try:
        content = cached_file.read_text(encoding="utf-8").strip()
        count = 0
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                count = len(parsed)
            elif isinstance(parsed, dict):
                count = len(parsed.get("shots", []) or parsed.get("data", []) or [parsed])
        except Exception:
            pass

        mtime = cached_file.stat().st_mtime
        from datetime import datetime
        mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        return {
            "exists": True,
            "data": content,
            "mtime": mtime_str,
            "shots_count": count,
        }
    except Exception as e:
        log.warning("读取大模型缓存失败: %s", e)
        return {"exists": False, "error": str(e), "data": None}


@app.delete("/api/director/llm_cached_response")
def api_director_delete_cached_response(json_path: str):
    """
    清除当前工程的大模型回填持久化缓存
    """
    jp = _validate_path(Path(json_path))
    cached_file = jp.parent / "llm_director_response.json"
    if cached_file.exists():
        try:
            cached_file.unlink()
            return {"status": "ok", "message": "已清除本地回填缓存"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"删除缓存文件失败: {e}")
    return {"status": "ok", "message": "缓存文件不存在"}


@app.get("/api/storyboard_frame")
def api_get_storyboard_frame(json_path: str, frame_name: str):
    """
    提供动态故事板分镜预览图片流
    """
    jp = _validate_path(Path(json_path))
    clean_frame = Path(frame_name).name
    frame_path = jp.parent / "storyboard" / clean_frame
    if not frame_path.exists():
        try:
            from src.storyboard_renderer import render_shot_frame
            proj = AlignmentProject.load_json(jp)
            shot_id_match = clean_frame.replace(".png", "")
            target_shot = next(
                (s for s in proj.storyboard if s.id == shot_id_match or f"shot_{s.shot_id:03d}" == shot_id_match),
                None
            )
            if target_shot:
                render_shot_frame(target_shot, frame_path)
        except Exception as e:
            log.error("即时渲染分镜失败: %s", e)

    if not frame_path.exists():
        raise HTTPException(404, f"分镜卡片不存在: {clean_frame}")
    return FileResponse(frame_path)


@app.post("/api/regen")
def regen_ass(req: RegenRequest):
    """从 alignment.json 生成 .ass 或合成视频"""
    json_path = Path(req.json_path)
    if not json_path.exists():
        raise HTTPException(404, f"JSON 不存在: {json_path}")

    try:
        alignment = AlignmentProject.load_json(json_path)
        stem = json_path.stem.replace("_alignment", "")
        ass_path = json_path.parent / f"{stem}.ass"
        audio_path = Path(req.audio_path) if req.audio_path else None
        subtitle_config = getattr(app.state, "subtitle_config", SubtitleConfig())
        
        # 覆盖设置
        subtitle_config.use_karaoke_gradient = (req.tag_type == "kf")
        subtitle_config.render_mode = req.render_mode
        
        # 生成 ASS
        generate_ass(alignment, ass_path, subtitle_config, audio_path=audio_path)
        log.info("ASS 重新生成: %s", ass_path.name)
        
        res = {"status": "ok", "ass_path": str(ass_path)}
        
        if req.mode == "video" and audio_path:
            # 执行视频合成
            from src.compositor import compose_video, CompositorConfig
            video_path = json_path.parent / f"{stem}.mp4"
            compositor_config = getattr(app.state, "compositor_config", CompositorConfig())

            # 背景优先级: alignment.json 中的 background 字段 > 纯黑
            background: Path | None = None
            if alignment.background:
                bg_p = Path(alignment.background)
                if bg_p.exists():
                    background = bg_p
                    log.info("使用 alignment.json 中的背景: %s", bg_p.name)
                else:
                    log.warning("alignment.json 指定的背景不存在: %s", bg_p)

            log.info("开始合成视频: %s (背景: %s, 分镜: %d 个)",
                     video_path.name, background, len(alignment.storyboard))
            compose_video(
                audio_path=audio_path,
                subtitle_path=ass_path,
                output_path=video_path,
                background=background,
                config=compositor_config,
                storyboard=alignment.storyboard,
            )
            log.info("视频合成完成: %s", video_path.name)
            res["video_path"] = str(video_path)
            res["mode"] = "video"
        
        return res
    except Exception as e:
        log.error("生成失败: %s", e, exc_info=True)
        raise HTTPException(500, str(e))


@app.post("/api/realign")
def realign(req: RealignRequest):
    """
    局部重对齐: 对 alignment JSON 中指定的行重新跑 WhisperX。
    """
    from src.aligner import realign_lines

    json_path = Path(req.json_path)
    if not json_path.exists():
        raise HTTPException(404, f"JSON 不存在: {json_path}")

    project = AlignmentProject.load_json(json_path)
    line_indices = req.line_indices

    invalid = [i for i in line_indices if i < 0 or i >= len(project.lines)]
    if invalid:
        raise HTTPException(400, f"索引越界: {invalid}，共 {len(project.lines)} 行")

    selected = [project.lines[i] for i in line_indices]
    rough_start = min(l.start for l in selected)
    rough_end   = max(l.end   for l in selected)
    texts       = [l.text for l in selected]

    # 优先用专属目录中的 {stem}_vocals.wav，找不到再用原始音频
    stem = json_path.stem.replace("_alignment", "")
    song_dir = json_path.parent
    vocals_path = song_dir / f"{stem}_vocals.mp3"
    if not vocals_path.exists():
        vocals_path = song_dir / f"{stem}_vocals.wav"
    if not vocals_path.exists():
        audio = _find_audio(stem, song_output_dir=song_dir)
        if audio is None:
            raise HTTPException(404, f"找不到人声文件: {stem}_vocals.mp3 或 .wav")
        vocals_path = audio
        log.warning("未找到 vocals 文件，使用原始音频: %s", vocals_path.name)

    log.info("局部重对齐请求: %s 第 %s 行 (%.2f~%.2fs)",
             stem, line_indices, rough_start, rough_end)

    try:
        new_lines = realign_lines(
            vocals_path=vocals_path,
            texts=texts,
            rough_start=rough_start,
            rough_end=rough_end,
            buffer=req.buffer,
        )
    except Exception as e:
        log.error("局部重对齐失败: %s", e, exc_info=True)
        raise HTTPException(500, str(e))

    for list_pos, orig_idx in enumerate(line_indices):
        if list_pos < len(new_lines):
            nl = new_lines[list_pos]
            project.lines[orig_idx] = AlignedLine(
                text=nl.text,
                start=nl.start,
                end=nl.end,
                words=[WordTimestamp(word=w.word, start=w.start, end=w.end) for w in nl.words],
                section=project.lines[orig_idx].section,
                style_overrides=project.lines[orig_idx].style_overrides,
            )

    bak = json_path.with_suffix(".json.bak")
    shutil.copy2(json_path, bak)
    project.save_json(json_path)

    log.info("局部重对齐完成，已写回: %s", json_path.name)
    return {
        "status": "ok",
        "patched_indices": line_indices,
        "lines": [
            {"index": orig_idx, "start": project.lines[orig_idx].start,
             "end": project.lines[orig_idx].end, "text": project.lines[orig_idx].text}
            for orig_idx in line_indices
        ],
    }


@app.post("/api/upload_asset")
async def upload_asset(file: UploadFile = File(...)):
    """上传图片素材到 assets/ 目录"""
    scan_dir = _get_scan_dir()
    assets_dir = scan_dir.parent / "assets"
    assets_dir.mkdir(exist_ok=True)

    # 安全校验文件类型
    allowed_suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed_suffixes:
        raise HTTPException(400, f"不支持的文件类型: {suffix}，仅允许 jpg/jpeg/png/webp")

    # 安全文件名（去除路径分隔符）
    safe_name = Path(file.filename).name
    dest = assets_dir / safe_name

    content = await file.read()
    # 限制文件大小 50MB
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(400, "文件过大，最大支持 50MB")

    with open(dest, "wb") as f:
        f.write(content)

    log.info("素材上传: %s -> %s", file.filename, dest)
    return {
        "status": "ok",
        "name": safe_name,
        "path": str(dest),
        "url": f"/api/asset_file?path={encode_path(str(dest.absolute()))}"
    }


@app.get("/api/audio", operation_id="stream_audio_get")
@app.head("/api/audio", operation_id="stream_audio_head", include_in_schema=False)
def stream_audio(path: str, download: bool = False, filename: str | None = None):
    """提供音频文件流（支持 Range 请求与附件下载）"""
    p = _validate_path(Path(path))
    suffix = p.suffix.lower()
    media_types = {".mp3": "audio/mpeg", ".wav": "audio/wav",
                   ".flac": "audio/flac", ".m4a": "audio/mp4", ".ogg": "audio/ogg"}
    media_type = media_types.get(suffix, "audio/mpeg")
    headers = {"Accept-Ranges": "bytes"}
    dl_name = filename or p.name if download else None
    if dl_name:
        from urllib.parse import quote
        quoted = quote(dl_name)
        headers["Content-Disposition"] = f"attachment; filename=\"{quoted}\"; filename*=UTF-8''{quoted}"
    return FileResponse(p, media_type=media_type, headers=headers)


@app.get("/api/download/original_mp3")
def download_original_mp3(song: str | None = None, json_path: str | None = None):
    """
    一键下载原曲 MP3：
    接收 song 名称或 json_path，自动找到原曲。
    若原曲为 wav/m4a/flac，则自动转码为 mp3 后返回，确保用户下载到的始终是 MP3。
    """
    song_dir = None
    stem = song
    if json_path:
        jp = _validate_path(Path(json_path))
        stem = jp.stem.replace("_alignment", "")
        song_dir = jp.parent
    elif song:
        stem = song.strip()
        scan_dir = _get_scan_dir()
        if (scan_dir / stem).exists():
            song_dir = scan_dir / stem
    else:
        raise HTTPException(400, "必须提供 song 或 json_path 参数")

    audio = _find_audio(stem, song_output_dir=song_dir)
    if not audio or not audio.exists():
        raise HTTPException(404, f"未找到歌曲 [{stem}] 的原曲音频文件")

    target_mp3 = audio
    if audio.suffix.lower() != ".mp3":
        cached_mp3 = audio.parent / f"{stem}.mp3"
        if cached_mp3.exists() and cached_mp3.stat().st_size > 1024:
            target_mp3 = cached_mp3
        else:
            from src.utils import get_ffmpeg_binary
            ffmpeg_bin = get_ffmpeg_binary()
            temp_mp3 = audio.parent / f"{stem}.mp3"
            cmd = [
                ffmpeg_bin, "-y",
                "-i", str(audio),
                "-vn",
                "-c:a", "libmp3lame",
                "-b:a", "192k",
                str(temp_mp3)
            ]
            import subprocess
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0 and temp_mp3.exists() and temp_mp3.stat().st_size > 1024:
                target_mp3 = temp_mp3
            else:
                log.warning("转码 MP3 失败，回退直接下载原音频: %s", res.stderr)
                target_mp3 = audio

    dl_filename = f"{stem}.mp3" if target_mp3.suffix.lower() == ".mp3" else f"{stem}{target_mp3.suffix}"
    from urllib.parse import quote
    quoted = quote(dl_filename)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f"attachment; filename=\"{quoted}\"; filename*=UTF-8''{quoted}",
    }
    media_type = "audio/mpeg" if target_mp3.suffix.lower() == ".mp3" else "application/octet-stream"
    return FileResponse(target_mp3, media_type=media_type, headers=headers)


@app.get("/api/suno/publish_status")
def api_suno_publish_status(url: str):
    """Check public availability without downloading or aligning audio."""
    from src.suno_fetch import fetch_song, SongNotPublishedError
    try:
        song = fetch_song(url.strip(), require_public=True)
        return {"is_public": song.is_public is True}
    except SongNotPublishedError:
        raise HTTPException(400, "Song is not published. Publish it in Suno’s (…) menu before downloading MP3 or MP4.")
    except Exception:
        raise HTTPException(502, "Could not verify song publication. Please try again.")


@app.get("/api/suno/download_mp3", operation_id="api_suno_download_mp3_get")
@app.post("/api/suno/download_mp3", operation_id="api_suno_download_mp3_post")
def api_suno_download_mp3(url: str):
    """
    Suno 仅下载原曲 MP3（第一步）：
    仅执行歌曲信息抓取 + 原曲音频下载 (支持直链与视频流自动回退提取)，
    不进行耗时的 Demucs 人声分离和 WhisperX 字符级对齐。
    """
    from src.suno_fetch import SongNotPublishedError
    url = url.strip()
    if not url:
        raise HTTPException(400, "请输入 Suno 歌曲链接")

    scan_dir = _get_scan_dir()
    input_dir = scan_dir.parent / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    try:
        is_netease = (
            "163.com" in url.lower()
            or "163cn.tv" in url.lower()
            or "<iframe" in url.lower()
            or "music.163" in url.lower()
            or (url.isdigit() and len(url) >= 5)
        )
        if is_netease:
            from src.netease_fetch import download_netease_song, fetch_netease_song, _sanitize_filename
            log.info(">>> [仅下 MP3] 开始从网易云音乐提取歌曲: %s", url)
            song = fetch_netease_song(url)
            song_name = _sanitize_filename(song.title) or f"netease_{song.id}"
            song_input_dir = input_dir / song_name
            song_input_dir.mkdir(parents=True, exist_ok=True)

            audio_path, lyrics_path, json_path, song = download_netease_song(
                song, song_input_dir, song_name=song_name, save_json=True
            )

            if not audio_path or not audio_path.exists():
                raise HTTPException(404, f"未能自动下载《{song.title}》音频流，该歌曲可能受平台版权保护。已保存歌词至 {song_input_dir}")
        else:
            from src.suno_fetch import fetch_song, download_song, _sanitize_filename
            log.info(">>> [仅下 MP3] 开始从 Suno 提取歌曲: %s", url)
            song = fetch_song(url)
            song_name = _sanitize_filename(song.title) or song.id
            song_input_dir = input_dir / song_name
            song_input_dir.mkdir(parents=True, exist_ok=True)

            audio_path, lyrics_path, json_path, song = download_song(
                url, song_input_dir, song_name=song_name, save_json=True
            )

            if not audio_path or not audio_path.exists():
                raise HTTPException(404, "未能从 Suno 提取音频，可能该歌曲未设置为 Public")

        # 确保输出为标准 MP3
        target_mp3 = audio_path
        if audio_path.suffix.lower() != ".mp3":
            cached_mp3 = audio_path.parent / f"{song_name}.mp3"
            if cached_mp3.exists() and cached_mp3.stat().st_size > 1024:
                target_mp3 = cached_mp3
            else:
                from src.utils import get_ffmpeg_binary
                ffmpeg_bin = get_ffmpeg_binary()
                temp_mp3 = audio_path.parent / f"{song_name}.mp3"
                cmd = [
                    ffmpeg_bin, "-y",
                    "-i", str(audio_path),
                    "-vn",
                    "-c:a", "libmp3lame",
                    "-b:a", "192k",
                    str(temp_mp3)
                ]
                import subprocess
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0 and temp_mp3.exists() and temp_mp3.stat().st_size > 1024:
                    target_mp3 = temp_mp3

        from urllib.parse import quote
        filename = f"{song_name}.mp3"
        quoted = quote(filename)
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": f"attachment; filename=\"{quoted}\"; filename*=UTF-8''{quoted}",
        }
        return FileResponse(target_mp3, media_type="audio/mpeg", headers=headers)
    except HTTPException:
        raise
    except Exception as e:
        if isinstance(e, SongNotPublishedError):
            raise HTTPException(400, "Song is not published. Publish it in Suno’s (…) menu before downloading MP3 or MP4.")
        log.error("Suno MP3 下载失败: %s", e, exc_info=True)
        raise HTTPException(500, f"Suno MP3 下载失败: {str(e)}")




# ── 商业化歌词动效短视频端点 ──────────────────────────────
class LyricVideoExportRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    audio_path: str | None = Field(default=None, description="音频路径 (可选)")
    aspect_ratio: str = Field(default="9:16", description="视频比例: 9:16 或 16:9")
    template: str = Field(default="apple", description="歌词排版模板: apple, center_bounce, tv")
    theme: str = Field(default="apple_white", description="主题调色板")
    background_mode: str = Field(default="full_bleed", description="动态背景模式: full_bleed, ken_burns, blurred_ambient, vinyl, solid_black")
    cover_path: str | None = Field(default=None, description="自定义封面路径 (可选)")
    font_size: int | None = Field(default=None, description="自定义字体大小 (可选)")
    duration_limit: float | None = Field(default=None, description="时长限制 (可选)")
    start_time: float = Field(default=0.0, description="裁剪起始时间 (秒)")
    end_time: float | None = Field(default=None, description="裁剪结束时间 (秒)")


_lyric_video_tasks = TaskStore(lambda: _get_scan_dir().parent / "work" / "video_tasks")


@app.get("/api/lyric_video/templates")
def api_get_lyric_video_templates():
    """获取所有可用的动效短视频模板、比例规格、主题色彩与背景动效选项"""
    from src.lyric_engine import get_lyric_video_options
    return get_lyric_video_options()


@app.post("/api/lyric_video/export")
def api_export_lyric_video(req: LyricVideoExportRequest):
    """一键异步合成 9:16 / 16:9 商业级动效歌词短视频"""
    jp = _validate_path(Path(req.json_path))
    stem = jp.stem.replace("_alignment", "")
    song_dir = jp.parent

    # 查找可用音频
    audio_path = None
    if req.audio_path:
        p = Path(req.audio_path)
        if p.exists():
            audio_path = p
    if not audio_path:
        audio_path = _find_audio(stem, song_output_dir=song_dir)
    if not audio_path:
        raise HTTPException(404, f"未找到可用的音频文件: {stem}")

    # 规范化输出路径: output/{song_name}/{song_name}_lyric_{ratio}_{template}.mp4
    clean_ratio = req.aspect_ratio.replace(":", "x")
    seg_tag = f"_{int(req.start_time)}s" if req.start_time > 0 else ""
    out_mp4 = song_dir / f"{stem}_lyric_{clean_ratio}_{req.template}{seg_tag}.mp4"

    task_id = f"lyric_{uuid.uuid4().hex[:8]}"
    _lyric_video_tasks[task_id] = {
        "status": "pending",
        "progress": 5.0,
        "message": "动效歌词短视频任务已提交...",
        "task_id": task_id,
        "result": None,
        "error": None,
    }

    def _worker():
        try:
            from src.lyric_engine import export_lyric_video
            _lyric_video_tasks[task_id]["status"] = "running"
            _lyric_video_tasks[task_id]["progress"] = 15.0

            def _on_prog(p_val: float, msg: str):
                _lyric_video_tasks[task_id]["progress"] = p_val
                _lyric_video_tasks[task_id]["message"] = msg

            res = export_lyric_video(
                alignment_source=jp,
                audio_path=audio_path,
                output_path=out_mp4,
                aspect_ratio=req.aspect_ratio,
                template=req.template,
                theme=req.theme,
                background_mode=req.background_mode,
                cover_path=req.cover_path,
                font_size=req.font_size,
                duration_limit=req.duration_limit,
                start_time=req.start_time,
                end_time=req.end_time,
                progress_callback=_on_prog,
            )

            res["video_url"] = f"/api/asset_file?path={encode_path(str(out_mp4.absolute()))}"
            if "cover_path" in res and res["cover_path"]:
                res["cover_url"] = f"/api/asset_file?path={encode_path(str(Path(res['cover_path']).absolute()))}"

            _lyric_video_tasks[task_id]["status"] = "completed"
            _lyric_video_tasks[task_id]["progress"] = 100.0
            _lyric_video_tasks[task_id]["message"] = f"视频生成成功！耗时: {res.get('elapsed_seconds')}s"
            _lyric_video_tasks[task_id]["result"] = res
            log.info("动效歌词短视频生成完成: %s -> %s", task_id, out_mp4.name)
        except Exception as e:
            log.exception("动效歌词短视频生成失败: %s", e)
            _lyric_video_tasks[task_id]["status"] = "failed"
            _lyric_video_tasks[task_id]["error"] = str(e)
            _lyric_video_tasks[task_id]["message"] = f"生成失败: {e}"

    threading.Thread(target=_worker, daemon=True).start()
    return {"task_id": task_id, "status": "pending"}


@app.get("/api/lyric_video/task_status")
def api_get_lyric_video_status(task_id: str):
    """轮询动效短视频渲染进度"""
    task = _lyric_video_tasks.get(task_id)
    if not task:
        raise HTTPException(404, f"未找到短视频任务: {task_id}")
    return task


# ── ComfyUI 本地视频生成与多 Take 调度端点 ────────────────
class ComfyUIGenerateRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    shot_id: str = Field(..., description="Shot ID，如 shot_001")
    model_type: str = Field(default="ltx_video", description="模型类型: ltx_video, wan21_t2v, flux_schnell")
    resolution: str = Field(default="768x512", description="分辨率，如 768x512, 832x480, 1280x720")
    steps: int = Field(default=20, ge=1, le=100, description="采样步数")
    seed: int | None = Field(default=None, description="随机种子")


class ComfyUISelectTakeRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    shot_id: str = Field(..., description="Shot ID")
    take_id: str = Field(..., description="Take ID")


class ComfyUIDeleteTakeRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    shot_id: str = Field(..., description="Shot ID")
    take_id: str = Field(..., description="Take ID")


class ComfyUIKeyframeRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    shot_id: str = Field(..., description="Shot ID，如 shot_001")
    resolution: str = Field(default="768x448", description="分辨率")
    steps: int = Field(default=4, ge=1, le=50, description="FLUX 采样步数")
    seed: int | None = Field(default=None, description="随机种子")


class ComfyUII2VRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    shot_id: str = Field(..., description="Shot ID，如 shot_001")
    keyframe_path: str | None = Field(default=None, description="首帧图片路径 (留空使用当前分镜 preview_image)")
    resolution: str = Field(default="768x448", description="分辨率")
    steps: int = Field(default=20, ge=1, le=100, description="采样步数")
    seed: int | None = Field(default=None, description="随机种子")


class ComfyUITwoStageRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    shot_id: str = Field(..., description="Shot ID，如 shot_001")
    resolution: str = Field(default="768x448", description="分辨率")
    keyframe_steps: int = Field(default=4, ge=1, le=50, description="FLUX 首帧采样步数")
    video_steps: int = Field(default=20, ge=1, le=100, description="LTX 视频采样步数")
    seed: int | None = Field(default=None, description="随机种子")


class ComfyUIEndframeRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    shot_id: str = Field(..., description="Shot ID，如 shot_001")
    resolution: str = Field(default="768x448", description="分辨率")
    steps: int = Field(default=4, ge=1, le=50, description="FLUX 尾帧采样步数")
    seed: int | None = Field(default=None, description="随机种子")


class LinkOneTakeRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    from_shot_id: str = Field(..., description="源分镜 ID (提供尾帧)")
    to_shot_id: str = Field(..., description="目标分镜 ID (继承首帧)")


_comfyui_tasks: dict[str, dict[str, Any]] = {}


@app.get("/api/comfyui/status")
def get_comfyui_status():
    """获取本地 ComfyUI 在线状态、显存使用率与可用模型清单"""
    client = get_comfyui_client()
    health = client.check_health()

    models = []
    if client.comfy_dir.exists():
        # Check checkpoints
        ckpt_dir = client.comfy_dir / "models" / "checkpoints"
        if ckpt_dir.exists():
            for f in ckpt_dir.glob("*.safetensors"):
                models.append({
                    "type": "checkpoint",
                    "name": f.name,
                    "id": "ltx_video" if "ltx" in f.name.lower() else f.stem,
                    "title": "LTX-Video 2B (极速物理视频)" if "ltx" in f.name.lower() else f.stem,
                })
        # Check diffusion_models
        diff_dir = client.comfy_dir / "models" / "diffusion_models"
        if diff_dir.exists():
            for f in diff_dir.glob("*.safetensors"):
                models.append({
                    "type": "diffusion_model",
                    "name": f.name,
                    "id": "wan21_t2v" if "wan" in f.name.lower() else f.stem,
                    "title": "Wan 2.1 1.3B (通义万相写实)" if "wan" in f.name.lower() else f.stem,
                })
        # Check unet
        unet_dir = client.comfy_dir / "models" / "unet"
        if unet_dir.exists():
            for f in unet_dir.glob("*.gguf"):
                models.append({
                    "type": "unet_gguf",
                    "name": f.name,
                    "id": "flux_schnell" if "flux" in f.name.lower() else f.stem,
                    "title": "FLUX.1 Schnell (4步极速高清)" if "flux" in f.name.lower() else f.stem,
                })

    return {
        "health": health,
        "models": models,
        "default_model": "ltx_video",
    }


@app.post("/api/comfyui/start")
def start_comfyui_server():
    """一键尝试拉起本地 ComfyUI 服务"""
    client = get_comfyui_client()
    ok = client.ensure_server_running(timeout_sec=20)
    return {"status": "ok" if ok else "failed", "online": ok}


@app.post("/api/comfyui/generate_take")
def generate_comfyui_take(req: ComfyUIGenerateRequest):
    """为指定分镜生成新的 Take 候选视频/图像"""
    p = _validate_path(Path(req.json_path))
    if not p.exists():
        raise HTTPException(404, f"找不到 alignment 文件: {p}")

    task_id = f"task_{uuid.uuid4().hex[:8]}"
    _comfyui_tasks[task_id] = {
        "status": "pending",
        "progress": 0.0,
        "message": "任务初始化中...",
        "shot_id": req.shot_id,
        "model_type": req.model_type,
        "take": None,
        "error": None,
    }

    def _worker():
        try:
            _comfyui_tasks[task_id]["status"] = "running"
            _comfyui_tasks[task_id]["progress"] = 5.0
            _comfyui_tasks[task_id]["message"] = "加载分镜工程..."

            proj = AlignmentProject.load_json(p)
            target_shot: ShotPlan | None = None
            for s in proj.storyboard:
                if s.id == req.shot_id or str(s.shot_id) == str(req.shot_id):
                    target_shot = s
                    break

            if not target_shot:
                raise ValueError(f"未找到目标镜头: {req.shot_id}")

            client = get_comfyui_client()

            def _on_progress(prog: float, msg: str):
                _comfyui_tasks[task_id]["progress"] = prog
                _comfyui_tasks[task_id]["message"] = msg

            project_dir = p.parent
            take = client.generate_take_for_shot(
                shot=target_shot,
                project_dir=project_dir,
                model_type=req.model_type,
                bibles=getattr(proj, "bibles", None) or getattr(proj, "global_bibles", None),
                resolution=req.resolution,
                steps=req.steps,
                seed=req.seed,
                progress_callback=_on_progress,
            )

            # 更新镜头 Takes 候选池
            if target_shot.takes is None:
                target_shot.takes = []

            for t in target_shot.takes:
                t.selected = False

            target_shot.takes.append(take)
            target_shot.selected_take_id = take.id
            target_shot.path = take.media_path
            target_shot.type = take.media_type

            # 持久化回盘
            proj.save_json(p)

            _comfyui_tasks[task_id]["status"] = "completed"
            _comfyui_tasks[task_id]["progress"] = 100.0
            _comfyui_tasks[task_id]["message"] = f"Take {take.id} 生成成功！"
            _comfyui_tasks[task_id]["take"] = take.model_dump()
            log.info("ComfyUI Take 成功写入分镜: %s -> %s", req.shot_id, take.id)

        except Exception as e:
            log.exception("ComfyUI Take 生成失败: %s", e)
            _comfyui_tasks[task_id]["status"] = "failed"
            _comfyui_tasks[task_id]["error"] = str(e)
            _comfyui_tasks[task_id]["message"] = f"生成失败: {e}"

    threading.Thread(target=_worker, daemon=True).start()
    return {"task_id": task_id, "status": "pending"}


@app.post("/api/comfyui/generate_keyframe")
def generate_comfyui_keyframe(req: ComfyUIKeyframeRequest):
    """为指定分镜生成 FLUX 高清电影首帧 (Keyframe)"""
    p = _validate_path(Path(req.json_path))
    if not p.exists():
        raise HTTPException(404, f"找不到 alignment 文件: {p}")

    task_id = f"task_{uuid.uuid4().hex[:8]}"
    _comfyui_tasks[task_id] = {
        "status": "pending",
        "progress": 0.0,
        "message": "首帧生成任务初始化中...",
        "shot_id": req.shot_id,
        "type": "keyframe",
        "keyframe_path": None,
        "error": None,
    }

    def _worker():
        try:
            _comfyui_tasks[task_id]["status"] = "running"
            _comfyui_tasks[task_id]["progress"] = 5.0
            _comfyui_tasks[task_id]["message"] = "读取分镜工程..."

            proj = AlignmentProject.load_json(p)
            target_shot: ShotPlan | None = None
            for s in proj.storyboard:
                if s.id == req.shot_id or str(s.shot_id) == str(req.shot_id):
                    target_shot = s
                    break

            if not target_shot:
                raise ValueError(f"未找到目标镜头: {req.shot_id}")

            client = get_comfyui_client()

            def _on_progress(prog: float, msg: str):
                _comfyui_tasks[task_id]["progress"] = prog
                _comfyui_tasks[task_id]["message"] = msg

            project_dir = p.parent
            kf_path = client.generate_keyframe_for_shot(
                shot=target_shot,
                project_dir=project_dir,
                bibles=getattr(proj, "bibles", None) or getattr(proj, "global_bibles", None),
                resolution=req.resolution,
                steps=req.steps,
                seed=req.seed,
                progress_callback=_on_progress,
            )

            target_shot.preview_image = kf_path
            if not target_shot.path:
                target_shot.path = kf_path
                target_shot.type = "image"

            proj.save_json(p)

            _comfyui_tasks[task_id]["status"] = "completed"
            _comfyui_tasks[task_id]["progress"] = 100.0
            _comfyui_tasks[task_id]["message"] = "电影级首帧生成成功！"
            _comfyui_tasks[task_id]["keyframe_path"] = kf_path
            log.info("ComfyUI 首帧生成成功: %s -> %s", req.shot_id, kf_path)

        except Exception as e:
            log.exception("ComfyUI 首帧生成失败: %s", e)
            _comfyui_tasks[task_id]["status"] = "failed"
            _comfyui_tasks[task_id]["error"] = str(e)
            _comfyui_tasks[task_id]["message"] = f"首帧生成失败: {e}"

    threading.Thread(target=_worker, daemon=True).start()
    return {"task_id": task_id, "status": "pending"}


@app.post("/api/comfyui/generate_i2v_take")
def generate_comfyui_i2v_take(req: ComfyUII2VRequest):
    """以首帧图为锚点，运行 LTX-Video I2V 生成动态视频 Take"""
    p = _validate_path(Path(req.json_path))
    if not p.exists():
        raise HTTPException(404, f"找不到 alignment 文件: {p}")

    task_id = f"task_{uuid.uuid4().hex[:8]}"
    _comfyui_tasks[task_id] = {
        "status": "pending",
        "progress": 0.0,
        "message": "图生视频任务初始化中...",
        "shot_id": req.shot_id,
        "type": "i2v_video",
        "take": None,
        "error": None,
    }

    def _worker():
        try:
            _comfyui_tasks[task_id]["status"] = "running"
            _comfyui_tasks[task_id]["progress"] = 5.0
            _comfyui_tasks[task_id]["message"] = "读取分镜工程..."

            proj = AlignmentProject.load_json(p)
            target_shot: ShotPlan | None = None
            for s in proj.storyboard:
                if s.id == req.shot_id or str(s.shot_id) == str(req.shot_id):
                    target_shot = s
                    break

            if not target_shot:
                raise ValueError(f"未找到目标镜头: {req.shot_id}")

            client = get_comfyui_client()

            def _on_progress(prog: float, msg: str):
                _comfyui_tasks[task_id]["progress"] = prog
                _comfyui_tasks[task_id]["message"] = msg

            project_dir = p.parent
            take = client.generate_i2v_take_for_shot(
                shot=target_shot,
                project_dir=project_dir,
                keyframe_path=req.keyframe_path,
                bibles=getattr(proj, "bibles", None) or getattr(proj, "global_bibles", None),
                resolution=req.resolution,
                steps=req.steps,
                seed=req.seed,
                progress_callback=_on_progress,
            )

            if target_shot.takes is None:
                target_shot.takes = []
            for t in target_shot.takes:
                t.selected = False

            target_shot.takes.append(take)
            target_shot.selected_take_id = take.id
            target_shot.path = take.media_path
            target_shot.type = take.media_type

            proj.save_json(p)

            _comfyui_tasks[task_id]["status"] = "completed"
            _comfyui_tasks[task_id]["progress"] = 100.0
            _comfyui_tasks[task_id]["message"] = f"Take {take.id} 生成成功！"
            _comfyui_tasks[task_id]["take"] = take.model_dump()
            log.info("ComfyUI I2V Take 成功写入分镜: %s -> %s", req.shot_id, take.id)

        except Exception as e:
            log.exception("ComfyUI I2V Take 生成失败: %s", e)
            _comfyui_tasks[task_id]["status"] = "failed"
            _comfyui_tasks[task_id]["error"] = str(e)
            _comfyui_tasks[task_id]["message"] = f"生成失败: {e}"

    threading.Thread(target=_worker, daemon=True).start()
    return {"task_id": task_id, "status": "pending"}


@app.post("/api/comfyui/generate_two_stage")
def generate_comfyui_two_stage(req: ComfyUITwoStageRequest):
    """一键执行两阶段：FLUX 首帧 + LTX-I2V 动态视频"""
    p = _validate_path(Path(req.json_path))
    if not p.exists():
        raise HTTPException(404, f"找不到 alignment 文件: {p}")

    task_id = f"task_{uuid.uuid4().hex[:8]}"
    _comfyui_tasks[task_id] = {
        "status": "pending",
        "progress": 0.0,
        "message": "两阶段任务初始化中...",
        "shot_id": req.shot_id,
        "type": "two_stage",
        "keyframe_path": None,
        "take": None,
        "error": None,
    }

    def _worker():
        try:
            _comfyui_tasks[task_id]["status"] = "running"
            _comfyui_tasks[task_id]["progress"] = 5.0
            _comfyui_tasks[task_id]["message"] = "读取分镜工程..."

            proj = AlignmentProject.load_json(p)
            target_shot: ShotPlan | None = None
            for s in proj.storyboard:
                if s.id == req.shot_id or str(s.shot_id) == str(req.shot_id):
                    target_shot = s
                    break

            if not target_shot:
                raise ValueError(f"未找到目标镜头: {req.shot_id}")

            client = get_comfyui_client()

            def _on_progress(prog: float, msg: str):
                _comfyui_tasks[task_id]["progress"] = prog
                _comfyui_tasks[task_id]["message"] = msg

            project_dir = p.parent
            kf_path, take = client.generate_two_stage_take(
                shot=target_shot,
                project_dir=project_dir,
                bibles=getattr(proj, "bibles", None) or getattr(proj, "global_bibles", None),
                resolution=req.resolution,
                video_steps=req.video_steps,
                keyframe_steps=req.keyframe_steps,
                seed=req.seed,
                progress_callback=_on_progress,
            )

            target_shot.preview_image = kf_path
            if target_shot.takes is None:
                target_shot.takes = []
            for t in target_shot.takes:
                t.selected = False

            target_shot.takes.append(take)
            target_shot.selected_take_id = take.id
            target_shot.path = take.media_path
            target_shot.type = take.media_type

            proj.save_json(p)

            _comfyui_tasks[task_id]["status"] = "completed"
            _comfyui_tasks[task_id]["progress"] = 100.0
            _comfyui_tasks[task_id]["message"] = f"两阶段完成！Take {take.id} 生成成功"
            _comfyui_tasks[task_id]["keyframe_path"] = kf_path
            _comfyui_tasks[task_id]["take"] = take.model_dump()
            log.info("ComfyUI 两阶段成功: %s -> kf:%s, take:%s", req.shot_id, kf_path, take.id)

        except Exception as e:
            log.exception("ComfyUI 两阶段执行失败: %s", e)
            _comfyui_tasks[task_id]["status"] = "failed"
            _comfyui_tasks[task_id]["error"] = str(e)
            _comfyui_tasks[task_id]["message"] = f"生成失败: {e}"

    threading.Thread(target=_worker, daemon=True).start()
    return {"task_id": task_id, "status": "pending"}


@app.post("/api/comfyui/generate_endframe")
def generate_comfyui_endframe(req: ComfyUIEndframeRequest):
    """为指定分镜生成 FLUX 尾帧 (Endframe)，用于一镜到底与首尾帧无缝切换"""
    p = _validate_path(Path(req.json_path))
    if not p.exists():
        raise HTTPException(404, f"找不到 alignment 文件: {p}")

    task_id = f"task_{uuid.uuid4().hex[:8]}"
    _comfyui_tasks[task_id] = {
        "status": "pending",
        "progress": 0.0,
        "message": "尾帧生成任务初始化中...",
        "shot_id": req.shot_id,
        "type": "endframe",
        "endframe_path": None,
        "error": None,
    }

    def _worker():
        try:
            _comfyui_tasks[task_id]["status"] = "running"
            _comfyui_tasks[task_id]["progress"] = 10.0
            _comfyui_tasks[task_id]["message"] = "读取分镜工程..."

            proj = AlignmentProject.load_json(p)
            target_shot: ShotPlan | None = None
            for s in proj.storyboard:
                if s.id == req.shot_id or str(s.shot_id) == str(req.shot_id):
                    target_shot = s
                    break

            if not target_shot:
                raise ValueError(f"未找到目标镜头: {req.shot_id}")

            client = get_comfyui_client()

            def _on_progress(prog: float, msg: str):
                _comfyui_tasks[task_id]["progress"] = prog
                _comfyui_tasks[task_id]["message"] = msg

            project_dir = p.parent
            ef_path = client.generate_endframe_for_shot(
                shot=target_shot,
                project_dir=project_dir,
                bibles=getattr(proj, "bibles", None) or getattr(proj, "global_bibles", None),
                resolution=req.resolution,
                steps=req.steps,
                seed=req.seed,
                progress_callback=_on_progress,
            )

            target_shot.endframe_image = ef_path
            proj.save_json(p)

            _comfyui_tasks[task_id]["status"] = "completed"
            _comfyui_tasks[task_id]["progress"] = 100.0
            _comfyui_tasks[task_id]["message"] = "电影尾帧生成成功！"
            _comfyui_tasks[task_id]["endframe_path"] = ef_path
            log.info("ComfyUI 尾帧生成成功: %s -> %s", req.shot_id, ef_path)

        except Exception as e:
            log.exception("ComfyUI 尾帧生成失败: %s", e)
            _comfyui_tasks[task_id]["status"] = "failed"
            _comfyui_tasks[task_id]["error"] = str(e)
            _comfyui_tasks[task_id]["message"] = f"尾帧生成失败: {e}"

    threading.Thread(target=_worker, daemon=True).start()
    return {"task_id": task_id, "status": "pending"}


@app.post("/api/shots/link_one_take")
def link_one_take(req: LinkOneTakeRequest):
    """一镜到底无缝绑定：将前一镜头的尾帧 (或当前首帧) 传递给后一镜头的首帧"""
    p = _validate_path(Path(req.json_path))
    proj = AlignmentProject.load_json(p)

    from_shot: ShotPlan | None = None
    to_shot: ShotPlan | None = None
    for s in proj.storyboard:
        if s.id == req.from_shot_id or str(s.shot_id) == str(req.from_shot_id):
            from_shot = s
        if s.id == req.to_shot_id or str(s.shot_id) == str(req.to_shot_id):
            to_shot = s

    if not from_shot:
        raise HTTPException(404, f"未找到源镜头: {req.from_shot_id}")
    if not to_shot:
        raise HTTPException(404, f"未找到目标镜头: {req.to_shot_id}")

    # 获取源镜头的尾帧或首帧
    inherited_image = from_shot.endframe_image or from_shot.preview_image
    if not inherited_image:
        raise HTTPException(400, f"源镜头 {from_shot.id} 尚无可用尾帧或首帧图像，请先生成！")

    to_shot.preview_image = inherited_image
    to_shot.path = inherited_image
    to_shot.type = "image"
    from_shot.continuity_mode = "one_take_continuous"
    from_shot.outgoing_transition = None  # 一镜到底无缝连接，无需传统剪辑黑场
    proj.save_json(p)

    log.info("一镜到底绑定成功: %s -> %s, 继承图像: %s", from_shot.id, to_shot.id, inherited_image)
    return {
        "status": "ok",
        "from_shot_id": from_shot.id,
        "to_shot_id": to_shot.id,
        "inherited_image": inherited_image,
    }


@app.get("/api/comfyui/task_status")
def get_comfyui_task_status(task_id: str):
    """轮询 ComfyUI 视频生成任务进度"""
    task = _comfyui_tasks.get(task_id)
    if not task:
        raise HTTPException(404, f"未找到任务: {task_id}")
    return task


@app.post("/api/comfyui/select_take")
def select_comfyui_take(req: ComfyUISelectTakeRequest):
    """选定指定 Take 作为正片播放素材"""
    p = _validate_path(Path(req.json_path))
    proj = AlignmentProject.load_json(p)
    target_shot = None
    for s in proj.storyboard:
        if s.id == req.shot_id or str(s.shot_id) == str(req.shot_id):
            target_shot = s
            break

    if not target_shot:
        raise HTTPException(404, f"未找到分镜: {req.shot_id}")

    matched_take = None
    for t in (target_shot.takes or []):
        if t.id == req.take_id:
            t.selected = True
            matched_take = t
        else:
            t.selected = False

    if not matched_take:
        raise HTTPException(404, f"分镜 {req.shot_id} 中未找到 Take {req.take_id}")

    target_shot.selected_take_id = matched_take.id
    target_shot.path = matched_take.media_path
    target_shot.type = matched_take.media_type
    proj.save_json(p)

    return {"status": "ok", "selected_take_id": matched_take.id}


@app.delete("/api/comfyui/delete_take")
def delete_comfyui_take(req: ComfyUIDeleteTakeRequest):
    """删除指定 Take 候选"""
    p = _validate_path(Path(req.json_path))
    proj = AlignmentProject.load_json(p)
    target_shot = None
    for s in proj.storyboard:
        if s.id == req.shot_id or str(s.shot_id) == str(req.shot_id):
            target_shot = s
            break

    if not target_shot or not target_shot.takes:
        raise HTTPException(404, f"未找到分镜或 Takes 为空: {req.shot_id}")

    target_shot.takes = [t for t in target_shot.takes if t.id != req.take_id]

    if target_shot.selected_take_id == req.take_id:
        if target_shot.takes:
            target_shot.takes[0].selected = True
            target_shot.selected_take_id = target_shot.takes[0].id
            target_shot.path = target_shot.takes[0].media_path
            target_shot.type = target_shot.takes[0].media_type
        else:
            target_shot.selected_take_id = None
            target_shot.path = target_shot.preview_image or ""
            target_shot.type = "image"

    proj.save_json(p)
    return {"status": "ok"}



# ── 静态文件: 从 frontend/local/ 目录提供 HTML/CSS/JS ──
_FRONTEND_DIR = _PROJECT_ROOT / "frontend" / "local"

from fastapi.staticfiles import StaticFiles
if _FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="local-static")

@app.get("/", response_class=HTMLResponse)
def index():
    index_file = _FRONTEND_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>frontend/local/index.html 不存在</h1>", status_code=500)


@app.get("/storyboard", response_class=HTMLResponse)
def storyboard():
    sb_file = _FRONTEND_DIR / "storyboard.html"
    if sb_file.exists():
        return HTMLResponse(sb_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>frontend/local/storyboard.html 不存在</h1>", status_code=500)


@app.get("/motion", response_class=HTMLResponse)
@app.get("/motion_studio", response_class=HTMLResponse)
@app.get("/motion_studio.html", response_class=HTMLResponse)
@app.get("/motion_studio_director.html", response_class=HTMLResponse)
def motion_studio():
    ms_file = _FRONTEND_DIR / "motion_studio_director.html"
    if not ms_file.exists():
        ms_file = _FRONTEND_DIR / "motion_studio.html"
    if ms_file.exists():
        html = ms_file.read_text(encoding="utf-8")
        for url, asset in (("/motion/studio.js", _FRONTEND_DIR / "motion" / "studio.js"),
                           ("/motion-lab.css", _FRONTEND_DIR / "motion-lab.css")):
            if asset.exists():
                version = hashlib.sha256(asset.read_bytes()).hexdigest()[:16]
                html = html.replace(f'{url}"', f'{url}?v={version}"')
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
    return HTMLResponse("<h1>frontend/local/motion_studio.html 不存在</h1>", status_code=500)


@app.get("/gallery", response_class=HTMLResponse)
@app.get("/gallery.html", response_class=HTMLResponse)
@app.get("/videos", response_class=HTMLResponse)
@app.get("/videos.html", response_class=HTMLResponse)
def gallery_view():
    g_file = _FRONTEND_DIR / "gallery.html"
    if g_file.exists():
        return HTMLResponse(g_file.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})
    return HTMLResponse("<h1>frontend/local/gallery.html 不存在</h1>", status_code=500)


def _find_audio(stem: str, song_output_dir: Path | None = None) -> Path | None:
    """在 input/{song_name}/ 和 output/{song_name}/ 专属子目录中查找原音频"""
    scan_dir = _get_scan_dir()
    exts = [".wav", ".mp3", ".flac", ".m4a", ".ogg"]
    
    song_name = song_output_dir.name if song_output_dir else stem
    search_dirs = [
        scan_dir.parent / "input" / song_name,
    ]
    if song_output_dir and song_output_dir.exists():
        search_dirs.append(song_output_dir)
    else:
        search_dirs.append(scan_dir / song_name)

    for d in search_dirs:
        if not d.exists():
            continue
        for target in [stem, song_name]:
            for ext in exts:
                p = d / f"{target}{ext}"
                if p.exists():
                    return p
    return None


def _find_audio_tracks(stem: str, song_output_dir: Path | None = None) -> dict[str, str]:
    """在 output/{song_name}/ 或 input/{song_name}/ 专属子目录中查找分离后的 vocals 与 instrumental 音轨"""
    scan_dir = _get_scan_dir()
    song_name = song_output_dir.name if song_output_dir else stem
    base_stem = stem.replace("_vocals", "").replace("_instrumental", "")

    search_dirs = []
    if song_output_dir and song_output_dir.exists():
        search_dirs.append(song_output_dir)
    else:
        search_dirs.append(scan_dir / song_name)
    search_dirs.append(scan_dir.parent / "input" / song_name)

    tracks = {}
    for d in search_dirs:
        if not d.exists():
            continue
        for ext in [".wav", ".mp3", ".flac", ".m4a"]:
            for name_prefix in [stem, base_stem, song_name]:
                v = d / f"{name_prefix}_vocals{ext}"
                if v.exists() and "vocals" not in tracks:
                    tracks["vocals"] = str(v)
                inst = d / f"{name_prefix}_instrumental{ext}"
                if inst.exists() and "instrumental" not in tracks:
                    tracks["instrumental"] = str(inst)
    return tracks


# ======================================================================
# 启动
# ======================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.local_editor",
        description="本地时间轴编辑器（轻量 FastAPI，无数据库）",
    )
    parser.add_argument("--dir", "-d", default=DEFAULT_DIR,
                        help=f"alignment.json 所在目录，默认: {DEFAULT_DIR}")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--config-file",
        default=None,
        help="可选配置文件 (.toml/.json)，读取 [subtitle] 字段用于本地重生 ASS",
    )
    parser.add_argument("--no-browser", action="store_true",
                        help="不自动打开浏览器")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scan_dir = Path(args.dir).expanduser().resolve()
    if not scan_dir.exists():
        print(f"[警告] 目录不存在，将创建: {scan_dir}")
        scan_dir.mkdir(parents=True, exist_ok=True)
    app.state.scan_dir = scan_dir

    config_path = Path(args.config_file).expanduser().resolve() if args.config_file else None
    try:
        subtitle_config = (
            PipelineConfig.from_file(config_path).subtitle
            if config_path
            else SubtitleConfig()
        )
    except Exception as e:
        print(f"[错误] 配置文件加载失败: {e}")
        raise SystemExit(1)
    app.state.subtitle_config = subtitle_config

    url = f"http://{args.host}:{args.port}"
    print(f"M2V 本地编辑器启动: {url}")
    print(f"扫描目录: {scan_dir}")
    if config_path:
        print(f"字幕配置: {config_path}")
    print("Ctrl+C 退出")

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")




# The studio shares this editor's song paths and audio API.
from src.motion_api import create_motion_router
app.include_router(create_motion_router(_get_scan_dir, _validate_path, _find_audio))

from src.bilibili_uploader import bilibili_router
app.include_router(bilibili_router)

from src.xiaohongshu_uploader import xiaohongshu_router
app.include_router(xiaohongshu_router)

from src.wechat_uploader import wechat_router
app.include_router(wechat_router)

from src.douyin_uploader import douyin_router
app.include_router(douyin_router)

from src.youtube_uploader import youtube_router
app.include_router(youtube_router)

from src.syndication_manager import syndication_router
app.include_router(syndication_router)

from src.session_manager import issue_session_token

@app.post("/api/session/init")
def init_session_endpoint():
    """签发防篡改服务端 HMAC 签名会话凭据"""
    import time
    token = issue_session_token()
    return {"session_token": token, "session_id": token, "created_at": time.time()}

@app.get("/motion_lab", response_class=HTMLResponse)
def motion_lab():
    return HTMLResponse((_FRONTEND_DIR / "motion_lab.html").read_text(encoding="utf-8"))

@app.get("/motion-lab.css")
def motion_styles():
    return FileResponse(_FRONTEND_DIR / "motion-lab.css", media_type="text/css")

@app.get("/motion/{asset}")
def motion_asset(asset: str):
    if asset not in ("lab.js", "studio.js", "render-entry.js", "lab.js.LEGAL.txt", "studio.js.LEGAL.txt", "render-entry.js.LEGAL.txt"):
        raise HTTPException(404, "文件不存在")
    path = _FRONTEND_DIR / "motion" / asset
    if not path.exists(): raise HTTPException(503, "动效前端尚未构建")
    return FileResponse(path)


if __name__ == "__main__":
    main()
