"""
Module 5: 视频合成器 (Cleaned)
- FFmpeg 命令构建与执行
- 背景高斯模糊 (Apple Style)
- 鲁棒性: 自动检测背景素材，不存在则回退
"""

from __future__ import annotations
import subprocess
from pathlib import Path
from src.config import CompositorConfig
from src.utils import log, check_ffmpeg

def compose_video(audio_path: Path, subtitle_path: Path, output_path: Path, background: Path | None = None, config: CompositorConfig | None = None) -> Path:
    if config is None: config = CompositorConfig()
    if not check_ffmpeg(): raise RuntimeError("FFmpeg 未安装")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = config.resolution
    
    # 路径鲁棒性检查
    bg_path = background if background else config.default_bg
    if bg_path and not bg_path.exists():
        log.warning("背景素材不存在: %s，将回退到纯黑背景", bg_path)
        bg_path = None

    is_image = bg_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp") if bg_path else False
    is_video = bg_path.suffix.lower() in (".mp4", ".avi", ".mov", ".mkv", ".webm") if bg_path else False

    if is_image: cmd = _build_image_bg_cmd(bg_path, audio_path, subtitle_path, output_path, config)
    elif is_video: cmd = _build_video_bg_cmd(bg_path, audio_path, subtitle_path, output_path, config)
    else: cmd = _build_black_bg_cmd(audio_path, subtitle_path, output_path, config)

    log.info("开始合成 (Apple Style): %s", output_path.name)
    _run_ffmpeg(cmd)
    return output_path

def _build_image_bg_cmd(bg_path: Path, audio_path: Path, subtitle_path: Path, output_path: Path, config: CompositorConfig) -> list[str]:
    w, h = config.resolution
    sub = _escape_ffmpeg_path(subtitle_path)
    return ["ffmpeg", "-y", "-loop", "1", "-i", str(bg_path), "-i", str(audio_path),
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,gblur=sigma=10,subtitles='{sub}'",
            "-c:v", config.video_codec, "-tune", "stillimage", "-crf", str(config.crf), "-c:a", config.audio_codec, "-b:a", config.audio_bitrate,
            "-pix_fmt", config.pixel_format, "-r", str(config.fps), "-shortest", "-movflags", "+faststart", str(output_path)]

def _build_video_bg_cmd(bg_path: Path, audio_path: Path, subtitle_path: Path, output_path: Path, config: CompositorConfig) -> list[str]:
    w, h = config.resolution
    sub = _escape_ffmpeg_path(subtitle_path)
    return ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(bg_path), "-i", str(audio_path),
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,gblur=sigma=10,subtitles='{sub}'",
            "-c:v", config.video_codec, "-crf", str(config.crf), "-c:a", config.audio_codec, "-b:a", config.audio_bitrate,
            "-pix_fmt", config.pixel_format, "-r", str(config.fps), "-shortest", "-movflags", "+faststart", str(output_path)]

def _build_black_bg_cmd(audio_path: Path, subtitle_path: Path, output_path: Path, config: CompositorConfig) -> list[str]:
    w, h = config.resolution
    sub = _escape_ffmpeg_path(subtitle_path)
    return ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={config.fps}", "-i", str(audio_path),
            "-vf", f"subtitles='{sub}'", "-c:v", config.video_codec, "-crf", str(config.crf), "-c:a", config.audio_codec, "-b:a", config.audio_bitrate,
            "-pix_fmt", config.pixel_format, "-shortest", "-movflags", "+faststart", str(output_path)]

def _escape_ffmpeg_path(path: Path) -> str:
    s = str(path).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":": s = s[0] + "\\:" + s[2:]
    return s

def _run_ffmpeg(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        log.error("FFmpeg 失败: %s", result.stderr.splitlines()[-10:])
        raise subprocess.CalledProcessError(result.returncode, cmd)
