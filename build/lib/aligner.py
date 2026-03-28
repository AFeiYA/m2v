"""
Module 3: 词级对齐引擎
- WhisperX forced alignment 封装
- 支持 Forced Alignment（传入原歌词约束，避免自由转写）
- Fallback: 对齐失败的行按时长均分给每个字符
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from src.config import AlignerConfig
from src.preprocessor import LyricLine
from src.utils import log


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class WordTimestamp:
    """单个字/词的时间戳"""
    word: str
    start: float   # 秒
    end: float      # 秒


@dataclass
class AlignedLine:
    """一行对齐后的歌词"""
    text: str
    start: float
    end: float
    words: list[WordTimestamp]


@dataclass
class AlignmentResult:
    """完整对齐结果"""
    lines: list[AlignedLine]

    def to_dict(self) -> dict:
        return {"lines": [asdict(line) for line in self.lines]}

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        log.info("对齐结果已保存: %s", path.name)

    @classmethod
    def load_json(cls, path: Path) -> "AlignmentResult":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        lines = []
        for line_data in data["lines"]:
            words = [WordTimestamp(**w) for w in line_data["words"]]
            lines.append(AlignedLine(
                text=line_data["text"],
                start=line_data["start"],
                end=line_data["end"],
                words=words,
            ))
        return cls(lines=lines)


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def align_lyrics(
    vocals_path: Path,
    lyrics: list[LyricLine],
    config: AlignerConfig | None = None,
) -> AlignmentResult:
    """
    使用 WhisperX 对 vocals 音频和歌词文本进行词级 forced alignment。

    Args:
        vocals_path: 干声音频路径 (来自 Demucs 分离)
        lyrics:      预处理后的歌词行列表
        config:      对齐引擎配置

    Returns:
        AlignmentResult 包含每行每字的 start/end 时间戳
    """
    if config is None:
        config = AlignerConfig()

    log.info("开始词级对齐: %s (%d 行歌词)", vocals_path.name, len(lyrics))

    try:
        import whisperx
        import torch
    except ImportError as e:
        raise ImportError(
            "WhisperX 未安装。请运行: pip install whisperx\n"
            "或使用 Docker 环境运行本项目。"
        ) from e

    device = config.device
    if device == "cuda" and not torch.cuda.is_available():
        log.warning("CUDA 不可用，回退到 CPU 模式")
        device = "cpu"
        compute_type = "int8"
    else:
        compute_type = config.compute_type

    # -----------------------------------------------------------------------
    # Step 1: Whisper 转写 (获取 segment 级时间范围)
    # -----------------------------------------------------------------------
    log.info("加载 Whisper 模型: %s (device=%s, compute=%s)",
             config.whisper_model, device, compute_type)
    model = whisperx.load_model(
        config.whisper_model,
        device=device,
        compute_type=compute_type,
        language=config.language,
    )

    audio = whisperx.load_audio(str(vocals_path))
    log.info("Whisper 转写中…")
    transcribe_result = model.transcribe(
        audio,
        batch_size=config.batch_size,
        language=config.language,
    )

    # -----------------------------------------------------------------------
    # Step 2: 加载对齐模型并执行 forced alignment
    # -----------------------------------------------------------------------
    log.info("加载对齐模型 (language=%s)…", config.language)
    align_model, align_metadata = whisperx.load_align_model(
        language_code=config.language,
        device=device,
        model_name=config.align_model,
    )

    # 用原始歌词文本替换 Whisper 的自由转写结果 (forced alignment)
    transcribe_result = _inject_lyrics_into_segments(
        transcribe_result, lyrics
    )

    log.info("执行词级对齐…")
    align_result = whisperx.align(
        transcribe_result["segments"],
        align_model,
        align_metadata,
        audio,
        device=device,
        return_char_alignments=(config.language == "zh"),  # 中文用字符级
    )

    # -----------------------------------------------------------------------
    # Step 3: 解析结果，构建 AlignmentResult
    # -----------------------------------------------------------------------
    aligned_lines = _parse_alignment_result(align_result, lyrics)
    result = AlignmentResult(lines=aligned_lines)

    log.info("对齐完成: %d 行, %d 个词",
             len(result.lines),
             sum(len(line.words) for line in result.lines))
    return result


# ---------------------------------------------------------------------------
# 辅助: 将原始歌词注入 Whisper 转写结果
# ---------------------------------------------------------------------------

def _inject_lyrics_into_segments(
    transcribe_result: dict,
    lyrics: list[LyricLine],
) -> dict:
    """
    用原始歌词文本替换 Whisper 的自由转写文本，
    保留 Whisper 给出的 segment 时间范围。
    这样 align() 就会按正确的歌词做 forced alignment。
    """
    segments = transcribe_result.get("segments", [])

    if len(segments) == 0:
        # 如果 Whisper 没有输出 segment，手动构造
        log.warning("Whisper 未返回 segment，使用歌词手动构造")
        new_segments = []
        for i, lyric in enumerate(lyrics):
            new_segments.append({
                "text": lyric.text,
                "start": lyric.timestamp if lyric.timestamp is not None else i * 5.0,
                "end": (lyric.timestamp + 5.0) if lyric.timestamp is not None else (i + 1) * 5.0,
            })
        transcribe_result["segments"] = new_segments
        return transcribe_result

    # 将歌词按顺序分配给 segments
    # 策略: 如果 segment 数 != 歌词行数，尝试最佳匹配
    if len(segments) >= len(lyrics):
        # segments 多于歌词行 → 合并多余 segments
        for i, lyric in enumerate(lyrics):
            if i < len(segments):
                segments[i]["text"] = lyric.text
        transcribe_result["segments"] = segments[:len(lyrics)]
    else:
        # segments 少于歌词行 → 基于时间均分
        new_segments = []
        if segments:
            total_start = segments[0].get("start", 0.0)
            total_end = segments[-1].get("end", total_start + len(lyrics) * 5.0)
        else:
            total_start = 0.0
            total_end = len(lyrics) * 5.0

        duration_per_line = (total_end - total_start) / len(lyrics)
        for i, lyric in enumerate(lyrics):
            new_segments.append({
                "text": lyric.text,
                "start": total_start + i * duration_per_line,
                "end": total_start + (i + 1) * duration_per_line,
            })
        transcribe_result["segments"] = new_segments

    return transcribe_result


# ---------------------------------------------------------------------------
# 辅助: 解析 WhisperX 对齐输出
# ---------------------------------------------------------------------------

def _parse_alignment_result(
    align_result: dict,
    lyrics: list[LyricLine],
) -> list[AlignedLine]:
    """将 WhisperX align() 的输出转为 AlignedLine 列表"""
    segments = align_result.get("segments", [])
    aligned_lines: list[AlignedLine] = []

    for i, seg in enumerate(segments):
        text = seg.get("text", "").strip()
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", seg_start + 1.0)

        # 获取词级时间戳
        word_segments = seg.get("words", [])

        if word_segments:
            words = []
            for ws in word_segments:
                w = ws.get("word", "").strip()
                if not w:
                    continue
                w_start = ws.get("start")
                w_end = ws.get("end")
                # 某些词可能缺少时间戳
                if w_start is None or w_end is None:
                    continue
                words.append(WordTimestamp(word=w, start=w_start, end=w_end))

            if words:
                aligned_lines.append(AlignedLine(
                    text=text,
                    start=words[0].start,
                    end=words[-1].end,
                    words=words,
                ))
                continue

        # Fallback: 对齐失败 → 均分时长给每个字符
        log.warning("第 %d 行对齐失败，使用均分 fallback: '%s'", i + 1, text[:20])
        fallback_words = _fallback_even_split(text, seg_start, seg_end)
        if fallback_words:
            aligned_lines.append(AlignedLine(
                text=text,
                start=seg_start,
                end=seg_end,
                words=fallback_words,
            ))

    return aligned_lines


def _fallback_even_split(
    text: str,
    start: float,
    end: float,
) -> list[WordTimestamp]:
    """将一行文本按字符均分时长（fallback 策略）"""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return []

    duration = end - start
    char_duration = duration / len(chars)
    words = []
    for i, char in enumerate(chars):
        words.append(WordTimestamp(
            word=char,
            start=round(start + i * char_duration, 3),
            end=round(start + (i + 1) * char_duration, 3),
        ))
    return words
