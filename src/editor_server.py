"""
卡拉OK 时间轴编辑器 — FastAPI 后端

启动方式:
    python -m src.editor_server --input ./input --output ./output --port 8765
    或: m2v edit --port 8765
"""

from __future__ import annotations

import argparse
import json
import shutil
import webbrowser
from pathlib import Path

from src.utils import log

# ---------------------------------------------------------------------------
# FastAPI app (延迟导入，避免未安装时报错)
# ---------------------------------------------------------------------------

def create_app(input_dir: Path, output_dir: Path) -> "FastAPI":
    """创建并配置 FastAPI 应用"""
    try:
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError:
        raise ImportError(
            "编辑器需要 FastAPI。请运行:\n"
            "  pip install fastapi uvicorn[standard]\n"
            "  或: pip install -e '.[editor]'"
        )

    app = FastAPI(title="M2V Timeline Editor")

    # 存储目录路径
    app.state.input_dir = input_dir
    app.state.output_dir = output_dir

    # --- API ---

    @app.get("/api/songs")
    async def list_songs():
        """列出所有可编辑的歌曲"""
        songs = []
        for align_file in output_dir.glob("*_alignment.json"):
            stem = align_file.name.replace("_alignment.json", "")
            # 查找音频
            audio = _find_audio(input_dir, output_dir, stem)
            # 读取行数
            try:
                data = json.loads(align_file.read_text(encoding="utf-8"))
                lines_count = len(data.get("lines", []))
                last_line = data["lines"][-1] if data.get("lines") else {}
                duration = last_line.get("end", 0)
            except Exception:
                lines_count = 0
                duration = 0

            songs.append({
                "stem": stem,
                "has_alignment": True,
                "has_audio": audio is not None,
                "lines_count": lines_count,
                "duration": round(duration, 1),
            })
        return songs

    @app.get("/api/songs/{stem}/align")
    async def get_alignment(stem: str):
        """获取对齐 JSON"""
        path = output_dir / f"{stem}_alignment.json"
        if not path.exists():
            raise HTTPException(404, f"未找到: {stem}_alignment.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        return data

    @app.put("/api/songs/{stem}/align")
    async def save_alignment(stem: str, request: Request):
        """保存编辑后的对齐 JSON (带校验)"""
        path = output_dir / f"{stem}_alignment.json"
        if not path.exists():
            raise HTTPException(404, f"未找到: {stem}_alignment.json")

        try:
            data = await request.json()
        except Exception:
            raise HTTPException(400, "无效的 JSON")

        # 校验
        errors = _validate_alignment(data)
        if errors:
            raise HTTPException(422, {"errors": errors})

        # 备份
        bak_path = path.with_suffix(".json.bak")
        shutil.copy2(path, bak_path)

        # 写入
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("对齐 JSON 已保存: %s (备份: %s)", path.name, bak_path.name)
        return {"status": "ok", "backup": bak_path.name}

    @app.get("/api/songs/{stem}/audio")
    async def get_audio(stem: str):
        """流式返回音频文件"""
        audio = _find_audio(input_dir, output_dir, stem)
        if audio is None:
            raise HTTPException(404, f"未找到音频: {stem}")
        media_type = "audio/mpeg" if audio.suffix == ".mp3" else "audio/wav"
        return FileResponse(audio, media_type=media_type)

    @app.post("/api/songs/{stem}/regen")
    async def regenerate(stem: str, request: Request):
        """从编辑后 JSON 重新生成 ASS / MP4"""
        body = await request.json()
        mode = body.get("mode", "ass")

        align_path = output_dir / f"{stem}_alignment.json"
        if not align_path.exists():
            raise HTTPException(404, f"未找到: {stem}_alignment.json")

        audio = _find_audio(input_dir, output_dir, stem)

        try:
            from src.aligner import AlignmentResult
            from src.subtitle import generate_ass
            from src.config import SubtitleConfig, CompositorConfig

            alignment = AlignmentResult.load_json(align_path)
            ass_path = output_dir / f"{stem}.ass"
            generate_ass(
                alignment=alignment,
                output_path=ass_path,
                audio_path=audio,
            )

            if mode == "video" and audio:
                from src.compositor import compose_video
                mp4_path = output_dir / f"{stem}.mp4"
                compose_video(
                    audio_path=audio,
                    subtitle_path=ass_path,
                    output_path=mp4_path,
                    config=CompositorConfig(),
                )
                return {"status": "ok", "file": mp4_path.name, "mode": "video"}

            return {"status": "ok", "file": ass_path.name, "mode": "ass"}

        except Exception as e:
            log.error("重新生成失败: %s", e, exc_info=True)
            raise HTTPException(500, str(e))

    # --- 前端静态文件 ---
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def _validate_alignment(data: dict) -> list[str]:
    """校验 alignment JSON — 仅检查致命错误，宽松容忍编辑偏差"""
    errors = []
    lines = data.get("lines")
    if not isinstance(lines, list):
        return ["'lines' 必须是数组"]

    for i, line in enumerate(lines):
        words = line.get("words", [])
        if not words:
            errors.append(f"第 {i+1} 行: words 为空")
            continue

        # 自动修正 line.start/end 与首末字一致
        line["start"] = words[0].get("start", line.get("start", 0))
        line["end"] = words[-1].get("end", line.get("end", 0))

        # 时间值非负
        for j, w in enumerate(words):
            if w.get("start", 0) < -0.01 or w.get("end", 0) < -0.01:
                errors.append(f"第 {i+1} 行第 {j+1} 字: 时间值 < 0")

        # 字 end < start 检查
        for j, w in enumerate(words):
            if w.get("end", 0) < w.get("start", 0) - 0.01:
                errors.append(
                    f"第 {i+1} 行第 {j+1} 字 '{w.get('word','')}': "
                    f"end({w.get('end',0):.3f}) < start({w.get('start',0):.3f})"
                )

    return errors[:20]  # 最多返回 20 个错误


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _find_audio(input_dir: Path, output_dir: Path, stem: str) -> Path | None:
    """查找音频文件 (优先 vocals.wav → input mp3)"""
    for d in [output_dir, input_dir]:
        for ext in [".wav", ".mp3", ".flac"]:
            p = d / f"{stem}{ext}"
            if p.exists():
                return p
        # 也检查 vocals 文件
        for ext in [".wav", ".mp3"]:
            p = d / f"{stem}_vocals{ext}"
            if p.exists():
                return p
    return None


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def run_editor(
    input_dir: Path,
    output_dir: Path,
    port: int = 8765,
    host: str = "127.0.0.1",
) -> None:
    """启动编辑器服务"""
    try:
        import uvicorn
    except ImportError:
        raise ImportError(
            "编辑器需要 uvicorn。请运行:\n"
            "  pip install uvicorn[standard]"
        )

    app = create_app(input_dir, output_dir)
    url = f"http://{host}:{port}"
    log.info("启动时间轴编辑器: %s", url)
    log.info("输入目录: %s", input_dir)
    log.info("输出目录: %s", output_dir)

    # 自动打开浏览器
    import threading
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")


def main() -> None:
    parser = argparse.ArgumentParser(description="M2V Timeline Editor")
    parser.add_argument("--input", "-i", default="./input", help="输入目录")
    parser.add_argument("--output", "-o", default="./output", help="输出目录")
    parser.add_argument("--port", "-p", type=int, default=8765, help="端口")
    parser.add_argument("--host", default="127.0.0.1", help="主机")
    args = parser.parse_args()

    run_editor(
        input_dir=Path(args.input),
        output_dir=Path(args.output),
        port=args.port,
        host=args.host,
    )


if __name__ == "__main__":
    main()
