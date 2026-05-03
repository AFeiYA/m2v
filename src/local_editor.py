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

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from src.aligner import AlignmentResult
from src.subtitle import generate_ass
from src.config import SubtitleConfig
from src.utils import log

# ── 默认值 ────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR   = str(_PROJECT_ROOT / "output")
DEFAULT_HOST  = "127.0.0.1"
DEFAULT_PORT  = 8765
# ─────────────────────────────────────────────────────────

app = FastAPI(title="M2V 本地编辑器", docs_url=None, redoc_url=None)


# ======================================================================
# 路径安全校验
# ======================================================================

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

@app.get("/api/files")
def list_files():
    """列出目录内所有 *_alignment.json 文件"""
    scan_dir = _get_scan_dir()
    files = sorted(scan_dir.glob("*_alignment.json"))
    result = []
    for f in files:
        stem = f.stem.replace("_alignment", "")
        audio = _find_audio(stem)
        result.append({
            "name": stem,
            "json_path": str(f),
            "audio_path": str(audio) if audio else None,
        })
    return result


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
async def save_alignment(path: str, request: Request):
    """保存编辑后的 alignment.json（先备份）"""
    p = _validate_path(Path(path))
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "无效的 JSON")

    errors = _validate(data)
    if errors:
        raise HTTPException(422, {"errors": errors})

    bak = p.with_suffix(".json.bak")
    shutil.copy2(p, bak)

    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    log.info("保存完成: %s", p.name)
    return {"status": "ok", "backup": str(bak)}


@app.post("/api/regen")
async def regen_ass(request: Request):
    """从 alignment.json 重新生成 .ass"""
    body = await request.json()
    json_path = Path(body.get("json_path", ""))
    audio_path_str = body.get("audio_path") or ""

    if not json_path.exists():
        raise HTTPException(404, f"JSON 不存在: {json_path}")

    try:
        alignment = AlignmentResult.load_json(json_path)
        stem = json_path.stem.replace("_alignment", "")
        ass_path = json_path.parent / f"{stem}.ass"
        audio_path = Path(audio_path_str) if audio_path_str else None
        subtitle_config = getattr(app.state, "subtitle_config", SubtitleConfig())
        generate_ass(alignment, ass_path, subtitle_config, audio_path=audio_path)
        log.info("ASS 重新生成: %s", ass_path.name)
        return {"status": "ok", "ass_path": str(ass_path)}
    except Exception as e:
        log.error("重新生成失败: %s", e, exc_info=True)
        raise HTTPException(500, str(e))


@app.post("/api/realign")
async def realign(request: Request):
    """
    局部重对齐: 对 alignment JSON 中指定的行重新跑 WhisperX。

    请求体:
        json_path   : alignment JSON 文件路径
        line_indices: 要重对齐的行索引列表 (0-based)
        buffer      : 音频裁剪前后缓冲秒数，默认 2.0
    """
    from src.aligner import realign_lines

    body = await request.json()
    json_path = Path(body.get("json_path", ""))
    line_indices: list[int] = body.get("line_indices", [])
    buffer: float = float(body.get("buffer", 2.0))

    if not json_path.exists():
        raise HTTPException(404, f"JSON 不存在: {json_path}")
    if not line_indices:
        raise HTTPException(400, "line_indices 不能为空")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    lines = data.get("lines", [])

    invalid = [i for i in line_indices if i < 0 or i >= len(lines)]
    if invalid:
        raise HTTPException(400, f"索引越界: {invalid}，共 {len(lines)} 行")

    selected = [lines[i] for i in line_indices]
    rough_start = min(l["start"] for l in selected)
    rough_end   = max(l["end"]   for l in selected)
    texts       = [l["text"] for l in selected]

    # 优先用 {stem}_vocals.wav，找不到再用原始音频
    stem = json_path.stem.replace("_alignment", "")
    scan_dir = _get_scan_dir()
    vocals_path = scan_dir / f"{stem}_vocals.wav"
    if not vocals_path.exists():
        audio = _find_audio(stem)
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
            buffer=buffer,
        )
    except Exception as e:
        log.error("局部重对齐失败: %s", e, exc_info=True)
        raise HTTPException(500, str(e))

    for list_pos, orig_idx in enumerate(line_indices):
        if list_pos < len(new_lines):
            nl = new_lines[list_pos]
            lines[orig_idx] = {
                "text":  nl.text,
                "start": nl.start,
                "end":   nl.end,
                "words": [{"word": w.word, "start": w.start, "end": w.end}
                          for w in nl.words],
            }

    bak = json_path.with_suffix(".json.bak")
    shutil.copy2(json_path, bak)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    log.info("局部重对齐完成，已写回: %s", json_path.name)
    return {
        "status": "ok",
        "patched_indices": line_indices,
        "lines": [
            {"index": orig_idx, "start": lines[orig_idx]["start"],
             "end": lines[orig_idx]["end"], "text": lines[orig_idx]["text"]}
            for orig_idx in line_indices
        ],
    }


@app.get("/api/audio")
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


def _find_audio(stem: str) -> Path | None:
    scan_dir = _get_scan_dir()
    exts = [".wav", ".mp3", ".flac", ".m4a", ".ogg"]
    search_dirs = [scan_dir, scan_dir.parent / "input", scan_dir.parent]
    for d in search_dirs:
        for ext in exts:
            p = d / f"{stem}{ext}"
            if p.exists():
                return p
    return None


def _validate(data: dict) -> list[str]:
    errors = []
    lines = data.get("lines")
    if not isinstance(lines, list):
        return ["'lines' 必须是数组"]
    for i, line in enumerate(lines):
        words = line.get("words", [])
        if words:
            line["start"] = words[0].get("start", line.get("start", 0))
            line["end"] = words[-1].get("end", line.get("end", 0))
        for j, w in enumerate(words):
            if w.get("end", 0) < w.get("start", 0) - 0.01:
                errors.append(
                    f"第{i+1}行第{j+1}字'{w.get('word','')}': "
                    f"end({w.get('end',0):.2f}) < start({w.get('start',0):.2f})"
                )
    return errors[:20]


def _load_subtitle_config(config_path: Path | None) -> SubtitleConfig:
    """从 JSON / TOML 读取本地编辑器使用的 subtitle 配置。"""
    config = SubtitleConfig()
    if not config_path:
        return config

    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    suffix = config_path.suffix.lower()
    if suffix == ".toml":
        if tomllib is None:
            raise ValueError("当前 Python 环境不支持 TOML 解析，请使用 Python 3.11+ 或改用 .json 配置")
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    elif suffix == ".json":
        data = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        raise ValueError("配置文件仅支持 .toml 或 .json")

    subtitle_cfg = data.get("subtitle", {})
    if not isinstance(subtitle_cfg, dict):
        return config

    if subtitle_cfg.get("template_path"):
        template_path = Path(subtitle_cfg["template_path"]).expanduser()
        if not template_path.is_absolute():
            template_path = (config_path.parent / template_path).resolve()
        config.template_path = template_path
    if subtitle_cfg.get("style_name"):
        config.style_name = str(subtitle_cfg["style_name"])
    if subtitle_cfg.get("primary_colour"):
        config.primary_colour = str(subtitle_cfg["primary_colour"])
    if subtitle_cfg.get("secondary_colour"):
        config.secondary_colour = str(subtitle_cfg["secondary_colour"])
    if subtitle_cfg.get("outline_colour"):
        config.outline_colour = str(subtitle_cfg["outline_colour"])
    if subtitle_cfg.get("font_name"):
        config.font_name = str(subtitle_cfg["font_name"])
    if subtitle_cfg.get("font_size") is not None:
        config.font_size = int(subtitle_cfg["font_size"])
    if "enable_beat_effects" in subtitle_cfg:
        config.enable_beat_effects = bool(subtitle_cfg["enable_beat_effects"])
    if subtitle_cfg.get("beat_scale") is not None:
        config.beat_scale = float(subtitle_cfg["beat_scale"])

    return config



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
        subtitle_config = _load_subtitle_config(config_path)
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
