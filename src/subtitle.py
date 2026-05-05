"""
Module 4: ASS 卡拉OK字幕生成器
- 词级 JSON → ASS \\k 标签
- 样式模板加载
- 可选: Librosa 节奏检测 → \\t 缩放动画
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
) -> Path:
    """
    将对齐结果生成 ASS 卡拉OK字幕文件 (Apple Music 风格)。
    """
    if config is None:
        config = SubtitleConfig()

    log.info("生成 ASS 字幕: %d 行", len(alignment.lines))

    # 加载模板头部
    header = _load_template_header(config)

    # 自动换行处理 (Apple Music 风格)
    max_width = 1920 - 200 # 左右边距各100
    alignment = _wrap_lines(alignment, max_width, config.font_size, config.font_name)
    log.info("自动换行后: %d 行", len(alignment.lines))

    # 可选: 检测节奏点
    beat_times: list[float] = []
    if config.enable_beat_effects and audio_path is not None:
        beat_times = _detect_beats(audio_path)
        log.info("检测到 %d 个节奏点", len(beat_times))

    # 生成 Dialogue 行 (Apple Music 滚动效果)
    dialogue_lines = _generate_apple_music_events(alignment, config, beat_times)

    # 组装完整 ASS 文件
    ass_content = header + "\n".join(dialogue_lines) + "\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(ass_content, encoding="utf-8-sig")  # BOM for compatibility

    log.info("ASS 字幕已生成: %s (%d 行 Dialogue)", output_path.name, len(dialogue_lines))
    return output_path

def _wrap_lines(alignment: AlignmentResult, max_width: int, font_size: int, font_name: str) -> AlignmentResult:
    """使用 Pillow 计算文本宽度并在单行内插入 \\N 实现自动换行，避免产生新的物理行导致滚动抖动"""
    import platform
    from PIL import ImageFont
    
    def get_fallback_font():
        system = platform.system()
        try:
            if system == "Windows": return ImageFont.truetype("msyh.ttc", font_size)
            elif system == "Darwin": return ImageFont.truetype("PingFang.ttc", font_size)
            else: return ImageFont.truetype("NotoSansCJK-Regular.ttc", font_size)
        except:
            return ImageFont.load_default()
            
    try:
        font = ImageFont.truetype(font_name, font_size)
    except:
        try:
            font = ImageFont.truetype(f"{font_name}.ttf", font_size)
        except:
            font = get_fallback_font()
            
    for line in alignment.lines:
        current_width = 0.0
        for word in line.words:
            # 清理可能存在的旧换行符
            w_text = word.word.replace("\\N", "")
            try:
                w_len = font.getlength(w_text)
            except AttributeError:
                try:
                    w_len = font.getsize(w_text)[0]
                except:
                    w_len = len(w_text) * font_size
            
            if current_width + w_len > max_width and current_width > 0:
                word.word = "\\N" + w_text
                current_width = w_len
            else:
                word.word = w_text
                current_width += w_len
                
        # 更新行的总文本
        line.text = "".join(w.word for w in line.words)
        
    return alignment


# ---------------------------------------------------------------------------
# 模板加载
# ---------------------------------------------------------------------------

def _load_template_header(config: SubtitleConfig) -> str:
    """加载 ASS 模板文件的头部 (Script Info + Styles)"""
    template_path = config.template_path

    if template_path.exists():
        content = template_path.read_text(encoding="utf-8")
        # 强制校正分辨率，确保与 CompositorConfig (1920x1080) 一致
        content = re.sub(r"PlayResX:\s*\d+", "PlayResX: 1920", content, flags=re.IGNORECASE)
        content = re.sub(r"PlayResY:\s*\d+", "PlayResY: 1080", content, flags=re.IGNORECASE)
        
        # 强制应用配置中的颜色 (正则匹配 Style 行中的颜色部分)
        # ASS Format: ..., PrimaryColour, SecondaryColour, OutlineColour, BackColour, ...
        # 我们寻找指定的 Style 名称行并修改它
        pattern = rf"(Style:\s*{config.style_name},[^,]+,[^,]+,)(&H[0-9A-F]+),(&H[0-9A-F]+),(&H[0-9A-F]+)"
        replacement = rf"\1{config.primary_colour},{config.secondary_colour},{config.outline_colour}"
        content = re.sub(pattern, replacement, content, flags=re.IGNORECASE)

        # 强制更新字体大小
        content = re.sub(rf"(Style:\s*{config.style_name},[^,]+,)\d+", rf"\g<1>{config.font_size}", content, flags=re.IGNORECASE)
        # 确保以换行结尾
        if not content.endswith("\n"):
            content += "\n"
        return content

    # 如果模板不存在，生成默认头部
    log.warning("模板文件不存在: %s，使用内置默认样式", template_path)
    return _generate_default_header(config)


def _generate_default_header(config: SubtitleConfig) -> str:
    """生成默认 ASS 文件头部"""
    return f"""[Script Info]
Title: Auto-Karaoke MV
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {config.style_name},{config.font_name},{config.font_size},{config.primary_colour},{config.secondary_colour},{config.outline_colour},&H80000000,-1,0,0,0,100,100,2,0,1,3,1,2,30,30,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


# ---------------------------------------------------------------------------
# 单行 Dialogue 生成
# ---------------------------------------------------------------------------

def _generate_apple_music_events(alignment: AlignmentResult, config: SubtitleConfig, beat_times: list[float]) -> list[str]:
    lines = alignment.lines
    N = len(lines)
    if N == 0:
        return []
        
    # 构建时间槽 (Slots)
    # Event k 占据 [S_k, S_{k+1}] 的时间。在这个时间段结束时（最后0.5秒），焦点平滑转移到 k+1。
    slots = []
    for i in range(N):
        start_t = lines[i].start
        end_t = lines[i+1].start if i < N - 1 else lines[i].end + 3.0
        slots.append((start_t, end_t))
        
    # 计算相对 Y 坐标 (动态计算包含 \N 的多行文本高度)
    local_y = [0.0] * N
    for i in range(1, N):
        prev_lines = lines[i-1].text.count("\\N") + 1
        curr_lines = lines[i].text.count("\\N") + 1
        # 每行文本的视觉高度占比约 1.2，块间距 0.6
        dist = (prev_lines + curr_lines) * 0.6 * config.font_size + 0.6 * config.font_size
        local_y[i] = local_y[i-1] + dist
        
    # Apple Music 风格的焦点行通常偏上，给下方即将到来的歌词留出更多视野
    # 距离屏幕顶部大约相当于 2-3 行的距离
    center_y = config.font_size * 4.5
        
    def parse_color(ass_color: str) -> tuple[str, str]:
        if ass_color.startswith("&H") and len(ass_color) >= 10:
            return "&H" + ass_color[2:4] + "&", "&H" + ass_color[4:10] + "&"
        return "&H00&", ass_color
        
    a_pri, c_pri = parse_color(config.primary_colour)
    a_sec, c_sec = parse_color(config.secondary_colour)
    
    def get_alpha(d: int, base_a: str) -> str:
        try:
            base_val = int(base_a[2:4], 16)
        except:
            base_val = 128
        if d == 0:
            return base_a
        target = 255
        val = base_val + (target - base_val) * (d / 4.0)
        val = min(255, max(0, int(val)))
        return f"&H{val:02X}&"

    def get_tags(d: int, is_active: bool, is_before: bool, for_anim_end: bool = False) -> str:
        scale = max(100 - d * 5, 70) if d > 0 else 100
        blur = d * 2.5
        alpha = get_alpha(d, a_sec)
        c = c_sec if is_before else c_pri
        
        if is_active:
            if for_anim_end:
                return f"\\1c{c_sec}\\1a{a_sec}\\fscx100\\fscy100\\blur0"
            else:
                return f"\\1c{c_pri}\\1a{a_pri}\\2c{c_sec}\\2a{a_sec}\\fscx100\\fscy100\\blur0"
        else:
            return f"\\1c{c}\\1a{alpha}\\fscx{scale}\\fscy{scale}\\blur{blur:.1f}"
            
    events = []
    for j in range(N):
        # 扩大视野到前后 4 行，以展示深远的模糊渐变
        k_min = max(0, j-4)
        k_max = min(N-1, j+4)
        
        for k in range(k_min, k_max + 1):
            slot_start, slot_end = slots[k]
            
            # 过滤掉无效的过短槽位
            if slot_end <= slot_start:
                continue
                
            # 过渡动画总时长上限 0.6s
            trans_duration = min(0.6, slot_end - slot_start)
            t_base_start = slot_end - trans_duration
            
            # 计算延迟: 距离新焦点 (k+1) 越远，动画开始得越晚 (果冻/级联效应)
            d_new = abs(j - (k + 1))
            delay_step = trans_duration * 0.15 
            move_dur = trans_duration * 0.5    
            
            t1_offset = d_new * delay_step
            if t1_offset + move_dur > trans_duration:
                t1_offset = trans_duration - move_dur
                
            trans_start_t = t_base_start + t1_offset
            trans_end_t = trans_start_t + move_dur
            
            t1 = int((trans_start_t - slot_start) * 1000)
            t2 = int((trans_end_t - slot_start) * 1000)
            
            y_start = center_y + local_y[j] - local_y[k]
            y_end = center_y + local_y[j] - local_y[k+1] if k < N - 1 else center_y + local_y[j] - local_y[k]
            
            # 状态生成
            d_start = abs(j - k)
            is_active_start = (k == j)
            is_before_start = (k < j)
            tag_start = get_tags(d_start, is_active_start, is_before_start, False)
            
            d_end = abs(j - (k + 1))
            is_active_end = (k + 1 == j)
            is_before_end = (k + 1 < j)
            tag_end = get_tags(d_end, is_active_end, is_before_end, True)
            
            ass_t_start = seconds_to_ass_time(slot_start)
            ass_t_end = seconds_to_ass_time(slot_end)
            
            if y_start == y_end:
                pos_tag = f"\\pos(100,{y_start:.1f})"
            else:
                pos_tag = f"\\move(100,{y_start:.1f},100,{y_end:.1f},{t1},{t2})"
                
            anim_tag = f"\\t({t1},{t2},{tag_end})" if tag_start != tag_end else ""
            tags = f"\\an4{pos_tag}{tag_start}{anim_tag}"
            
            if k == j:
                tag_steady = get_tags(0, True, False, False)
                karaoke_text = ""
                current_t = lines[j].start
                
                for word in lines[j].words:
                    # 计算当前字和上一个字之间的静音空白 gap
                    gap_cs = int((word.start - current_t) * 100)
                    if gap_cs > 0:
                        karaoke_text += f"{{\\k{gap_cs}}}"
                    
                    # 当前字的持续时间
                    dur_cs = int((word.end - max(word.start, current_t)) * 100)
                    if dur_cs < 0: 
                        dur_cs = 0
                        
                    # 根据配置决定使用平滑过光 (\kf) 还是逐字跳跃 (\k)
                    k_tag = "kf" if config.use_karaoke_gradient else "k"
                    karaoke_text += f"{{\\{k_tag}{dur_cs}}}{word.word}"
                    current_t = max(word.end, current_t)
                
                # Active line uses tag_steady as its base!
                # We prepend pos_tag to tag_steady
                tags_active = f"\\an4{pos_tag}{tag_steady}{anim_tag}"
                events.append(f"Dialogue: 0,{ass_t_start},{ass_t_end},{config.style_name},,0,0,0,,{{{tags_active}}}{karaoke_text}")
            else:
                events.append(f"Dialogue: 0,{ass_t_start},{ass_t_end},{config.style_name},,0,0,0,,{{{tags}}}{lines[j].text}")

    # 按时间排序事件，让 ASS 文件看起来更整齐
    events.sort(key=lambda x: x.split(",")[1])
    return events


# ---------------------------------------------------------------------------
# 节奏同步动画 (可选)
# ---------------------------------------------------------------------------

def _detect_beats(audio_path: Path) -> list[float]:
    """使用 Librosa 检测音频节奏点 (onset times)"""
    try:
        import librosa
        y, sr = librosa.load(str(audio_path), sr=22050)
        # 使用 onset_detect 获取起始点
        onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units="frames")
        onset_times = librosa.frames_to_time(onset_frames, sr=sr)
        return onset_times.tolist()
    except ImportError:
        log.warning("Librosa 未安装，跳过节奏检测")
        return []
    except Exception as e:
        log.warning("节奏检测失败: %s", e)
        return []


def _get_beat_effect(
    word_start: float,
    word_end: float,
    beat_times: list[float],
    config: SubtitleConfig,
) -> str:
    """
    如果当前字的时间范围内有节奏点，返回 ASS \\t 缩放动画标签。
    效果: 字幕在 beat 处快速放大再缩回。
    """
    scale_pct = int(config.beat_scale * 100)

    for beat in beat_times:
        if word_start <= beat <= word_end:
            # beat 在当前字范围内 → 添加缩放脉冲
            # \t(t1, t2, \fscx110\fscy110) → 在 t1~t2 内放大
            beat_offset_ms = int((beat - word_start) * 1000)
            pulse_duration = 80  # ms
            return (
                f"\\t({beat_offset_ms},{beat_offset_ms + pulse_duration},"
                f"\\fscx{scale_pct}\\fscy{scale_pct})"
                f"\\t({beat_offset_ms + pulse_duration},{beat_offset_ms + pulse_duration * 2},"
                f"\\fscx100\\fscy100)"
            )
    return ""
