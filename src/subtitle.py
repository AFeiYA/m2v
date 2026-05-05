"""
Module 4: ASS 卡拉OK字幕生成器
- Apple Music 极致风格
- 单字独立定位 (Avoid Jitter)
- 修正: 简单整体跳动 (110% Uniform Scale)
"""

from __future__ import annotations
import re
from pathlib import Path
from PIL import ImageFont

from src.aligner import AlignmentResult, AlignedLine
from src.config import SubtitleConfig
from src.utils import log, seconds_to_ass_time, seconds_to_centiseconds

def generate_ass(alignment: AlignmentResult, output_path: Path, config: SubtitleConfig | None = None, audio_path: Path | None = None, resolution: tuple[int, int] = (1920, 1080)) -> Path:
    if config is None: config = SubtitleConfig()
    header = _load_template_header(config, resolution)
    try: font = ImageFont.truetype(config.font_path, config.font_size)
    except Exception: font = None

    dialogue_lines = []
    res_x, res_y = resolution
    mid_y, margin_l, offset_y = res_y // 2, 150, 150

    for i, line in enumerate(alignment.lines):
        start_t, end_t = seconds_to_ass_time(line.start), seconds_to_ass_time(line.end)
        
        if config.render_mode == "apple":
            current_x = margin_l
            for word in line.words:
                word_text = word.word
                delay_sec = word.start - line.start
                delay_cs, delay_ms = int(round(delay_sec * 100)), int(round(delay_sec * 1000))
                dur_cs = int(round((word.end - word.start) * 100))

                for char in word_text:
                    char_w = font.getlength(char) if font else (config.font_size if ord(char) > 128 else config.font_size * 0.5)
                    char_center_x = current_x + (char_w / 2)
                    
                    pulse_tags = ""
                    if config.apple_pulse:
                        # 简单整体缩放，产生“跳跃”感而不拉长
                        pulse_tags = (f"\\t({delay_ms},{delay_ms + 80},\\fscx110\\fscy110)"
                                     f"\\t({delay_ms + 120},{delay_ms + 300},\\fscx100\\fscy100)")
                    
                    tags = f"{{\\an2\\pos({char_center_x:.1f},{mid_y}){pulse_tags}}}"
                    content = f"{tags}{{\\k{delay_cs}}}{{\\kf{dur_cs}}}{char}"
                    dialogue_lines.append(f"Dialogue: 0,{start_t},{end_t},{config.style_name},,0,0,0,,{content}")
                    current_x += char_w

            # 预备与结束行
            if i > 0:
                prev = alignment.lines[i-1]
                tags = f"{{\\an7\\pos({margin_l},{mid_y + offset_y})\\blur4\\alpha&H80&}}"
                dialogue_lines.append(f"Dialogue: 0,{seconds_to_ass_time(prev.start)},{seconds_to_ass_time(prev.end)},{config.style_name},,0,0,0,,{tags}{line.text}")
            if i < len(alignment.lines) - 1:
                nxt = alignment.lines[i+1]
                tags = f"{{\\an7\\pos({margin_l},{mid_y - offset_y})\\blur4\\alpha&H80&}}"
                dialogue_lines.append(f"Dialogue: 0,{seconds_to_ass_time(nxt.start)},{seconds_to_ass_time(nxt.end)},{config.style_name},,0,0,0,,{tags}{line.text}")
        else:
            karaoke_text = "".join([f"{{\\kf{seconds_to_centiseconds(w.end-w.start)}}}{w.word}" for w in line.words])
            dialogue_lines.append(f"Dialogue: 0,{start_t},{end_t},{config.style_name},,0,0,0,,{karaoke_text}")

    output_path.write_text(header + "\n".join(dialogue_lines) + "\n", encoding="utf-8-sig")
    return output_path

def _load_template_header(config: SubtitleConfig, resolution: tuple[int, int]) -> str:
    template_path = config.template_path
    if template_path.exists():
        content = template_path.read_text(encoding="utf-8")
        content = re.sub(r"PlayResX:\s*\d+", f"PlayResX: {resolution[0]}", content, flags=re.IGNORECASE)
        content = re.sub(r"PlayResY:\s*\d+", f"PlayResY: {resolution[1]}", content, flags=re.IGNORECASE)
        pattern = rf"(Style:\s*{config.style_name},[^,]+,[^,]+,)(&H[0-9A-F]+),(&H[0-9A-F]+),(&H[0-9A-F]+),(&H[0-9A-F]+),[^,]+,[^,]+,[^,]+,[^,]+,[^,]+,[^,]+,[^,]+,[^,]+,[^,]+,(\d+),(\d+),(\d+)"
        replacement = rf"\g<1>{config.primary_colour},{config.secondary_colour},&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,2,2"
        content = re.sub(pattern, replacement, content, flags=re.IGNORECASE)
        content = re.sub(rf"(Style:\s*{config.style_name},[^,]+,)\d+", rf"\g<1>{config.font_size}", content, flags=re.IGNORECASE)
        return content if content.endswith("\n") else content + "\n"
    return _generate_default_header(config, resolution)

def _generate_default_header(config: SubtitleConfig, resolution: tuple[int, int]) -> str:
    return f"[Script Info]\nScriptType: v4.00+\nPlayResX: {resolution[0]}\nPlayResY: {resolution[1]}\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: {config.style_name},{config.font_name},{config.font_size},{config.primary_colour},{config.secondary_colour},&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,2,2,120,120,60,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
