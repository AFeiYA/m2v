"""
商业化轻量歌词动效短视频引擎 (Lyric Video Engine)
- 零 GPU 依赖，纯 CPU / FFmpeg 高速渲染 (15-30秒成片)
- 支持 9:16 竖屏 (抖音/TikTok/小红书/Reels) 与 16:9 横屏 (B站/YouTube)
- 多种动态背景:
    * 磨砂毛玻璃流动光晕 + 精美封面卡片 (blurred_ambient, Apple Music 移动端视觉)
    * 封面慢速呼吸变焦 (ken_burns, 电影感微动效)
    * 经典黑胶唱机动效 (vinyl, 唱盘旋转)
    * 极简纯黑工作室 (solid_black)
- 多种排版模板:
    * Apple Music 动效滚动聚焦 (apple)
    * 极简居中弹性跳动 (center_bounce)
    * 经典 KTV 双行交替过光 (tv)
- 主题调色板 (极简珍珠白、赛博霓虹、复古黑胶金、极光冷艳紫、清爽翡翠绿)
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Literal

import requests
from PIL import Image, ImageDraw

from src.aligner import AlignmentResult
from src.storyboard_schema import AlignedLine, WordTimestamp
from src.config import SubtitleConfig, CompositorConfig
from src.subtitle import generate_ass, COLOR_PALETTES
from src.utils import log, check_ffmpeg, get_ffmpeg_binary, get_ffprobe_binary


# ---------------------------------------------------------------------------
# 规格与选项元数据
# ---------------------------------------------------------------------------

ASPECT_RATIOS = {
    "9:16": {
        "id": "9:16",
        "name": "📱 9:16 竖屏短视频",
        "desc": "适配抖音、TikTok、小红书、微信视频号、Instagram Reels",
        "width": 1080,
        "height": 1920,
        "default_font_size": 54,
    },
    "16:9": {
        "id": "16:9",
        "name": "💻 16:9 横屏高清",
        "desc": "适配 Bilibili、YouTube、PC 宽屏播放器",
        "width": 1920,
        "height": 1080,
        "default_font_size": 72,
    },
}

TEMPLATES = {
    "apple": {
        "id": "apple",
        "name": "🍎 Apple Music 动效滚动",
        "desc": "焦点高亮放大、前后期模糊渐变深景深与逐字丝滑过光",
    },
    "center_bounce": {
        "id": "center_bounce",
        "name": "⚡ 极简居中弹性跳动",
        "desc": "短视频单行居中唱词、入场弹性微缩放、下一句虚化预告",
    },
    "tv": {
        "id": "tv",
        "name": "🎤 经典 KTV 双行交替",
        "desc": "上下双行交替跟唱，高亮过光，经典卡拉OK体验",
    },
}

BACKGROUND_MODES = {
    "full_bleed": {
        "id": "full_bleed",
        "name": "🖼️ 全图沉浸式铺满 (9:16 首选推荐)",
        "desc": "封面原画全屏无黑边铺满 + 电影级光影对比，无割裂感，短视频视效极佳",
    },
    "ken_burns": {
        "id": "ken_burns",
        "name": "📷 封面慢呼吸变焦 (Ken Burns)",
        "desc": "封面原画全屏缓推呼吸镜头，极具电影叙事感",
    },
    "blurred_ambient": {
        "id": "blurred_ambient",
        "name": "✨ 磨砂毛玻璃 + 封面卡片",
        "desc": "高斯模糊动态氛围底层 + 上半部精致封面立体悬浮 (适合 16:9 横屏)",
    },
    "vinyl": {
        "id": "vinyl",
        "name": "💿 经典黑胶唱盘旋转",
        "desc": "唱片盘旋转动效，搭配中心黑胶贴纸与氛围底层",
    },
    "solid_black": {
        "id": "solid_black",
        "name": "🖤 纯黑极简工作室",
        "desc": "纯净黑底，烘托极致纯粹的荧光动效歌词",
    },
}


def get_lyric_video_options() -> dict[str, Any]:
    """返回供前端 UI 渲染的模板、色彩、比例与背景模式选项"""
    themes_list = []
    for tid, info in COLOR_PALETTES.items():
        # 将 ASS 颜色 (&H00BBGGRR / &HBBGGRR) 转换为前端 CSS Hex (#RRGGBB)
        hex_color = _ass_color_to_hex(info["primary"])
        themes_list.append({
            "id": tid,
            "name": info["name"],
            "preview_color": hex_color,
            "primary": info["primary"],
            "secondary": info["secondary"],
        })

    return {
        "aspect_ratios": list(ASPECT_RATIOS.values()),
        "templates": list(TEMPLATES.values()),
        "themes": themes_list,
        "background_modes": list(BACKGROUND_MODES.values()),
    }


def _ass_color_to_hex(ass_color: str) -> str:
    """ASS 颜色 (&H00BBGGRR 或 &HBBGGRR) 转 Web HEX (#RRGGBB)"""
    clean = ass_color.replace("&H", "").replace("&", "")
    if len(clean) >= 8:
        # &HAABBGGRR
        b = clean[2:4]
        g = clean[4:6]
        r = clean[6:8]
    elif len(clean) == 6:
        # BBGGRR
        b = clean[0:2]
        g = clean[2:4]
        r = clean[4:6]
    else:
        return "#FFFFFF"
    return f"#{r}{g}{b}".lower()


# ---------------------------------------------------------------------------
# 封面素材自动嗅探与下载
# ---------------------------------------------------------------------------

def resolve_song_cover(
    song_dir: Path,
    stem: str,
    custom_cover: Path | str | None = None,
) -> Path | None:
    """
    智能解析歌曲封面：
    1. 用户显式指定的封面路径 (若存在)
    2. 检查工程子目录中的本地封面图片: {stem}_cover.*, cover.*
    3. 检查 input/{stem}/ 或 output/{stem}/ 下的 *_suno.json，若包含 image_large_url / image_url 则自动下载并缓存
    4. 检查 storyboard/ 或 keyframes/ 下的第一张已渲染图片
    5. 若均未找到，自动合成一张极简质感黑胶渐变封面
    """
    if custom_cover:
        p = Path(custom_cover)
        if p.exists() and p.is_file():
            return p

    # 1. 查找本地已有封面
    image_exts = [".jpg", ".jpeg", ".png", ".webp"]
    search_dirs = [song_dir, song_dir.parent.parent / "input" / song_dir.name]
    for sdir in search_dirs:
        if not sdir.exists():
            continue
        for base in [f"{stem}_cover", "cover", stem]:
            for ext in image_exts:
                cand = sdir / f"{base}{ext}"
                if cand.exists() and cand.is_file() and cand.stat().st_size > 1024:
                    return cand

    # 2. 检查 Suno 元数据并自动下载官方高清封面
    suno_json_candidates = [
        song_dir / f"{stem}_suno.json",
        song_dir.parent.parent / "input" / song_dir.name / f"{stem}_suno.json",
        song_dir.parent.parent / "input" / f"{stem}_suno.json",
    ]
    for sj in suno_json_candidates:
        if sj.exists() and sj.is_file():
            try:
                data = json.loads(sj.read_text(encoding="utf-8"))
                img_url = data.get("image_large_url") or data.get("image_url")
                if img_url:
                    dest_cover = song_dir / f"{stem}_cover.jpeg"
                    log.info("从 Suno 元数据自动下载官方高清封面: %s → %s", img_url, dest_cover.name)
                    resp = requests.get(img_url, timeout=20, headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
                    })
                    if resp.status_code == 200 and len(resp.content) > 1024:
                        dest_cover.write_bytes(resp.content)
                        return dest_cover
            except Exception as e:
                log.warning("下载 Suno 封面异常: %s", e)

    # 3. 检查分镜或关键帧图片
    sb_dir = song_dir / "storyboard"
    if sb_dir.exists():
        frames = sorted(sb_dir.glob("*.png"))
        if frames:
            return frames[0]

    kf_dir = song_dir / "keyframes"
    if kf_dir.exists():
        kfs = sorted(kf_dir.glob("*.png"))
        if kfs:
            return kfs[0]

    # 4. 生成默认典雅封面 (带唱片同心圆质感)
    default_cover = song_dir / f"{stem}_default_cover.png"
    if not default_cover.exists():
        _create_fallback_cover(default_cover, title=stem)
    return default_cover


def _create_fallback_cover(output_path: Path, title: str) -> Path:
    """生成带唱片纹理与曲名的质感默认封面"""
    size = 1000
    img = Image.new("RGB", (size, size), color=(20, 24, 33))
    draw = ImageDraw.Draw(img)

    # 绘制微弱同心圆唱片纹理
    cx, cy = size // 2, size // 2
    for r in range(120, 480, 24):
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(38, 44, 58), width=1)

    # 中心黑胶唱针孔与色块
    core_r = 110
    draw.ellipse([cx - core_r, cy - core_r, cx + core_r, cy + core_r], fill=(30, 35, 48), outline=(60, 68, 88), width=2)
    inner_r = 25
    draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r], fill=(12, 14, 20))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


def _create_vinyl_disc(cover_path: Path, output_path: Path, disc_size: int = 680) -> Path:
    """
    基于封面图片生成一张带有黑胶纹理与中心贴纸的圆形唱盘透明 PNG
    """
    img = Image.new("RGBA", (disc_size, disc_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = disc_size // 2, disc_size // 2
    radius = disc_size // 2 - 4

    # 1. 绘制黑胶唱片底盘
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(18, 18, 22, 255), outline=(45, 45, 52, 255), width=2)

    # 2. 绘制多圈黑胶反光细槽
    for r in range(int(radius * 0.42), radius - 6, 8):
        alpha = 30 + (r % 16) * 4
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(180, 180, 195, alpha), width=1)

    # 3. 裁切封面为中心圆形贴纸
    try:
        raw_cov = Image.open(cover_path).convert("RGBA")
        sticker_r = int(radius * 0.40)
        sticker_d = sticker_r * 2
        raw_cov = raw_cov.resize((sticker_d, sticker_d), Image.Resampling.LANCZOS)

        # 圆形 mask
        mask = Image.new("L", (sticker_d, sticker_d), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse([0, 0, sticker_d, sticker_d], fill=255)

        img.paste(raw_cov, (cx - sticker_r, cy - sticker_r), mask)
    except Exception as e:
        log.warning("黑胶贴纸贴合异常: %s", e)

    # 4. 中心穿轴孔
    center_hole = int(disc_size * 0.035)
    draw.ellipse([cx - center_hole, cy - center_hole, cx + center_hole, cy + center_hole], fill=(10, 10, 14, 255), outline=(120, 120, 130, 255), width=2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


# ---------------------------------------------------------------------------
# FFmpeg 滤镜图构建器
# ---------------------------------------------------------------------------

def _escape_sub_path(path: Path) -> str:
    """转义 ASS 字幕路径供 FFmpeg filter 使用"""
    s = str(path.resolve()).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        s = s[0] + "\\:" + s[2:]
    # 转义特殊符号与单引号
    s = s.replace("'", "'\\''")
    return s


def slice_alignment_for_segment(
    alignment: AlignmentResult,
    start_time: float = 0.0,
    end_time: float | None = None,
) -> AlignmentResult:
    """
    针对起止时间段裁剪 AlignmentResult，并将时间戳平移至从 0.0 开始：
    - 仅保留与 [start_time, end_time] 有交集的歌词行
    - 将所有 line.start, line.end 以及 word.start, word.end 减去 start_time
    - 更新 duration 为 end_time - start_time
    """
    st = max(0.0, float(start_time or 0.0))
    et = float(end_time) if (end_time is not None and float(end_time) > st) else None

    if st == 0.0 and et is None:
        return alignment

    new_lines = []
    for line in alignment.lines:
        if line.end <= st:
            continue
        if et is not None and line.start >= et:
            continue

        shifted_words = []
        for w in (line.words or []):
            if w.end <= st:
                continue
            if et is not None and w.start >= et:
                continue
            w_st = max(0.0, w.start - st)
            w_et = max(w_st + 0.04, (w.end - st) if et is None else min(et - st, w.end - st))
            shifted_words.append(WordTimestamp(word=w.word, start=w_st, end=w_et))

        if shifted_words:
            shifted_start = shifted_words[0].start
            shifted_end = shifted_words[-1].end
        else:
            shifted_start = max(0.0, line.start - st)
            shifted_end = max(shifted_start + 0.1, (line.end - st) if et is None else min(et - st, line.end - st))

        new_lines.append(
            AlignedLine(
                text=line.text,
                start=shifted_start,
                end=shifted_end,
                words=shifted_words,
                style_overrides=getattr(line, "style_overrides", {}),
                section=getattr(line, "section", ""),
            )
        )

    new_duration = (et - st) if et is not None else max(0.1, alignment.duration - st)

    return AlignmentResult(
        title=alignment.title,
        duration=new_duration,
        lines=new_lines,
        sections=[],
    )


def build_lyric_video_ffmpeg_cmd(
    audio_path: Path,
    ass_path: Path,
    output_path: Path,
    cover_path: Path,
    width: int,
    height: int,
    bg_mode: str,
    fps: int = 30,
    crf: int = 18,
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    audio_bitrate: str = "192k",
    temp_dir: Path | None = None,
    duration_limit: float | None = None,
    start_time: float = 0.0,
) -> list[str]:
    """构建优化的纯 CPU FFmpeg 动效视频合成命令"""
    ffmpeg_bin = get_ffmpeg_binary()
    escaped_sub = _escape_sub_path(ass_path)
    inputs = []
    filters = []

    # 准备音频输入参数 (若指定了 start_time > 0，在 -i 前添加 -ss 极速精准 seek)
    audio_args = []
    if start_time and start_time > 0.0:
        audio_args.extend(["-ss", f"{start_time:.3f}"])
    audio_args.extend(["-i", str(audio_path)])

    if bg_mode == "solid_black":
        # 纯黑极简工作室
        inputs.extend(["-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r={fps}"])
        inputs.extend(audio_args)
        filters.append(f"[0:v]subtitles='{escaped_sub}'[v_out]")

    elif bg_mode == "ken_burns":
        # 封面全屏慢呼吸推进 (Ken Burns)
        inputs.extend(["-loop", "1", "-i", str(cover_path)])
        inputs.extend(audio_args)

        # 预先缩放至 1.25 倍基准，使用 zoompan 缓推，添加微弱暗角/对比度提升歌词可读性
        tw = int(width * 1.2)
        th = int(height * 1.2)
        filters.append(
            f"[0:v]scale={tw}:{th}:force_original_aspect_ratio=increase,"
            f"crop={tw}:{th},"
            f"zoompan=z='min(zoom+0.0003,1.15)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps},"
            f"eq=brightness=-0.18:contrast=1.05,"
            f"subtitles='{escaped_sub}'[v_out]"
        )

    elif bg_mode == "vinyl":
        # 旋转黑胶唱盘
        if temp_dir is None:
            temp_dir = output_path.parent
        disc_size = int(min(width, height) * 0.62) if height > width else int(height * 0.68)
        vinyl_png = temp_dir / f"disc_{disc_size}.png"
        _create_vinyl_disc(cover_path, vinyl_png, disc_size=disc_size)

        # 0: 底层封面 (模糊)
        inputs.extend(["-loop", "1", "-i", str(cover_path)])
        # 1: 黑胶唱片透明 PNG
        inputs.extend(["-loop", "1", "-i", str(vinyl_png)])
        # 2: 音频
        inputs.extend(audio_args)

        # 模糊背景
        filters.append(
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"boxblur=40:5,eq=brightness=-0.28[bg_blur]"
        )

        # 唱片匀速旋转: 18秒转一圈
        filters.append(
            f"[1:v]rotate=2*PI*t/18:ow={disc_size}:oh={disc_size}:c=none[spinning_disc]"
        )

        # 叠加唱盘到上部/左部
        if height > width:
            # 竖屏 9:16: 唱盘位于屏幕上部 (X居中, Y=180)
            overlay_x = f"(W-w)/2"
            overlay_y = 190
        else:
            # 横屏 16:9: 唱盘位于左侧 (X=160, Y居中)
            overlay_x = 160
            overlay_y = f"(H-h)/2"

        filters.append(f"[bg_blur][spinning_disc]overlay=x={overlay_x}:y={overlay_y}[v_layered]")
        filters.append(f"[v_layered]subtitles='{escaped_sub}'[v_out]")

    elif bg_mode == "blurred_ambient":
        # 磨砂毛玻璃流动光晕 + 精美封面卡片 (适合 16:9 横屏，或桌面播放器模式)
        inputs.extend(["-loop", "1", "-i", str(cover_path)])
        inputs.extend(audio_args)

        if height > width:
            # 📱 9:16 竖屏短视频布局
            card_size = int(width * 0.62)
            card_y = 160
            filters.append(
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},"
                f"boxblur=45:5,eq=brightness=-0.25[bg_blur]"
            )
            filters.append(
                f"[0:v]scale={card_size}:{card_size}:force_original_aspect_ratio=increase,"
                f"crop={card_size}:{card_size},"
                f"pad={card_size+8}:{card_size+8}:4:4:color=white@0.25[card]"
            )
            filters.append(f"[bg_blur][card]overlay=x=(W-w)/2:y={card_y}[v_card]")
            filters.append(f"[v_card]subtitles='{escaped_sub}'[v_out]")
        else:
            # 💻 16:9 横屏布局
            card_size = int(height * 0.58)  # ~620px
            filters.append(
                f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},"
                f"boxblur=45:5,eq=brightness=-0.25[bg_blur]"
            )
            filters.append(
                f"[0:v]scale={card_size}:{card_size}:force_original_aspect_ratio=increase,"
                f"crop={card_size}:{card_size},"
                f"pad={card_size+8}:{card_size+8}:4:4:color=white@0.25[card]"
            )
            filters.append(f"[bg_blur][card]overlay=x=160:y=(H-h)/2[v_card]")
            filters.append(f"[v_card]subtitles='{escaped_sub}'[v_out]")

    else:
        # 默认模式: full_bleed (🖼️ 全图沉浸式铺满，9:16 短视频首选，告别小卡片割裂感)
        inputs.extend(["-loop", "1", "-i", str(cover_path)])
        inputs.extend(audio_args)

        # 原画全屏铺满裁切 + 电影级微调明暗对比度 (微暗化 -0.14，对比度 1.06，保证白色歌词通透浮现且原画张力十足)
        filters.append(
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"eq=brightness=-0.14:contrast=1.06,"
            f"subtitles='{escaped_sub}'[v_out]"
        )

    # 音频淡入淡出保护 (切片片段开头淡入 0.35s，结尾淡出 0.6s)
    input_indices = [i for i, val in enumerate(inputs) if val == "-i"]
    audio_input_idx = len(input_indices) - 1

    fade_filters = []
    if start_time and start_time > 0.0:
        fade_filters.append("afade=t=in:ss=0:d=0.35")
    if duration_limit and duration_limit > 2.0:
        fade_filters.append(f"afade=t=out:st={duration_limit - 0.6:.2f}:d=0.6")

    audio_map_target = f"{audio_input_idx}:a"
    if fade_filters:
        filters.append(f"[{audio_input_idx}:a]{','.join(fade_filters)}[a_out]")
        audio_map_target = "[a_out]"

    filter_complex = ";".join(filters)

    cmd = [
        ffmpeg_bin, "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v_out]",
        "-map", audio_map_target,
        "-c:v", video_codec,
        "-preset", "veryfast",
        "-crf", str(crf),
        "-c:a", audio_codec,
        "-b:a", audio_bitrate,
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
    ]
    if duration_limit and duration_limit > 0:
        cmd.extend(["-t", f"{duration_limit:.3f}"])
    cmd.extend([
        "-shortest",
        "-movflags", "+faststart",
        str(output_path),
    ])
    return cmd


# ---------------------------------------------------------------------------
# 歌词短视频合成主管线
# ---------------------------------------------------------------------------

def export_lyric_video(
    alignment_source: Path | str | AlignmentResult,
    audio_path: Path | str,
    output_path: Path | str,
    aspect_ratio: str = "9:16",
    template: str = "apple",
    theme: str = "apple_white",
    background_mode: str = "full_bleed",
    cover_path: Path | str | None = None,
    font_size: int | None = None,
    duration_limit: float | None = None,
    start_time: float = 0.0,
    end_time: float | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """
    一键导出商业级动效歌词短视频 (9:16 / 16:9)。

    Returns:
        {
            "status": "ok",
            "video_path": str,
            "ass_path": str,
            "cover_path": str,
            "duration": float,
            "size_mb": float,
            "resolution": [width, height],
            "aspect_ratio": str,
            "template": str,
            "theme": str,
        }
    """
    t0 = time.time()
    if not check_ffmpeg():
        raise RuntimeError("系统未检测到可用的 FFmpeg！请确保安装了 ffmpeg-full 或将其加入 PATH。")

    # 1. 规范化路径与数据
    audio_p = Path(audio_path).resolve()
    if not audio_p.exists():
        raise FileNotFoundError(f"音频文件不存在: {audio_p}")

    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    stem = out_p.stem

    if isinstance(alignment_source, (str, Path)):
        alignment_path = Path(alignment_source).resolve()
        alignment = AlignmentResult.load_json(alignment_path)
        song_dir = alignment_path.parent
    else:
        alignment = alignment_source
        song_dir = out_p.parent

    # 2. 匹配时间裁剪区间 (支持副歌、主歌或自定义起止时间)
    effective_st = max(0.0, float(start_time or 0.0))
    effective_et = float(end_time) if (end_time is not None and float(end_time) > effective_st) else None
    if effective_et is not None:
        effective_dur = effective_et - effective_st
    elif duration_limit and duration_limit > 0:
        effective_dur = float(duration_limit)
        effective_et = effective_st + effective_dur
    else:
        effective_dur = None

    if effective_st > 0.0 or effective_et is not None:
        log.info("✂️ 执行视频时间裁剪: 起点=%.2fs, 终点=%s, 时长=%s",
                 effective_st, f"{effective_et:.2f}s" if effective_et else "全曲", f"{effective_dur:.2f}s" if effective_dur else "自适应")
        alignment = slice_alignment_for_segment(alignment, effective_st, effective_et)

    if progress_callback:
        progress_callback(10.0, "解析歌曲封面与比例规格...")

    # 3. 匹配分辨率规格
    ratio_spec = ASPECT_RATIOS.get(aspect_ratio, ASPECT_RATIOS["9:16"])
    width = ratio_spec["width"]
    height = ratio_spec["height"]
    actual_font_size = font_size or ratio_spec["default_font_size"]

    # 4. 解析封面
    resolved_cover = resolve_song_cover(song_dir, stem=song_dir.name, custom_cover=cover_path)
    if not resolved_cover or not resolved_cover.exists():
        fallback_cover = song_dir / f"{song_dir.name}_cover.png"
        _create_fallback_cover(fallback_cover, title=song_dir.name)
        resolved_cover = fallback_cover

    log.info("🎯 歌词视频配置: 比例=%s (%dx%d), 模板=%s, 主题=%s, 背景=%s, 封面=%s",
             aspect_ratio, width, height, template, theme, background_mode, resolved_cover.name)

    if progress_callback:
        progress_callback(30.0, "生成高精度动效 ASS 字幕...")

    # 5. 生成适配当前分辨率与调色板的 ASS 字幕
    ass_path = out_p.with_suffix(".ass")
    sub_config = SubtitleConfig(
        font_size=actual_font_size,
        play_res_x=width,
        play_res_y=height,
        margin_x=70 if width == 1080 else 100,
        render_mode=template,
        theme=theme,
        use_karaoke_gradient=True,
    )

    # 针对不同背景与比例微调焦点的垂直坐标
    if aspect_ratio == "9:16":
        if background_mode in ("blurred_ambient", "vinyl"):
            # 上半部分有封面卡片，歌词焦点下移到 56% 处 (~1075px)
            sub_config.center_y = int(height * 0.56)
        else:
            sub_config.center_y = int(height * 0.45)
    else:
        # 16:9 横屏
        if background_mode == "blurred_ambient":
            sub_config.margin_x = int(width * 0.45)  # 避开左侧封面
            sub_config.center_y = int(height * 0.40)

    generate_ass(alignment, ass_path, config=sub_config, audio_path=audio_p)

    if progress_callback:
        progress_callback(50.0, "构建 FFmpeg CPU 高速视频合成命令...")

    # 6. 构建 FFmpeg 命令并执行
    cmd = build_lyric_video_ffmpeg_cmd(
        audio_path=audio_p,
        ass_path=ass_path,
        output_path=out_p,
        cover_path=resolved_cover,
        width=width,
        height=height,
        bg_mode=background_mode,
        temp_dir=song_dir,
        duration_limit=effective_dur,
        start_time=effective_st,
    )

    log.info("开始渲染动效短视频: %s", out_p.name)
    log.debug("FFmpeg CMD: %s", " ".join(cmd))

    if progress_callback:
        progress_callback(65.0, "FFmpeg 正在渲染动效视频 (预计耗时 15-25 秒)...")

    # 执行命令
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if res.returncode != 0:
        log.error("FFmpeg 渲染失败: %s", res.stderr[-500:] if res.stderr else "未知错误")
        raise subprocess.CalledProcessError(res.returncode, cmd, output=res.stdout, stderr=res.stderr)

    if not out_p.exists() or out_p.stat().st_size < 10000:
        raise RuntimeError(f"输出视频文件生成异常: {out_p}")

    size_mb = round(out_p.stat().st_size / (1024 * 1024), 2)
    elapsed = round(time.time() - t0, 1)
    log.info("🎉 歌词短视频合成成功！耗时: %.1fs, 大小: %.2fMB, 文件: %s", elapsed, size_mb, out_p.name)

    if progress_callback:
        progress_callback(100.0, "视频合成完成！")

    return {
        "status": "ok",
        "video_path": str(out_p),
        "ass_path": str(ass_path),
        "cover_path": str(resolved_cover),
        "size_mb": size_mb,
        "elapsed_seconds": elapsed,
        "resolution": [width, height],
        "aspect_ratio": aspect_ratio,
        "template": template,
        "theme": theme,
        "background_mode": background_mode,
    }
