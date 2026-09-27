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
# 主题调色板
# ---------------------------------------------------------------------------

COLOR_PALETTES: dict[str, dict[str, str]] = {
    "apple_white": {
        "name": "极简珍珠白",
        "primary": "&H00FFFFFF",    # 纯白 (已唱)
        "secondary": "&H66FFFFFF",  # 半透明白 (未唱)
        "outline": "&H99000000",    # 暗色半透明描边
    },
    "cyber_neon": {
        "name": "赛博霓虹",
        "primary": "&H00FFFF00",    # 电光青 (已唱)
        "secondary": "&H66FF007F",  # 霓虹粉 (未唱)
        "outline": "&HAA050510",
    },
    "amber_gold": {
        "name": "复古黑胶金",
        "primary": "&H0000D7FF",    # 琥珀金 (已唱)
        "secondary": "&H661E69D2",  # 复古铜褐 (未唱)
        "outline": "&H990F0B05",
    },
    "midnight_purple": {
        "name": "极光冷艳紫",
        "primary": "&H00FFB0E0",    # 薰衣草亮白紫 (已唱)
        "secondary": "&H66E22B8A",  # 幽邃紫 (未唱)
        "outline": "&HAA100520",
    },
    "emerald_mint": {
        "name": "清爽翡翠绿",
        "primary": "&H007FFF00",    # 薄荷荧光绿 (已唱)
        "secondary": "&H66408000",  # 橄榄青 (未唱)
        "outline": "&H99052010",
    },
}


def apply_theme_palette(config: SubtitleConfig) -> SubtitleConfig:
    """如果配置了主题调色板，自动应用颜色"""
    theme = getattr(config, "theme", "apple_white")
    if theme in COLOR_PALETTES:
        pal = COLOR_PALETTES[theme]
        # 若是默认值，则替换为对应主题色彩
        if config.primary_colour in ("&H00FFFFFF", pal["primary"]):
            config.primary_colour = pal["primary"]
            config.secondary_colour = pal["secondary"]
            config.outline_colour = pal["outline"]
    return config


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
    将对齐结果生成 ASS 卡拉OK字幕文件 (支持 Apple Music 滚动、经典双行、极简居中跳动)。
    """
    if config is None:
        config = SubtitleConfig()

    apply_theme_palette(config)

    play_res_x = getattr(config, "play_res_x", 1920)
    play_res_y = getattr(config, "play_res_y", 1080)
    margin_x = getattr(config, "margin_x", 100 if play_res_x >= 1920 else 70)

    log.info("生成 ASS 字幕: %d 行 (分辨率: %dx%d, 风格: %s, 模式: %s)",
             len(alignment.lines), play_res_x, play_res_y, getattr(config, 'theme', 'default'), config.render_mode)

    # 加载模板头部
    header = _load_template_header(config)

    # 自动换行处理 (根据实际视频分辨率自适应边距与最大宽度)
    max_width = play_res_x - 2 * margin_x
    alignment = _wrap_lines(alignment, max_width, config.font_size, config.font_name)
    log.info("自动换行后: %d 行 (最大宽度限制: %dpx)", len(alignment.lines), max_width)

    # 可选: 检测节奏点
    beat_times: list[float] = []
    if config.enable_beat_effects and audio_path is not None:
        beat_times = _detect_beats(audio_path)
        log.info("检测到 %d 个节奏点", len(beat_times))

    # 生成 Dialogue 行
    if config.render_mode == "tv":
        dialogue_lines = _generate_tv_events(alignment, config, beat_times)
    elif config.render_mode in ("center_bounce", "bounce", "center"):
        dialogue_lines = _generate_center_bounce_events(alignment, config, beat_times)
    else:
        # Apple Music 滚动效果 (默认)
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
    play_res_x = getattr(config, "play_res_x", 1920)
    play_res_y = getattr(config, "play_res_y", 1080)

    if template_path.exists():
        content = template_path.read_text(encoding="utf-8")
        # 校正分辨率，确保与 CompositorConfig 及当前版面比例一致
        content = re.sub(r"PlayResX:\s*\d+", f"PlayResX: {play_res_x}", content, flags=re.IGNORECASE)
        content = re.sub(r"PlayResY:\s*\d+", f"PlayResY: {play_res_y}", content, flags=re.IGNORECASE)
        
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
    play_res_x = getattr(config, "play_res_x", 1920)
    play_res_y = getattr(config, "play_res_y", 1080)
    margin_v = 60 if play_res_y <= 1080 else 120
    return f"""[Script Info]
Title: Auto-Karaoke MV
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {config.style_name},{config.font_name},{config.font_size},{config.primary_colour},{config.secondary_colour},{config.outline_colour},&HA0000000,-1,0,0,0,100,100,3,0,1,4,2,2,30,30,{margin_v},1

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
    play_res_x = getattr(config, "play_res_x", 1920)
    play_res_y = getattr(config, "play_res_y", 1080)
    margin_x = getattr(config, "margin_x", 100 if play_res_x >= 1920 else 70)

    if getattr(config, "center_y", None) is not None:
        center_y = config.center_y
    elif play_res_y > play_res_x:
        center_y = play_res_y * 0.44
    else:
        center_y = config.font_size * 4.5
        
    def parse_color(ass_color: str) -> tuple[str, str]:
        if ass_color.startswith("&H") and len(ass_color) >= 10:
            return "&H" + ass_color[2:4] + "&", "&H" + ass_color[4:10] + "&"
        return "&H00&", ass_color
        
    events = []
    for j in range(N):
        # 提取当前行专属的颜色样式覆盖
        overrides = getattr(lines[j], 'style_overrides', {}) if hasattr(lines[j], 'style_overrides') else {}
        line_pri = overrides.get("primary_colour", config.primary_colour)
        line_sec = overrides.get("secondary_colour", config.secondary_colour)
        
        a_pri, c_pri = parse_color(line_pri)
        a_sec, c_sec = parse_color(line_sec)
        
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
                pos_tag = f"\\pos({margin_x},{y_start:.1f})"
            else:
                pos_tag = f"\\move({margin_x},{y_start:.1f},{margin_x},{y_end:.1f},{t1},{t2})"
                
            anim_tag = f"\\t({t1},{t2},{tag_end})" if tag_start != tag_end else ""
            tags = f"\\an4{pos_tag}{tag_start}{anim_tag}"
            
            if k == j:
                tag_steady = get_tags(0, True, False, False)
                karaoke_text = ""
                current_t = lines[j].start
                
                for word in lines[j].words:
                    # 计算当前字和上一个字之间的静音空白 gap
                    gap_cs = round((word.start - current_t) * 100)
                    if gap_cs > 0:
                        karaoke_text += f"{{\\k{gap_cs}}}"
                    
                    # 当前字的持续时间
                    dur_cs = max(0, round((word.end - max(word.start, current_t)) * 100))
                        
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

# TV 风格: 双行交替居中 (经典 KTV)
# ---------------------------------------------------------------------------

def _generate_tv_events(
    alignment: AlignmentResult,
    config: SubtitleConfig,
    beat_times: list[float],
) -> list[str]:
    """
    经典 KTV 双行交替字幕 — 始终显示两行:
    - 屏幕下方固定两个位置 (上行 / 下行)
    - 偶数句(0,2,4…)在上行，奇数句(1,3,5…)在下行
    - 当前演唱行: 过光高亮 (\\k/\\kf)
    - 下一行: 暗色预览，提前显示以便观众跟读
    - 唱完后文字保持高亮，直到同位置的下一句替换它

    时间轴 (以第 i 行为例):
      预览阶段: lines[i-1].start → lines[i].start   (暗色静态)
      演唱阶段: lines[i].start   → lines[i+1].start  (卡拉OK过光)
    """
    lines = alignment.lines
    N = len(lines)
    if N == 0:
        return []

    # 布局: 上行靠左，下行靠右，间距加大
    play_res_x = getattr(config, "play_res_x", 1920)
    play_res_y = getattr(config, "play_res_y", 1080)
    margin_x = getattr(config, "margin_x", 100 if play_res_x >= 1920 else 70)

    if play_res_y > play_res_x:
        # 竖屏 9:16
        y_upper = int(play_res_y * 0.76)
        y_lower = int(play_res_y * 0.84)
        margin = margin_x
        x_left  = margin
        x_right = play_res_x - margin
    else:
        # 横屏 16:9
        y_upper = 850    # 上行
        y_lower = 960    # 下行 (间距 110px)
        margin = 360
        x_left  = margin    # 左对齐 x
        x_right = 1920 - margin   # 右对齐 x

    # 配色: 支持使用配置中的主题色或经典 KTV 配色
    theme = getattr(config, "theme", "apple_white")
    if theme in COLOR_PALETTES and theme != "apple_white":
        pal = COLOR_PALETTES[theme]
        color_sung = pal["primary"] + ("&" if not pal["primary"].endswith("&") else "")
        color_unsunng = pal["secondary"] + ("&" if not pal["secondary"].endswith("&") else "")
    else:
        # 经典 KTV 配色
        color_sung = "&HFFFF00&"     # 青色 (已唱/过光后)
        color_unsunng = "&H00FFFFFF&"  # 白色 (未唱)
    color_dim = color_unsunng      # 预览暗色

    events = []

    def _build_karaoke(line, event_start) -> str:
        """为一行构建带前导等待的卡拉OK标签文本"""
        parts = []
        current_t = event_start

        for word in line.words:
            gap_cs = int((word.start - current_t) * 100)
            if gap_cs > 0:
                parts.append(f"{{\\k{gap_cs}}}")

            dur_cs = int((word.end - max(word.start, current_t)) * 100)
            if dur_cs < 0:
                dur_cs = 0

            k_tag = "kf" if config.use_karaoke_gradient else "k"
            parts.append(f"{{\\{k_tag}{dur_cs}}}{word.word}")
            current_t = max(word.end, current_t)

        return "".join(parts)

    for i in range(N):
        line = lines[i]
        is_upper = (i % 2 == 0)
        y_pos = y_upper if is_upper else y_lower
        # 上行靠左(\an4), 下行靠右(\an6)
        an = "\\an4" if is_upper else "\\an6"
        x_pos = x_left if is_upper else x_right

        # ── 预览阶段 (暗色白字) ──
        if i > 0:
            preview_start = lines[i - 1].start
        else:
            preview_start = max(0, line.start - 2.0)

        preview_end = line.start

        if preview_end > preview_start + 0.05:
            ass_ps = seconds_to_ass_time(preview_start)
            ass_pe = seconds_to_ass_time(preview_end)
            dim_tags = f"{an}\\pos({x_pos},{y_pos})\\1c{color_dim}\\1a&H00&"
            events.append(
                f"Dialogue: 0,{ass_ps},{ass_pe},{config.style_name},,0,0,0,,"
                f"{{{dim_tags}}}{line.text}"
            )

        # ── 演唱阶段 (白→青色过光) ──
        active_start = line.start
        if i + 1 < N:
            active_end = lines[i + 1].start
        else:
            active_end = line.end + 2.0
        active_end = max(active_end, line.end + 0.1)

        ass_as = seconds_to_ass_time(active_start)
        ass_ae = seconds_to_ass_time(active_end)

        karaoke_text = _build_karaoke(line, active_start)
        # \1c = 过光后颜色(已唱=青色), \2c = 过光前颜色(未唱=白色), \1a\2a = 强制不透明
        active_tags = f"{an}\\pos({x_pos},{y_pos})\\1c{color_sung}\\2c{color_unsunng}\\1a&H00&\\2a&H00&"
        events.append(
            f"Dialogue: 0,{ass_as},{ass_ae},{config.style_name},,0,0,0,,"
            f"{{{active_tags}}}{karaoke_text}"
        )

    return events


# ---------------------------------------------------------------------------
# 极简居中跳动风格 (TikTok / Reels 爆款单行居中)
# ---------------------------------------------------------------------------

def _generate_center_bounce_events(
    alignment: AlignmentResult,
    config: SubtitleConfig,
    beat_times: list[float],
) -> list[str]:
    """
    极简居中动效:
    - 当前演唱行在屏幕居中偏下黄金位置 (\\an5)
    - 入场微缩放弹跳 (\\t(0, 140, \\fscx108\\fscy108)\\t(140, 280, \\fscx100\\fscy100))
    - \\kf 卡拉OK顺滑过光
    - 离场平滑淡出
    - 下一句弱显预览
    """
    lines = alignment.lines
    N = len(lines)
    if N == 0:
        return []

    play_res_x = getattr(config, "play_res_x", 1920)
    play_res_y = getattr(config, "play_res_y", 1080)
    center_x = play_res_x / 2.0

    if getattr(config, "center_y", None) is not None:
        center_y = config.center_y
    elif play_res_y > play_res_x:
        # 竖屏 9:16: 居中偏下 58% (避开顶部封面与底部控件)
        center_y = play_res_y * 0.58
    else:
        # 横屏 16:9: 居中偏下 65%
        center_y = play_res_y * 0.65

    events = []
    k_tag = "kf" if config.use_karaoke_gradient else "k"

    for i in range(N):
        curr = lines[i]
        start_t = curr.start
        end_t = lines[i + 1].start if i < N - 1 else curr.end + 2.0

        ass_start = seconds_to_ass_time(start_t)
        ass_end = seconds_to_ass_time(end_t)

        # 构建当前句卡拉OK过光
        karaoke_parts = []
        c_time = start_t
        for w in curr.words:
            gap_cs = int((w.start - c_time) * 100)
            if gap_cs > 0:
                karaoke_parts.append(f"{{\\k{gap_cs}}}")
            dur_cs = max(0, int((w.end - max(w.start, c_time)) * 100))
            karaoke_parts.append(f"{{\\{k_tag}{dur_cs}}}{w.word}")
            c_time = max(w.end, c_time)
        karaoke_text = "".join(karaoke_parts)

        # 弹跳动画与淡入淡出
        bounce_tags = (
            f"\\an5\\pos({center_x:.1f},{center_y:.1f})"
            f"\\fad(150,200)"
            f"\\t(0,140,\\fscx108\\fscy108)\\t(140,280,\\fscx100\\fscy100)"
        )
        events.append(
            f"Dialogue: 1,{ass_start},{ass_end},{config.style_name},,0,0,0,,"
            f"{{{bounce_tags}}}{karaoke_text}"
        )

        # 下一句预览 (弱显半透明)
        if i + 1 < N:
            nxt = lines[i + 1]
            sub_y = center_y + config.font_size * 1.5
            dim_tags = (
                f"\\an5\\pos({center_x:.1f},{sub_y:.1f})"
                f"\\1a&HAA&\\2a&HAA&\\fscx85\\fscy85\\blur2"
                f"\\fad(200,200)"
            )
            events.append(
                f"Dialogue: 0,{ass_start},{ass_end},{config.style_name},,0,0,0,,"
                f"{{{dim_tags}}}{nxt.text}"
            )

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


def _create_dialogue_line(
    line: AlignedLine,
    config: SubtitleConfig,
    beat_times: list[float] | None = None,
) -> str:
    """生成单行基础 Dialogue 事件（支持 \\k / \\kf 与 beat 缩放特效）"""
    k_tag = "kf" if getattr(config, "use_karaoke_gradient", False) else "k"
    karaoke_parts = []
    current_t = line.start

    for word in line.words:
        gap_cs = round((word.start - current_t) * 100)
        if gap_cs > 0:
            karaoke_parts.append(f"{{\\k{gap_cs}}}")

        dur_cs = max(0, round((word.end - max(word.start, current_t)) * 100))
        anim = _get_beat_effect(word.start, word.end, beat_times or [], config)
        prefix = f"{{{anim}}}" if anim else ""
        karaoke_parts.append(f"{prefix}{{\\{k_tag}{dur_cs}}}{word.word}")
        current_t = max(word.end, current_t)

    karaoke_text = "".join(karaoke_parts)
    start_str = seconds_to_ass_time(line.start)
    end_str = seconds_to_ass_time(line.end)
    return f"Dialogue: 0,{start_str},{end_str},{config.style_name},,0,0,0,,{karaoke_text}"

