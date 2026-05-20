"""
Module 5: 视频合成器
- FFmpeg 命令构建与执行
- 模式 A: 静态图片背景 (loop)
- 模式 B: 视频背景 (循环)
- 三层合成: 默认背景 → 分镜图片(overlay) → ASS 字幕
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
    storyboard: list | None = None,
) -> Path:
    """
    使用 FFmpeg 合成最终卡拉OK视频。

    Args:
        audio_path:    原始 MP3 音频路径
        subtitle_path: ASS 字幕文件路径
        output_path:   输出 MP4 路径
        background:    背景素材 (图片或视频)，None 则使用纯黑背景
        config:        合成器配置
        storyboard:    分镜事件列表 [StoryboardEvent, ...]

    Returns:
        输出文件路径
    """
    if config is None:
        config = CompositorConfig()

    if not check_ffmpeg():
        raise RuntimeError("FFmpeg 未安装或不在 PATH 中")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 过滤有效的分镜事件
    valid_events = _filter_valid_storyboard(storyboard)

    # 如果没有显式背景，从分镜事件中取第一张图片作为全程背景
    if background is None and valid_events:
        for ev in valid_events:
            if ev['path'].suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
                background = ev['path']
                log.info("无显式背景，使用分镜第一张图片作为全程背景: %s", background.name)
                break

    if valid_events:
        cmd = _build_storyboard_cmd(
            audio_path, subtitle_path, output_path,
            background, valid_events, config,
        )
    else:
        # 无分镜事件，走原有逻辑
        cmd = _build_simple_cmd(
            audio_path, subtitle_path, output_path,
            background, config,
        )

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
# 分镜事件过滤
# ---------------------------------------------------------------------------

def _filter_valid_storyboard(storyboard: list | None) -> list:
    """过滤出路径存在、时间有效的分镜事件"""
    if not storyboard:
        return []

    valid = []
    for ev in storyboard:
        # 支持 dict 或 dataclass
        if hasattr(ev, 'path'):
            path, start, end, etype = ev.path, ev.start, ev.end, ev.type
            speed_align = getattr(ev, 'speed_align', True)
        elif isinstance(ev, dict):
            path = ev.get('path', '')
            start = ev.get('start', 0)
            end = ev.get('end', 0)
            etype = ev.get('type', 'image')
            speed_align = ev.get('speed_align', True)
        else:
            continue

        p = Path(path)
        if not p.exists():
            log.warning("分镜素材不存在，跳过: %s", path)
            continue
        if end <= start:
            log.warning("分镜时间无效 (end<=start)，跳过: %s", path)
            continue

        valid.append({
            'path': p,
            'start': start,
            'end': end,
            'type': etype,
            'speed_align': speed_align,
        })

    valid.sort(key=lambda e: e['start'])
    if valid:
        log.info("有效分镜事件: %d 个", len(valid))
    return valid


# ---------------------------------------------------------------------------
# 无分镜：简单合成 (保留原有逻辑)
# ---------------------------------------------------------------------------

def _build_simple_cmd(
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
    background: Path | None,
    config: CompositorConfig,
) -> list[str]:
    """无分镜事件时的简单合成命令"""
    w, h = config.resolution

    # 确定背景类型
    bg_path = background if background else config.default_bg

    if bg_path is not None and bg_path.exists():
        is_image = bg_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp")
        is_video = bg_path.suffix.lower() in (".mp4", ".avi", ".mov", ".mkv", ".webm")
    else:
        is_image = False
        is_video = False

    if is_image:
        return _build_image_bg_cmd(bg_path, audio_path, subtitle_path, output_path, config)
    elif is_video:
        return _build_video_bg_cmd(bg_path, audio_path, subtitle_path, output_path, config)
    else:
        return _build_black_bg_cmd(audio_path, subtitle_path, output_path, config)


# ---------------------------------------------------------------------------
# 三层合成: 默认背景 → 分镜 overlay → 字幕
# ---------------------------------------------------------------------------

def _get_video_duration(path: Path) -> float:
    """获取视频的实际时长 (秒)。若获取失败或 ffprobe 不可用，返回 5.0 秒。"""
    import shutil
    if not shutil.which("ffprobe"):
        log.warning("ffprobe 未找到，无法获取视频时长: %s", path.name)
        return 5.0
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            return float(res.stdout.strip())
    except Exception as e:
        log.warning("无法获取视频时长: %s, 错误: %s", path.name, e)
    return 5.0


def _build_storyboard_cmd(
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
    background: Path | None,
    events: list[dict],
    config: CompositorConfig,
) -> list[str]:
    """
    构建三层合成的 FFmpeg 命令:

    Layer 1 (底层): 默认背景 — 纯黑/图片/视频
    Layer 2 (中层): 分镜图片 — 通过 overlay + enable 在指定时间段叠加
    Layer 3 (顶层): ASS 字幕
    """
    w, h = config.resolution
    sub_path_escaped = _escape_ffmpeg_path(subtitle_path) if subtitle_path else ""

    # ── 构建输入列表 ──
    inputs: list[str] = []

    # Input 0: 背景
    bg_path = background if background else config.default_bg
    bg_is_image = False
    if bg_path and bg_path.exists():
        bg_is_image = bg_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp")
        if bg_is_image:
            inputs.extend(["-loop", "1", "-i", str(bg_path)])
        else:
            inputs.extend(["-stream_loop", "-1", "-i", str(bg_path)])
    else:
        # 纯黑背景
        inputs.extend(["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={config.fps}"])

    # Input 1: 音频
    inputs.extend(["-i", str(audio_path)])

    # Input 2..N: 分镜图片/视频
    for ev in events:
        p = ev['path']
        if ev['type'] == 'image' or p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
            inputs.extend(["-loop", "1", "-i", str(p)])
        else:
            inputs.extend(["-stream_loop", "-1", "-i", str(p)])

    # ── 构建 filter_complex ──
    filters = []

    # 第一步: 把背景缩放到目标分辨率
    filters.append(
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1,fps={config.fps}[bg]"
    )

    # 第二步: 逐个叠加分镜图层
    prev_label = "bg"
    for i, ev in enumerate(events):
        input_idx = i + 2  # 0=背景, 1=音频, 2+=分镜
        overlay_label = f"ov{i}"
        scaled_label = f"sb{i}"

        p = ev['path']
        s = ev['start']
        e = ev['end']
        D = e - s
        is_video = not (ev['type'] == 'image' or p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp"))

        if is_video:
            # 视频做时间对齐 setpts：从首帧(0秒)开始播放，并在 S 秒开始叠加。可选拉伸/压缩以匹配 D 长度
            L = _get_video_duration(p)
            speed_align = ev.get('speed_align', True)
            
            if speed_align and L > 0:
                speed_factor = D / L
                setpts_filter = f"setpts=PTS*{speed_factor:.4f}+{s:.4f}/TB"
                log.info("分镜视频 [%d] %s: 时长 %.2fs, 区间 %.2fs, 速度比例 %.4fx", 
                         i, p.name, L, D, speed_factor)
            else:
                setpts_filter = f"setpts=PTS+{s:.4f}/TB"
                log.info("分镜视频 [%d] %s: 时长 %.2fs, 区间 %.2fs, 保持原速并在 %.2fs 处切入", 
                         i, p.name, L, D, s)
                
            filters.append(
                f"[{input_idx}:v]{setpts_filter},"
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
                f"setsar=1[{scaled_label}]"
            )
        else:
            # 缩放分镜图片到目标分辨率
            filters.append(
                f"[{input_idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
                f"setsar=1[{scaled_label}]"
            )

        # 在指定时间段叠加
        filters.append(
            f"[{prev_label}][{scaled_label}]overlay=0:0:"
            f"enable='between(t,{s:.3f},{e:.3f})'[{overlay_label}]"
        )
        prev_label = overlay_label

    # 第三步: 叠加 ASS 字幕
    if subtitle_path and config.enable_subtitles:
        final_label = "final"
        filters.append(
            f"[{prev_label}]subtitles='{sub_path_escaped}'[{final_label}]"
        )
    else:
        final_label = prev_label

    filter_complex = ";".join(filters)

    # ── 组装完整命令 ──
    cmd = ["ffmpeg", "-y"]
    cmd.extend(inputs)
    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(["-map", f"[{final_label}]", "-map", "1:a"])
    cmd.extend([
        "-c:v", config.video_codec,
        "-crf", str(config.crf),
        "-c:a", config.audio_codec,
        "-b:a", config.audio_bitrate,
        "-pix_fmt", config.pixel_format,
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ])

    return cmd


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
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
    if subtitle_path and config.enable_subtitles:
        sub_path_escaped = _escape_ffmpeg_path(subtitle_path)
        vf += f",subtitles='{sub_path_escaped}'"
        
    return [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(bg_path),
        "-i", str(audio_path),
        "-vf", vf,
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
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
    if subtitle_path and config.enable_subtitles:
        sub_path_escaped = _escape_ffmpeg_path(subtitle_path)
        vf += f",subtitles='{sub_path_escaped}'"
        
    return [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(bg_path),
        "-i", str(audio_path),
        "-vf", vf,
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
    if subtitle_path and config.enable_subtitles:
        sub_path_escaped = _escape_ffmpeg_path(subtitle_path)
        vf = f"subtitles='{sub_path_escaped}'"
    else:
        vf = "null"
        
    return [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s={w}x{h}:r={config.fps}",
        "-i", str(audio_path),
        "-vf", vf,
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
