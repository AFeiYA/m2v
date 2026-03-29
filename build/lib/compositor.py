"""
Module 5: 视频合成器
- FFmpeg 命令构建与执行
- 模式 A: 静态图片背景 (loop)
- 模式 B: 视频背景 (循环)
- 支持自定义分辨率 / 编码参数
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.config import CompositorConfig
from src.utils import log, check_ffmpeg


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def compose_video(
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
    background: Path | None = None,
    config: CompositorConfig | None = None,
) -> Path:
    """
    使用 FFmpeg 合成最终卡拉OK视频。

    Args:
        audio_path:    原始 MP3 音频路径
        subtitle_path: ASS 字幕文件路径
        output_path:   输出 MP4 路径
        background:    背景素材 (图片或视频)，None 则使用纯黑背景
        config:        合成器配置

    Returns:
        输出文件路径
    """
    if config is None:
        config = CompositorConfig()

    if not check_ffmpeg():
        raise RuntimeError("FFmpeg 未安装或不在 PATH 中")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = config.resolution

    # 确定背景类型
    if background is None:
        bg_path = config.default_bg
    else:
        bg_path = background

    if bg_path is not None and bg_path.exists():
        is_image = bg_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp")
        is_video = bg_path.suffix.lower() in (".mp4", ".avi", ".mov", ".mkv", ".webm")
    else:
        is_image = False
        is_video = False

    # 构建 FFmpeg 命令
    if is_image:
        cmd = _build_image_bg_cmd(bg_path, audio_path, subtitle_path, output_path, config)
    elif is_video:
        cmd = _build_video_bg_cmd(bg_path, audio_path, subtitle_path, output_path, config)
    else:
        cmd = _build_black_bg_cmd(audio_path, subtitle_path, output_path, config)

    log.info("开始视频合成: %s", output_path.name)
    log.debug("FFmpeg 命令: %s", " ".join(cmd))

    _run_ffmpeg(cmd)

    if output_path.exists():
        size_mb = output_path.stat().st_size / (1024 * 1024)
        log.info("视频合成完成: %s (%.1f MB)", output_path.name, size_mb)
    else:
        raise RuntimeError(f"FFmpeg 合成失败: 输出文件不存在 {output_path}")

    return output_path


# ---------------------------------------------------------------------------
# 模式 A: 静态图片背景
# ---------------------------------------------------------------------------

def _build_image_bg_cmd(
    bg_path: Path,
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
    config: CompositorConfig,
) -> list[str]:
    """静态图片 → 循环为视频流，叠加字幕"""
    w, h = config.resolution
    # 用 ffmpeg 的 subtitles 路径需要转义反斜杠和冒号
    sub_path_escaped = _escape_ffmpeg_path(subtitle_path)
    return [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(bg_path),
        "-i", str(audio_path),
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
               f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
               f"subtitles='{sub_path_escaped}'",
        "-c:v", config.video_codec,
        "-tune", "stillimage",
        "-crf", str(config.crf),
        "-c:a", config.audio_codec,
        "-b:a", config.audio_bitrate,
        "-pix_fmt", config.pixel_format,
        "-r", str(config.fps),
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]


# ---------------------------------------------------------------------------
# 模式 B: 视频背景 (循环)
# ---------------------------------------------------------------------------

def _build_video_bg_cmd(
    bg_path: Path,
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
    config: CompositorConfig,
) -> list[str]:
    """视频背景 → 循环播放，叠加字幕"""
    w, h = config.resolution
    sub_path_escaped = _escape_ffmpeg_path(subtitle_path)
    return [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(bg_path),
        "-i", str(audio_path),
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
               f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
               f"subtitles='{sub_path_escaped}'",
        "-c:v", config.video_codec,
        "-crf", str(config.crf),
        "-c:a", config.audio_codec,
        "-b:a", config.audio_bitrate,
        "-pix_fmt", config.pixel_format,
        "-r", str(config.fps),
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]


# ---------------------------------------------------------------------------
# 模式 C: 纯黑背景 (无背景素材时)
# ---------------------------------------------------------------------------

def _build_black_bg_cmd(
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
    config: CompositorConfig,
) -> list[str]:
    """使用 lavfi 生成纯黑背景"""
    w, h = config.resolution
    sub_path_escaped = _escape_ffmpeg_path(subtitle_path)
    return [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s={w}x{h}:r={config.fps}",
        "-i", str(audio_path),
        "-vf", f"subtitles='{sub_path_escaped}'",
        "-c:v", config.video_codec,
        "-crf", str(config.crf),
        "-c:a", config.audio_codec,
        "-b:a", config.audio_bitrate,
        "-pix_fmt", config.pixel_format,
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ]


# ---------------------------------------------------------------------------
# FFmpeg 路径转义
# ---------------------------------------------------------------------------

def _escape_ffmpeg_path(path: Path) -> str:
    """
    FFmpeg subtitles 滤镜路径需要转义:
    - 反斜杠 → 正斜杠 (Windows)
    - 冒号前加反斜杠 (Windows 盘符)
    """
    s = str(path).replace("\\", "/")
    # 转义冒号 (C:/... → C\\:/...)
    if len(s) >= 2 and s[1] == ":":
        s = s[0] + "\\:" + s[2:]
    return s


# ---------------------------------------------------------------------------
# FFmpeg 执行
# ---------------------------------------------------------------------------

def _run_ffmpeg(cmd: list[str]) -> None:
    """执行 FFmpeg 命令"""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        log.error("FFmpeg 执行失败 (code=%d)", result.returncode)
        if result.stderr:
            # 只打印最后 30 行错误
            err_lines = result.stderr.strip().splitlines()
            for line in err_lines[-30:]:
                log.error("[ffmpeg] %s", line)
        raise subprocess.CalledProcessError(result.returncode, cmd)
