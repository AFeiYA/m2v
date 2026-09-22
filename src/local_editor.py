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
import json
import shutil
import threading
import webbrowser
from pathlib import Path
from typing import Literal

import uvicorn
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse

from src.storyboard_schema import (
    AlignmentProject,
    AlignmentResult,
    AlignedLine,
    MusicSection,
    ShotPlan,
    WordTimestamp,
)
from src.subtitle import generate_ass
from src.config import PipelineConfig, SubtitleConfig
from src.utils import log

# ── 默认值 ────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR   = str(_PROJECT_ROOT / "output")
DEFAULT_HOST  = "127.0.0.1"
DEFAULT_PORT  = 8000
# ─────────────────────────────────────────────────────────

app = FastAPI(title="M2V 本地编辑器", docs_url=None, redoc_url=None)


# ======================================================================
# API 数据模型 (Pydantic v2)
# ======================================================================

class SunoImportRequest(BaseModel):
    url: str = Field(..., description="Suno 歌曲分享链接")


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


def _validate_path(p: Path, must_exist: bool = True) -> Path:
    """校验路径在扫描目录内，防止任意文件读取"""
    scan_dir = _get_scan_dir()
    resolved = p.resolve()
    # 允许扫描目录本身及其父目录下的 input/ 目录
    allowed_roots = [scan_dir.resolve(), (scan_dir.parent / "input").resolve(), scan_dir.parent.resolve()]
    if not any(str(resolved).startswith(str(root)) for root in allowed_roots):
        raise HTTPException(403, f"路径越界: 仅允许访问项目目录内的文件")
    if must_exist and not resolved.exists():
        raise HTTPException(404, f"文件不存在: {resolved.name}")
    return resolved


# ======================================================================
# API
# ======================================================================

@app.post("/api/suno/import")
def import_suno_song(req: SunoImportRequest):
    """从 Suno 网址一键导入、自动分轨并完成词级时间轴对齐"""
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "Suno URL 不能为空")

    scan_dir = _get_scan_dir()
    input_dir = scan_dir.parent / "input"
    output_dir = scan_dir

    try:
        from src.suno_fetch import auto_process_suno
        result = auto_process_suno(
            url=url,
            input_dir=input_dir,
            output_dir=output_dir,
            launch_editor=False,
        )
        return result
    except Exception as e:
        log.error("Suno 导入失败: %s", e, exc_info=True)
        raise HTTPException(500, f"处理失败: {e}")


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


@app.get("/api/asset_file")
def get_asset_file(path: str):
    """提供素材文件流"""
    p = _validate_path(Path(path))
    return FileResponse(p)


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
    shutil.copy2(p, bak)
    project.save_json(p)

    log.info("保存完成: %s", p.name)
    return {"status": "ok", "backup": str(bak)}


class AutoDirectRequest(BaseModel):
    json_path: str = Field(..., description="alignment.json 路径")
    audio_path: str | None = Field(default=None, description="音频路径")


@app.post("/api/director/auto_direct")
def api_auto_direct(req: AutoDirectRequest):
    """
    一键运行 AI 导演与动态故事板 (Animatic) 生成流程
    """
    json_path = _validate_path(Path(req.json_path))
    project = AlignmentProject.load_json(json_path)

    # 查找可用音频
    song_dir = json_path.parent
    audio_path = None
    if req.audio_path:
        p = Path(req.audio_path)
        if p.exists():
            audio_path = p
    if not audio_path:
        stem = json_path.stem.replace("_alignment", "")
        audio_path = _find_audio(stem, song_output_dir=song_dir)

    analysis = None
    if audio_path and audio_path.exists():
        try:
            from src.audio_analyzer import analyze_audio_for_director
            drums_path = song_dir / f"{song_dir.name}_instrumental.wav"
            analysis = analyze_audio_for_director(
                audio_path=audio_path,
                drums_path=drums_path if drums_path.exists() else None,
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
    vocals_path = song_dir / f"{stem}_vocals.wav"
    if not vocals_path.exists():
        audio = _find_audio(stem, song_output_dir=song_dir)
        if audio is None:
            raise HTTPException(404, f"找不到人声文件: {stem}_vocals.wav")
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


@app.api_route("/api/audio", methods=["GET", "HEAD"])
def stream_audio(path: str):
    """提供音频文件流（支持 Range 请求）"""
    p = _validate_path(Path(path))
    suffix = p.suffix.lower()
    media_types = {".mp3": "audio/mpeg", ".wav": "audio/wav",
                   ".flac": "audio/flac", ".m4a": "audio/mp4", ".ogg": "audio/ogg"}
    media_type = media_types.get(suffix, "audio/mpeg")
    return FileResponse(p, media_type=media_type, headers={"Accept-Ranges": "bytes"})


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


if __name__ == "__main__":
    main()
