"""
Module 4: ASS 卡拉OK字幕生成器
- 词级 JSON → ASS \\k 标签
- 样式模板加载
- 可选: Librosa 节奏检测 → \\t 缩放动画
"""

from __future__ import annotations

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
    将对齐结果生成 ASS 卡拉OK字幕文件。

    Args:
        alignment:   词级对齐结果
        output_path: 输出 .ass 文件路径
        config:      字幕样式配置
        audio_path:  原始音频路径 (用于节奏检测, 可选)

    Returns:
        输出文件路径
    """
    if config is None:
        config = SubtitleConfig()

    log.info("生成 ASS 字幕: %d 行", len(alignment.lines))

    # 加载模板头部
    header = _load_template_header(config)

    # 可选: 检测节奏点
    beat_times: list[float] = []
    if config.enable_beat_effects and audio_path is not None:
        beat_times = _detect_beats(audio_path)
        log.info("检测到 %d 个节奏点", len(beat_times))

    # 生成 Dialogue 行
    dialogue_lines: list[str] = []
    for line in alignment.lines:
        ass_line = _create_dialogue_line(line, config, beat_times)
        dialogue_lines.append(ass_line)

    # 组装完整 ASS 文件
    ass_content = header + "\n".join(dialogue_lines) + "\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(ass_content, encoding="utf-8-sig")  # BOM for compatibility

    log.info("ASS 字幕已生成: %s (%d 行 Dialogue)", output_path.name, len(dialogue_lines))
    return output_path


# ---------------------------------------------------------------------------
# 模板加载
# ---------------------------------------------------------------------------

def _load_template_header(config: SubtitleConfig) -> str:
    """加载 ASS 模板文件的头部 (Script Info + Styles)"""
    template_path = config.template_path

    if template_path.exists():
        content = template_path.read_text(encoding="utf-8")
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

def _create_dialogue_line(
    line: AlignedLine,
    config: SubtitleConfig,
    beat_times: list[float],
) -> str:
    """
    生成一行 ASS Dialogue，包含 \\k 卡拉OK标签。

    ASS \\k 语法:  {\\k<centiseconds>}字符
    例: {\\k50}我  → "我" 字变色持续 500ms
    """
    start_time = seconds_to_ass_time(line.start)
    end_time = seconds_to_ass_time(line.end)

    # 构建卡拉OK文本
    karaoke_text = ""
    for word in line.words:
        duration_cs = seconds_to_centiseconds(word.end - word.start)

        # 可选: 在节奏点处添加缩放动画
        beat_effect = ""
        if beat_times and config.enable_beat_effects:
            beat_effect = _get_beat_effect(word.start, word.end, beat_times, config)

        karaoke_text += f"{{\\k{duration_cs}{beat_effect}}}{word.word}"

    return f"Dialogue: 0,{start_time},{end_time},{config.style_name},,0,0,0,,{karaoke_text}"


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
