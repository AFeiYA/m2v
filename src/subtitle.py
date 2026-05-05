"""
Module 4: ASS 卡拉OK字幕生成器
- 词级 JSON → ASS \\k 标签
- 样式模板加载
- Apple Music 风格滚动动效 + 字级呼吸感 (Apple Pulse)
"""

from __future__ import annotations
import re
from pathlib import Path

from src.aligner import AlignmentResult, AlignedLine
from src.config import SubtitleConfig
from src.utils import log, seconds_to_ass_time, seconds_to_centiseconds


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def generate_ass(
    alignment: AlignmentResult,
    output_path: Path,
    config: SubtitleConfig | None = None,
    audio_path: Path | None = None,
    resolution: tuple[int, int] = (1920, 1080),
) -> Path:
    if config is None:
        config = SubtitleConfig()

    log.info("生成字幕 (模式: %s): %d 行", config.render_mode, len(alignment.lines))
    header = _load_template_header(config, resolution)

    # 可选: 检测节奏点
    beat_times: list[float] = []
    if config.enable_beat_effects and audio_path is not None:
        beat_times = _detect_beats(audio_path)

    dialogue_lines: list[str] = []
    res_x, res_y = resolution
    mid_y = res_y // 2
    offset_y = 150

    for i, line in enumerate(alignment.lines):
        # 计算当前行的开始和结束（用于 Dialogue 时间轴）
        start_t = seconds_to_ass_time(line.start)
        end_t = seconds_to_ass_time(line.end)
        
        # 1. 活跃行 (Active)
        if config.render_mode == "apple":
            # 构建带呼吸感的卡拉OK文本
            karaoke_text = ""
            for word in line.words:
                duration_cs = seconds_to_centiseconds(word.end - word.start)
                
                # 计算这个词相对于行开始的毫秒数
                rel_start_ms = int((word.start - line.start) * 1000)
                word_dur_ms = int((word.end - word.start) * 1000)
                
                # Apple 呼吸感: 只在 Y 轴缩放，避免非等宽字体横向推挤导致的整行跳动
                pulse_tags = ""
                if config.apple_pulse:
                    # \t(开始, 结束, 效果) -> Y轴放大到 115%，然后缩回
                    pulse_tags = (
                        f"\\t({rel_start_ms},{rel_start_ms + 80},\\fscy115)"
                        f"\\t({rel_start_ms + 120},{rel_start_ms + 250},\\fscy100)"
                    )
                
                # 节奏点增强 (如果开启)
                beat_tags = _get_beat_effect(word.start, word.end, beat_times, config) if beat_times else ""
                
                # \kf 是变色，pulse_tags 是缩放
                karaoke_text += f"{{\\kf{duration_cs}{pulse_tags}{beat_tags}}}{word.word}"
            
            # Dialogue 生成
            pos_tags = f"{{\\pos({res_x//2},{mid_y})}}"
            dialogue_lines.append(f"Dialogue: 0,{start_t},{end_t},{config.style_name},,0,0,0,,{pos_tags}{karaoke_text}")

            # 2. 预备行 (Upcoming)
            if i > 0:
                prev = alignment.lines[i-1]
                up_tags = f"{{\\pos({res_x//2},{mid_y + offset_y})\\blur4\\alpha&H80&}}"
                dialogue_lines.append(f"Dialogue: 0,{seconds_to_ass_time(prev.start)},{seconds_to_ass_time(prev.end)},{config.style_name},,0,0,0,,{up_tags}{line.text}")

            # 3. 结束行 (Passed)
            if i < len(alignment.lines) - 1:
                nxt = alignment.lines[i+1]
                pass_tags = f"{{\\pos({res_x//2},{mid_y - offset_y})\\blur4\\alpha&H80&}}"
                dialogue_lines.append(f"Dialogue: 0,{seconds_to_ass_time(nxt.start)},{seconds_to_ass_time(nxt.end)},{config.style_name},,0,0,0,,{pass_tags}{line.text}")
        
        else:
            # 经典模式
            karaoke_text = "".join([f"{{\\kf{seconds_to_centiseconds(w.end-w.start)}}}{w.word}" for w in line.words])
            dialogue_lines.append(f"Dialogue: 0,{start_t},{end_t},{config.style_name},,0,0,0,,{karaoke_text}")

    ass_content = header + "\n".join(dialogue_lines) + "\n"
    output_path.write_text(ass_content, encoding="utf-8-sig")
    return output_path


# ---------------------------------------------------------------------------
# 模板与辅助逻辑
# ---------------------------------------------------------------------------

def _load_template_header(config: SubtitleConfig, resolution: tuple[int, int]) -> str:
    template_path = config.template_path
    if template_path.exists():
        content = template_path.read_text(encoding="utf-8")
        content = re.sub(r"PlayResX:\s*\d+", f"PlayResX: {resolution[0]}", content, flags=re.IGNORECASE)
        content = re.sub(r"PlayResY:\s*\d+", f"PlayResY: {resolution[1]}", content, flags=re.IGNORECASE)
        pattern = rf"(Style:\s*{config.style_name},[^,]+,[^,]+,)(&H[0-9A-F]+),(&H[0-9A-F]+),(&H[0-9A-F]+)"
        replacement = rf"\g<1>{config.primary_colour},{config.secondary_colour},{config.outline_colour}"
        content = re.sub(pattern, replacement, content, flags=re.IGNORECASE)
        content = re.sub(rf"(Style:\s*{config.style_name},[^,]+,)\d+", rf"\g<1>{config.font_size}", content, flags=re.IGNORECASE)
        return content if content.endswith("\n") else content + "\n"
    return _generate_default_header(config, resolution)

def _generate_default_header(config: SubtitleConfig, resolution: tuple[int, int]) -> str:
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {resolution[0]}
PlayResY: {resolution[1]}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {config.style_name},{config.font_name},{config.font_size},{config.primary_colour},{config.secondary_colour},{config.outline_colour},&H80000000,-1,0,0,0,100,100,2,0,1,3,1,2,30,30,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

def _detect_beats(audio_path: Path) -> list[float]:
    try:
        import librosa
        y, sr = librosa.load(str(audio_path), sr=22050)
        onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units="frames")
        return librosa.frames_to_time(onset_frames, sr=sr).tolist()
    except Exception: return []

def _get_beat_effect(word_start: float, word_end: float, beat_times: list[float], config: SubtitleConfig) -> str:
    scale_pct = int(config.beat_scale * 100)
    for beat in beat_times:
        if word_start <= beat <= word_end:
            off = int((beat - word_start) * 1000)
            return f"\\t({off},{off+80},\\fscx{scale_pct}\\fscy{scale_pct})\\t({off+80},{off+160},\\fscx100\\fscy100)"
    return ""
