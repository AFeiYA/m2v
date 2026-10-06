"""
Auto-Karaoke MV Generator — 词级对齐模块
采用方案二: 纯 Wav2Vec2 CTC Forced Alignment (音素/字符级强约束声学对齐)

核心架构与职责分工:
1. 有歌词场景 (自带 TXT/LRC 或 Suno 导入, 占比 95%+):
   - 100% 走纯 Wav2Vec2 CTC Forced Alignment 引擎;
   - 使用原歌词做强制对齐，并检测异常压缩与跨间奏错误;
   - 中英文双语分流声学模型 (WAV2VEC2_ASR_BASE_960H + XLSR-53 Chinese);
   - 毫秒级字级/音素级时间轴打点。
2. 无歌词场景 (纯音频导入):
   - 两步走架构: 先调用 transcribe_audio() (faster-whisper) 听写纯歌词文本;
   - 再将生成的歌词文本无缝送入 align_lyrics() 完成高精度 CTC 时间轴打点。
"""

from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

import numpy as np
import soundfile as sf
import torch
import torchaudio
from torchaudio.functional import forced_align, merge_tokens
from transformers import AutoModelForCTC, AutoProcessor

from src.config import AlignerConfig
from src.preprocessor import LyricLine
from src.utils import log

_whisper_cache: dict[tuple[str, str, str], Any] = {}


def _get_whisper(config: AlignerConfig | None = None) -> Any:
    from faster_whisper import WhisperModel

    if config is None:
        config = AlignerConfig()
    device = config.device
    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"
    compute_type = "int8" if device == "cpu" else "float16"
    model_size = config.whisper_model or "base"
    if device == "cpu" and model_size.startswith("large"):
        # CPU 运行环境下优先采用轻量且已缓存的 base 模型，避免大模型转写延迟过大
        model_size = "base"
    key = (model_size, device, compute_type)
    if key not in _whisper_cache:
        log.info("【多语言 Whisper 引擎】加载 Whisper: %s (device=%s, compute=%s)", model_size, device, compute_type)
        _whisper_cache[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
    return _whisper_cache[key]

# ---------------------------------------------------------------------------
# 数据结构 (统一由 Pydantic v2 强类型体系提供)
# ---------------------------------------------------------------------------
from src.storyboard_schema import (
    WordTimestamp,
    AlignedLine,
    MusicSection,
    ShotPlan,
    StoryboardEvent,
    VisualBible,
    AlignmentProject,
    AlignmentResult,
)

_CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


# ---------------------------------------------------------------------------
# 自动开唱点与前奏检测 (Vocal Onset Detection)
# ---------------------------------------------------------------------------

def detect_vocal_onset(
    vocals_path: Path,
    rms_threshold: float = 0.02,
    window_sec: float = 0.1,
    min_continuous_sec: float = 0.3,
) -> float:
    """
    通过扫描人声音轨的 RMS 能量包络，检测真实开唱时间点 (秒)。
    跳过前奏中的伴奏渗漏、呼吸音或极短杂音。
    """
    try:
        wav, sr = sf.read(str(vocals_path), dtype="float32", always_2d=False)
        if wav.ndim > 1:
            wav = wav.mean(axis=1)

        total_dur = len(wav) / sr
        hop_len = int(sr * window_sec)
        num_frames = (len(wav) - hop_len) // hop_len
        if num_frames <= 0:
            return 0.0

        rms = np.array([
            np.sqrt(np.mean(wav[i * hop_len: i * hop_len + hop_len] ** 2))
            for i in range(num_frames)
        ])

        max_rms = float(np.max(rms)) if len(rms) > 0 else 0.0
        if max_rms < 1e-4:
            return 0.0

        adaptive_thresh = max(rms_threshold, max_rms * 0.12)
        consecutive_needed = max(1, int(min_continuous_sec / window_sec))

        voiced_blocks = []
        in_block = False
        block_start = 0.0

        for i, r in enumerate(rms):
            t = i * window_sec
            if r >= adaptive_thresh:
                if not in_block:
                    in_block = True
                    block_start = t
            else:
                if in_block:
                    in_block = False
                    dur = t - block_start
                    if dur >= min_continuous_sec:
                        voiced_blocks.append((round(block_start, 2), round(t, 2)))

        if in_block:
            dur = (num_frames * window_sec) - block_start
            if dur >= min_continuous_sec:
                voiced_blocks.append((round(block_start, 2), round(num_frames * window_sec, 2)))

        if not voiced_blocks:
            return 0.0

        # A later pause may be an interlude after an opening vocal shout.
        # Never discard earlier voiced blocks solely because a long gap follows.
        return voiced_blocks[0][0]

    except Exception as e:
        log.warning("自动开唱检测异常 (不影响后续流程): %s", e)
        return 0.0


# ---------------------------------------------------------------------------
# 歌词语言与时间锚点数据契约
# ---------------------------------------------------------------------------

class WhisperWordAnchor(BaseModel):
    """Whisper 转写词级时间戳锚点"""
    word: str
    start: float
    end: float
    probability: float = 1.0


class WhisperSegmentAnchor(BaseModel):
    """Whisper 转写片段级时间戳锚点"""
    id: int = 0
    text: str
    start: float
    end: float
    language: str = "en"
    words: list[WhisperWordAnchor] = Field(default_factory=list)


def detect_line_lang(text: str) -> str:
    """
    检测歌词行的语言类型:
    - zh: 中文 (汉字为主)
    - ja: 日语 (含假名)
    - ko: 韩语 (含谚文)
    - other: 其它语言 (法语/德语/西语/意语等含变音符拉丁字母或特定特征词)
    - en: 英文 (标准英文字母为主)
    """
    if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    zh = len(_CHINESE_CHAR_RE.findall(text))
    latin = len(re.findall(r"[a-zA-Z\u00C0-\u024F]", text))
    if zh > latin:
        return "zh"
    if latin == 0:
        return "zh" if zh > 0 else "en"
    accented = len(re.findall(r"[\u00C0-\u024F]", text))
    if accented > 0:
        return "other"
    tokens = set(re.findall(r"[a-zA-Z]+", text.lower()))
    if tokens & {
        "les", "des", "sur", "avec", "dans", "pour", "une", "croissants",
        "moi", "toi", "doux", "quand", "est", "sont", "nous", "vous",
        "el", "la", "los", "las", "del", "por", "para", "con", "una",
        "und", "der", "die", "das", "mit", "nicht", "eine", "einer"
    }:
        return "other"
    return "en"


_detect_line_lang = detect_line_lang


# ---------------------------------------------------------------------------
# 歌词分词与辅助工具
# ---------------------------------------------------------------------------

def tokenize_lyric_line(text: str) -> list[str]:
    """
    将单行歌词拆分为最小对齐单元 (Tokens):
    - 中文汉字: 按单个字符切分 (如 '靠窗的位子' -> ['靠', '窗', '的', '位', '子'])
    - 英文单词: 按单词切分并保留后导空格 (如 'Give me ' -> ['Give ', 'me '])
    - 标点符号: 附着在相邻单词或独立
    """
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if _CHINESE_CHAR_RE.match(char):
            # 汉字单字切分，同时吸附其后的标点
            j = i + 1
            while j < n and not _CHINESE_CHAR_RE.match(text[j]) and not text[j].isalnum() and not text[j].isspace():
                j += 1
            tokens.append(text[i:j])
            i = j
        elif char.isalnum() or char in ("'", "-"):
            # 英文单词连续捕获
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in ("'", "-")):
                j += 1
            # 吸附词尾空格 (卡拉OK排版关键)
            while j < n and text[j].isspace():
                j += 1
            tokens.append(text[i:j])
            i = j
        elif char.isspace():
            i += 1
        else:
            tokens.append(char)
            i += 1
    return tokens


def _fallback_even_split(
    text: str,
    start: float,
    end: float,
) -> list[WordTimestamp]:
    """将一行文本按字符均分时长 (兜底 fallback 策略)"""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return []

    duration = max(0.05, end - start)
    char_duration = duration / len(chars)
    words = []
    for i, char in enumerate(chars):
        words.append(WordTimestamp(
            word=char,
            start=round(start + i * char_duration, 3),
            end=round(start + (i + 1) * char_duration, 3),
        ))
    return words


def _fill_annotation_times(aligned_lines: list[AlignedLine]) -> None:
    """回填编曲说明行 ([Intro], [Solo] 等) 的时间区间"""
    n = len(aligned_lines)
    for i, line in enumerate(aligned_lines):
        if not line.words or (line.words[0].word == line.text and line.start == 0.0 and line.end == 0.0):
            prev_end = 0.0
            for j in range(i - 1, -1, -1):
                if aligned_lines[j].end > 0:
                    prev_end = aligned_lines[j].end
                    break

            next_start = prev_end + 1.0
            for j in range(i + 1, n):
                if aligned_lines[j].start > 0:
                    next_start = aligned_lines[j].start
                    break

            fill_start = prev_end
            fill_end = max(fill_start + 0.5, min(next_start, fill_start + 4.0))
            line.start = round(fill_start, 3)
            line.end = round(fill_end, 3)
            line.words = [WordTimestamp(word=line.text, start=line.start, end=line.end)]


def alignment_quality_issue(lines: list[AlignedLine]) -> str | None:
    """Reject widespread CTC collapse; monotonic timestamps alone are not quality."""
    words = [word for line in lines
             if not re.fullmatch(r'\[.*\]|[（(].*[）)]', line.text.strip())
             for word in line.words
             if re.search(r"[\w\u4e00-\u9fff]", word.word)]
    if len(words) >= 12:
        collapsed = sum(word.end - word.start <= 0.035 for word in words)
        if collapsed / len(words) >= 0.4:
            return f"{collapsed}/{len(words)} 个字词不足 35 毫秒，存在大面积时间挤压"
    stretched = [word for word in words if word.end - word.start > 20]
    if stretched:
        return "单个字词占用超过 20 秒，可能错误跨越间奏或匹配错区间"
    return None


def _trim_word_over_silence(start: float, end: float, singing_sections: list[tuple[float, float]]) -> float:
    """A word must not absorb a long silent intro before its acoustic match."""
    if end - start > 4.0:
        for before, after in zip(singing_sections, singing_sections[1:]):
            if start < before[1] and end > after[0] and after[0] - before[1] >= 3.5 and end - after[0] <= 4.0:
                start = after[0]
    return start


def _audit_alignment(aligned: list[AlignedLine]) -> list[AlignedLine]:
    """审计对齐时间戳单调性与合理性"""
    out: list[AlignedLine] = []
    prev_end = 0.0
    for line in aligned:
        cur_start = max(line.start, prev_end)
        cur_end = max(line.end, cur_start + 0.1)

        audited_words = []
        w_prev = cur_start
        for w in line.words:
            ws = max(w.start, w_prev)
            we = max(w.end, ws + 0.02)
            audited_words.append(WordTimestamp(word=w.word, start=round(ws, 3), end=round(we, 3)))
            w_prev = we

        line_start = audited_words[0].start if audited_words else cur_start
        line_end = audited_words[-1].end if audited_words else cur_end
        out.append(AlignedLine(
            text=line.text,
            start=round(line_start, 3),
            end=round(line_end, 3),
            words=audited_words,
        ))
        prev_end = line_end
    return out


# ---------------------------------------------------------------------------
# 方案二: 纯 Wav2Vec2 CTC Forced Alignment 核心引擎
# ---------------------------------------------------------------------------

def align_lyrics(
    vocals_path: Path,
    lyrics: list[LyricLine],
    config: AlignerConfig | None = None,
    allow_self_heal: bool = True,
) -> AlignmentResult:
    """
    词级强约束声学对齐统一主入口 (默认且唯一标准: Wav2Vec2 CTC Forced Alignment)
    """
    return align_lyrics_ctc(vocals_path, lyrics, config, allow_self_heal=allow_self_heal)


def align_lyrics_ctc(
    vocals_path: Path,
    lyrics: list[LyricLine],
    config: AlignerConfig | None = None,
    allow_self_heal: bool = True,
) -> AlignmentResult:
    """
    方案二: 纯 Wav2Vec2 CTC Forced Alignment 词级对齐引擎:
    - 使用原歌词的 CTC 强制对齐，失败时明确报告，不能保证任意唱法均匹配
    - 英文声学模型: torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
    - 中文声学模型: jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn
    - 结合开唱点检测 (Vocal Onset) 与 RMS 能量间奏隔离机制，乐句级强约束精确打点
    """
    if config is None:
        config = AlignerConfig()

    log.info("【方案二: 纯 CTC Forced Alignment】启动词级声学对齐: %s (%d 行歌词)", vocals_path.name, len(lyrics))

    # 1. 开唱点检测
    min_start = config.lyrics_start_time if config else 0.0
    if min_start <= 0:
        min_start = detect_vocal_onset(vocals_path)
        if min_start > 0:
            log.info("自动检测到开唱点: %.2fs (已锁死前奏区间)", min_start)

    # 2. 读取音频并重采样为 16kHz
    wav, sr = sf.read(str(vocals_path), dtype="float32", always_2d=False)
    if wav.ndim > 1:
        wav = wav.mean(axis=1)

    wav_t = torch.from_numpy(wav).unsqueeze(0)
    wav_16k = torchaudio.functional.resample(wav_t, orig_freq=sr, new_freq=16000)
    total_audio_sec = wav_16k.size(1) / 16000.0

    # 3. RMS 能量扫描，识别有效人声大段落
    hop = int(sr * 0.1)
    rms_vals = [float(np.sqrt(np.mean(wav[i:i + hop] ** 2))) for i in range(0, len(wav) - hop, hop)]
    times = [i / sr for i in range(0, len(wav) - hop, hop)]
    is_voiced = [r > 0.015 for r in rms_vals]

    raw_blocks = []
    in_voice = False
    start_t = 0.0
    for i, v in enumerate(is_voiced):
        t = times[i]
        if v and not in_voice:
            in_voice = True
            start_t = t
        elif not v and in_voice:
            in_voice = False
            if t - start_t >= 0.5:
                raw_blocks.append((round(start_t, 2), round(t, 2)))
    if in_voice:
        raw_blocks.append((round(start_t, 2), round(times[-1], 2)))

    # 合并相隔 < 2.8s 的小停顿，保留大间奏与 Solo
    singing_sections = []
    for b in raw_blocks:
        if b[1] < min_start:
            continue
        if not singing_sections:
            singing_sections.append(b)
        else:
            prev_s, prev_e = singing_sections[-1]
            if b[0] - prev_e < 2.8:
                singing_sections[-1] = (prev_s, b[1])
            else:
                singing_sections.append(b)

    log.info("人声检测发现 %d 个主要歌唱乐段: %s", len(singing_sections), singing_sections)

    # 4. 歌词按语言分流
    singing_lyrics: list[tuple[int, LyricLine]] = [(idx, ly) for idx, ly in enumerate(lyrics) if not ly.is_annotation]

    lang_runs: list[tuple[str, list[tuple[int, LyricLine]]]] = []
    cur_run: list[tuple[int, LyricLine]] = []
    cur_lang = None
    for item in singing_lyrics:
        idx, ly = item
        lang = detect_line_lang(ly.text)
        if cur_lang is None or lang == cur_lang:
            cur_run.append(item)
            cur_lang = lang
        else:
            lang_runs.append((cur_lang, cur_run))
            cur_run = [item]
            cur_lang = lang
    if cur_run:
        lang_runs.append((cur_lang, cur_run))

    log.info("歌词分为 %d 个语言乐句块: %s", len(lang_runs), [(lang, len(lines)) for lang, lines in lang_runs])

    # 5. 加载声学模型 (按需加载)
    has_en = any(lang == "en" for lang, _ in lang_runs)
    has_zh = any(lang == "zh" for lang, _ in lang_runs)

    model_en, dict_en = None, None
    if has_en:
        log.info("加载英文 Wav2Vec2 声学模型 (WAV2VEC2_ASR_BASE_960H)…")
        bundle_en = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
        model_en = bundle_en.get_model()
        labels_en = bundle_en.get_labels()
        dict_en = {c: i for i, c in enumerate(labels_en)}

    model_zh, proc_zh, blank_zh = None, None, 0
    if has_zh:
        log.info("加载中文 Wav2Vec2 声学模型 (jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn)…")
        model_zh_name = "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn"
        hub_dir = Path.home() / ".cache/huggingface/hub/models--jonatasgrosman--wav2vec2-large-xlsr-53-chinese-zh-cn/snapshots"
        local_target = None
        if hub_dir.exists():
            for snap in hub_dir.iterdir():
                if snap.is_dir() and (snap / "preprocessor_config.json").exists() and (snap / "vocab.json").exists():
                    local_target = str(snap)
                    break
        load_source = local_target or model_zh_name
        try:
            proc_zh = AutoProcessor.from_pretrained(load_source, local_files_only=True)
            model_zh = AutoModelForCTC.from_pretrained(load_source, local_files_only=True)
        except Exception:
            proc_zh = AutoProcessor.from_pretrained(load_source)
            model_zh = AutoModelForCTC.from_pretrained(load_source)
        model_zh.eval()
        blank_zh = proc_zh.tokenizer.pad_token_id or 0

    aligned_line_map: dict[int, AlignedLine] = {}

    def _align_en(lines_with_idx: list[tuple[int, LyricLine]], s_sec: float, e_sec: float):
        s_sec = max(0.0, s_sec - 0.2)
        e_sec = min(total_audio_sec, e_sec + 0.3)
        wav_slice = wav_16k[:, int(s_sec * 16000): int(e_sec * 16000)]
        if wav_slice.size(1) < 400:
            return

        with torch.inference_mode():
            emissions = torch.cat([model_en(chunk)[0].log_softmax(dim=-1)
                                   for chunk in wav_slice.split(20 * 16000, dim=1)
                                   if chunk.size(1) >= 400], dim=1)

        clean_lines = []
        for _, ly in lines_with_idx:
            words = [w.strip().upper() for w in ly.text.split() if w.strip()]
            clean_lines.append("|".join(words))

        full_text = "|".join(clean_lines)
        targets = torch.tensor([[dict_en.get(c, 0) for c in full_text if c in dict_en]], dtype=torch.int32)
        aligned_tokens, scores = forced_align(emissions, targets, blank=0)
        spans = merge_tokens(aligned_tokens[0], scores[0], blank=0)
        frame_dur = (wav_slice.size(1) / 16000.0) / emissions.size(1)

        span_idx = 0
        for li, (orig_idx, ly) in enumerate(lines_with_idx):
            line_str = clean_lines[li]
            target_count = len([c for c in line_str if c in dict_en])
            l_spans = spans[span_idx: span_idx + target_count]
            span_idx += target_count + 1

            words: list[WordTimestamp] = []
            tokens = tokenize_lyric_line(ly.text)
            curr_s_idx = 0
            for tok in tokens:
                tok_clean = "".join(c.upper() for c in tok if c.isalnum())
                if not tok_clean:
                    w_s = s_sec + l_spans[curr_s_idx].start * frame_dur if curr_s_idx < len(l_spans) else (words[-1].end if words else s_sec)
                    words.append(WordTimestamp(word=tok, start=round(w_s, 3), end=round(w_s, 3)))
                    continue
                w_spans = l_spans[curr_s_idx: curr_s_idx + len(tok_clean)]
                curr_s_idx += len(tok_clean) + 1
                if not w_spans:
                    prev_end = words[-1].end if words else s_sec
                    words.append(WordTimestamp(word=tok, start=round(prev_end, 3), end=round(prev_end + 0.1, 3)))
                    continue
                w_s = s_sec + w_spans[0].start * frame_dur
                w_e = s_sec + w_spans[-1].end * frame_dur
                w_s = _trim_word_over_silence(w_s, w_e, singing_sections)
                words.append(WordTimestamp(word=tok, start=round(w_s, 3), end=round(max(w_e, w_s + 0.05), 3)))

            aligned_line_map[orig_idx] = AlignedLine(
                text=ly.text,
                start=words[0].start if words else s_sec,
                end=words[-1].end if words else e_sec,
                words=words,
            )

    def _align_zh(lines_with_idx: list[tuple[int, LyricLine]], s_sec: float, e_sec: float):
        s_sec = max(0.0, s_sec - 0.2)
        e_sec = min(total_audio_sec, e_sec + 0.3)
        wav_slice = wav_16k[:, int(s_sec * 16000): int(e_sec * 16000)]
        if wav_slice.size(1) < 400:
            return

        with torch.inference_mode():
            emissions = torch.cat([model_zh(chunk).logits.log_softmax(dim=-1)
                                   for chunk in wav_slice.split(20 * 16000, dim=1)
                                   if chunk.size(1) >= 400], dim=1)

        clean_lines = []
        for _, ly in lines_with_idx:
            c_clean = "".join(c for c in ly.text if not c.isspace() and _CHINESE_CHAR_RE.match(c))
            clean_lines.append(c_clean)

        full_text = "".join(clean_lines)
        target_ids = proc_zh.tokenizer.convert_tokens_to_ids(list(full_text))
        targets = torch.tensor([target_ids], dtype=torch.int32)
        aligned_tokens, scores = forced_align(emissions, targets, blank=blank_zh)
        spans = merge_tokens(aligned_tokens[0], scores[0], blank=blank_zh)
        frame_dur = (wav_slice.size(1) / 16000.0) / emissions.size(1)

        span_idx = 0
        for li, (orig_idx, ly) in enumerate(lines_with_idx):
            line_str = clean_lines[li]
            target_count = len(line_str)
            l_spans = spans[span_idx: span_idx + target_count]
            span_idx += target_count

            words: list[WordTimestamp] = []
            tokens = tokenize_lyric_line(ly.text)
            curr_s_idx = 0
            for tok in tokens:
                tok_clean = "".join(c for c in tok if _CHINESE_CHAR_RE.match(c))
                if not tok_clean:
                    w_s = s_sec + l_spans[curr_s_idx].start * frame_dur if curr_s_idx < len(l_spans) else (words[-1].end if words else s_sec)
                    words.append(WordTimestamp(word=tok, start=round(w_s, 3), end=round(w_s, 3)))
                    continue
                w_spans = l_spans[curr_s_idx: curr_s_idx + len(tok_clean)]
                curr_s_idx += len(tok_clean)
                if not w_spans:
                    prev_end = words[-1].end if words else s_sec
                    words.append(WordTimestamp(word=tok, start=round(prev_end, 3), end=round(prev_end + 0.1, 3)))
                    continue
                w_s = s_sec + w_spans[0].start * frame_dur
                w_e = s_sec + w_spans[-1].end * frame_dur
                w_s = _trim_word_over_silence(w_s, w_e, singing_sections)
                if curr_s_idx < len(l_spans):
                    w_e = min(s_sec + l_spans[curr_s_idx].start * frame_dur, w_e + 0.15)
                else:
                    w_e = min(e_sec, w_e + 0.15)
                words.append(WordTimestamp(word=tok, start=round(w_s, 3), end=round(max(w_e, w_s + 0.05), 3)))

            aligned_line_map[orig_idx] = AlignedLine(
                text=ly.text,
                start=words[0].start if words else s_sec,
                end=words[-1].end if words else e_sec,
                words=words,
            )

    def _align_other(lines_with_idx: list[tuple[int, LyricLine]], s_sec: float, e_sec: float):
        sub_slice = wav[int(s_sec * sr): int(e_sec * sr)]
        all_w: list[tuple[float, float, str]] = []
        if len(sub_slice) > int(sr * 0.5):
            try:
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                    tmp_path = tf.name
                sf.write(tmp_path, sub_slice, sr)
                wm = _get_whisper(config)
                # 局部切片转写 (支持小切片的多语言自动识别)
                segments, _ = wm.transcribe(tmp_path, word_timestamps=True)
                for s in segments:
                    if s.words:
                        for w in s.words:
                            w_str = w.word.strip()
                            if w_str:
                                all_w.append((s_sec + w.start, s_sec + w.end, w_str))
                Path(tmp_path).unlink(missing_ok=True)
            except Exception as e:
                log.warning("多语言 Whisper 局部转写异常，转为平滑插值: %s", e)

        # 整理原歌词待对齐 tokens (以原歌词为不可篡改的 Ground Truth)
        all_line_toks: list[tuple[int, str, str]] = []  # (orig_idx, tok, clean)
        for orig_idx, ly in lines_with_idx:
            for tok in tokenize_lyric_line(ly.text):
                clean = "".join(c.lower() for c in tok if c.isalnum())
                all_line_toks.append((orig_idx, tok, clean))

        token_times: list[tuple[float, float] | None] = [None] * len(all_line_toks)
        match_sim = 0.0

        if all_w:
            w_cleans = ["".join(c.lower() for c in w[2] if c.isalnum()) for w in all_w]
            ly_cleans = [item[2] for item in all_line_toks]

            matcher = difflib.SequenceMatcher(None, ly_cleans, w_cleans)
            match_sim = matcher.ratio()
            for tag, alo, ahi, blo, bhi in matcher.get_opcodes():
                if tag == "equal":
                    for offset in range(ahi - alo):
                        wi = blo + offset
                        token_times[alo + offset] = (all_w[wi][0], all_w[wi][1])
                elif tag == "replace":
                    if blo < bhi:
                        ws = all_w[blo][0]
                        we = all_w[bhi - 1][1]
                        n_toks = ahi - alo
                        span = max(0.05, (we - ws) / max(1, n_toks))
                        for offset in range(n_toks):
                            token_times[alo + offset] = (ws + offset * span, ws + (offset + 1) * span)

        # 兜底插值未匹配的 token
        prev_t = s_sec
        unmatched_count = 0
        for i, (orig_idx, tok, clean) in enumerate(all_line_toks):
            if token_times[i] is None:
                unmatched_count += 1
                next_t = e_sec
                for j in range(i + 1, len(token_times)):
                    if token_times[j] is not None:
                        next_t = token_times[j][0]
                        break
                span_t = max(0.05, (next_t - prev_t) / max(1, sum(1 for k in range(i, len(token_times)) if token_times[k] is None)))
                token_times[i] = (prev_t, min(next_t, prev_t + span_t))
            prev_t = token_times[i][1]

        # 聚合为各行 AlignedLine 并检查置信度
        cur_tok_idx = 0
        total_l = len(lines_with_idx)
        l_dur = (e_sec - s_sec) / max(1, total_l)
        for li, (orig_idx, ly) in enumerate(lines_with_idx):
            tokens = tokenize_lyric_line(ly.text)
            words: list[WordTimestamp] = []
            for tok in tokens:
                if cur_tok_idx < len(all_line_toks):
                    ws, we = token_times[cur_tok_idx]
                    ws = _trim_word_over_silence(ws, we, singing_sections)
                    words.append(WordTimestamp(word=tok, start=round(ws, 3), end=round(max(we, ws + 0.05), 3)))
                    cur_tok_idx += 1

            exp_s = s_sec + li * l_dur
            exp_e = exp_s + l_dur
            is_low_conf = (match_sim < 0.4 or unmatched_count > len(all_line_toks) * 0.5)
            if is_low_conf:
                log.warning("第 %d 行歌词 (非中英语言) 识别匹配度偏低 (sim=%.2f)，建议在编辑器中复核时间轴: %s",
                            orig_idx + 1, match_sim, ly.text)

            aligned_line_map[orig_idx] = AlignedLine(
                text=ly.text,
                start=words[0].start if words else exp_s,
                end=words[-1].end if words else exp_e,
                words=words,
                style_overrides={"confidence": "low" if is_low_conf else "normal"},
            )

    def _dispatch_align(lang: str, lines: list[tuple[int, LyricLine]], s_sec: float, e_sec: float):
        if lang == "zh":
            _align_zh(lines, s_sec, e_sec)
        elif lang == "en":
            _align_en(lines, s_sec, e_sec)
        else:
            _align_other(lines, s_sec, e_sec)

    # 6. 整曲顺序 + 上下文锚点 + 声学遗漏审计 (Context-Bounded Global Anchor & Voicing Audit)
    # 6.1 提取自然歌词段落 (Stanzas)
    # 优先遵循歌词空行 (line.paragraph)。若未划分段落，则按语言切换或每 4 行形成自然段
    stanzas: list[list[tuple[int, LyricLine]]] = []
    has_explicit_paragraphs = any(ly.paragraph > 0 for _, ly in singing_lyrics)

    if has_explicit_paragraphs:
        cur_p = None
        cur_stanza: list[tuple[int, LyricLine]] = []
        for orig_idx, ly in singing_lyrics:
            if cur_p is None or ly.paragraph == cur_p:
                cur_stanza.append((orig_idx, ly))
                cur_p = ly.paragraph
            else:
                stanzas.append(cur_stanza)
                cur_stanza = [(orig_idx, ly)]
                cur_p = ly.paragraph
        if cur_stanza:
            stanzas.append(cur_stanza)
    else:
        # 无显式空行段落：按语言突变或每 4 行聚合
        cur_lang = None
        cur_stanza = []
        for orig_idx, ly in singing_lyrics:
            line_lang = detect_line_lang(ly.text)
            if cur_lang is None or (line_lang == cur_lang and len(cur_stanza) < 4):
                cur_stanza.append((orig_idx, ly))
                cur_lang = line_lang
            else:
                stanzas.append(cur_stanza)
                cur_stanza = [(orig_idx, ly)]
                cur_lang = line_lang
        if cur_stanza:
            stanzas.append(cur_stanza)

    log.info("歌词结构分析完成: 组织为 %d 个自然段落", len(stanzas))

    # 6.2 文本签名与上下文锚点标记 (Context Anchors)
    stanza_sigs = []
    sig_counts: dict[str, int] = {}
    for st in stanzas:
        sig = "".join(c.lower() for _, ly in st for c in ly.text if c.isalnum() or _CHINESE_CHAR_RE.match(c))
        stanza_sigs.append(sig)
        sig_counts[sig] = sig_counts.get(sig, 0) + 1

    is_repeated_stanza = [sig_counts[sig] > 1 for sig in stanza_sigs]

    # 估算每个段落的生理语速目标时长 (秒)
    stanza_target_durs: list[float] = []
    for st in stanzas:
        dur_est = 0.0
        for _, ly in st:
            l_lang = detect_line_lang(ly.text)
            if l_lang == "en":
                words = [w for w in ly.text.split() if w.strip()]
                dur_est += len(words) * 0.50 + 0.35
            else:
                chars = [c for c in ly.text if not c.isspace() and (c.isalnum() or _CHINESE_CHAR_RE.match(c))]
                dur_est += len(chars) * 0.33 + 0.35
        stanza_target_durs.append(max(1.8, dur_est))

    # 6.3 细粒度声学发音块提取与 RMS 能量微切分 (Micro-Voicing & Valley Split)
    # 步骤 A: 平滑微小声门停顿 (< 0.4s)，避免乐句断裂但保留乐句间呼吸 (>= 0.4s)
    base_blocks: list[tuple[float, float]] = []
    for b in raw_blocks:
        if b[1] < min_start:
            continue
        if not base_blocks:
            base_blocks.append(b)
        else:
            prev_s, prev_e = base_blocks[-1]
            if b[0] - prev_e < 0.4:
                base_blocks[-1] = (prev_s, b[1])
            else:
                base_blocks.append(b)

    # 步骤 B: 对较长的人声块 (> 5.5s)，沿局部 RMS 能量波谷 (呼吸/轻音断点) 细分为乐句级单元
    acoustic_sections: list[tuple[float, float]] = []
    for b_s, b_e in base_blocks:
        dur = b_e - b_s
        if dur > 5.5 and len(rms_vals) > 0:
            idx_s = max(0, int(b_s / 0.1))
            idx_e = min(len(rms_vals), int(b_e / 0.1))
            sub_rms = rms_vals[idx_s:idx_e]
            sub_times = times[idx_s:idx_e]
            num_splits = int(np.round(dur / 4.5))
            if num_splits > 1 and len(sub_rms) > 4:
                chunk_len = len(sub_rms) // num_splits
                cuts = [b_s]
                for si in range(1, num_splits):
                    center = si * chunk_len
                    w = int(1.2 / 0.1)
                    search_range = range(max(0, center - w), min(len(sub_rms), center + w))
                    best_k = min(search_range, key=lambda ki: sub_rms[ki])
                    cuts.append(round(sub_times[best_k], 2))
                cuts.append(b_e)
                for ci in range(len(cuts) - 1):
                    if cuts[ci + 1] > cuts[ci] + 0.3:
                        acoustic_sections.append((cuts[ci], cuts[ci + 1]))
            else:
                acoustic_sections.append((b_s, b_e))
        else:
            acoustic_sections.append((b_s, b_e))

    # 步骤 C: 确保声学块数量 M >= 段落数 K (若由于连唱导致 M < K，持续在最长块的能量最低点分裂)
    K = len(stanzas)
    while len(acoustic_sections) < K:
        longest_idx = max(range(len(acoustic_sections)), key=lambda i: acoustic_sections[i][1] - acoustic_sections[i][0])
        ls, le = acoustic_sections[longest_idx]
        if le - ls < 1.0:
            break
        mid_idx = int(((ls + le) / 2.0) / 0.1)
        w = max(1, int((le - ls) * 0.3 / 0.1))
        search_range = range(max(0, mid_idx - w), min(len(rms_vals), mid_idx + w))
        if search_range:
            best_k = min(search_range, key=lambda ki: rms_vals[ki])
            cut_t = round(times[best_k], 2)
        else:
            cut_t = round((ls + le) / 2.0, 2)
        if ls + 0.3 < cut_t < le - 0.3:
            acoustic_sections[longest_idx: longest_idx + 1] = [(ls, cut_t), (cut_t, le)]
        else:
            mid_t = round((ls + le) / 2.0, 2)
            acoustic_sections[longest_idx: longest_idx + 1] = [(ls, mid_t), (mid_t, le)]

    if not acoustic_sections:
        acoustic_sections = [(min_start, total_audio_sec)]

    log.info("提取细粒度声学发音块: %d 个 (覆盖 %.2fs ~ %.2fs, 段落数=%d)",
             len(acoustic_sections), acoustic_sections[0][0], acoustic_sections[-1][1], K)

    # 6.4 单调最优分段全局动态规划 (Monotonic Global DP)
    M = len(acoustic_sections)
    INF = 1e9

    dp = np.full((K + 1, M + 1), INF)
    parent = np.full((K + 1, M + 1), -1, dtype=int)
    dp[0][0] = 0.0

    for k in range(1, K + 1):
        target = stanza_target_durs[k - 1]
        for m in range(1, M + 1):
            for prev_m in range(0, m):
                if dp[k - 1][prev_m] >= INF:
                    continue
                s_t = acoustic_sections[prev_m][0]
                e_t = acoustic_sections[m - 1][1]
                dur = e_t - s_t

                # 约束 A: 段内不可跨越 >= 3.0s 的纯伴奏/长间奏
                has_interlude = False
                for bi in range(prev_m, m - 1):
                    if acoustic_sections[bi + 1][0] - acoustic_sections[bi][1] >= 3.0:
                        has_interlude = True
                        break
                if has_interlude:
                    continue

                # 约束 B: 语速生理下限 (不可严重挤压)
                if dur < target * 0.40:
                    continue

                # 代价函数: 语速偏差二次方惩罚
                cost = ((dur - target) ** 2) / target

                # 尾段覆盖约束: 最后一个段落如果距离末尾未分配的人声块太多，加惩罚
                if k == K:
                    unassigned_blocks = M - m
                    if unassigned_blocks > 1:
                        cost += unassigned_blocks * 6.0

                total_cost = dp[k - 1][prev_m] + cost
                if total_cost < dp[k][m]:
                    dp[k][m] = total_cost
                    parent[k][m] = prev_m

    best_end_m = -1
    best_total_cost = INF
    # 终点优先落在歌曲后部发音块 (倒数 3 个块内)
    min_search_m = max(1, M - 2)
    for m in range(min_search_m, M + 1):
        if dp[K][m] < best_total_cost:
            best_total_cost = dp[K][m]
            best_end_m = m

    # 兜底：若倒数 3 个块没有合法闭合路径，扩大搜索到全部 m
    if best_end_m == -1 or best_total_cost >= INF:
        for m in range(1, M + 1):
            if dp[K][m] < best_total_cost:
                best_total_cost = dp[K][m]
                best_end_m = m

    stanza_spans: list[tuple[float, float]] = []
    if best_end_m > 0 and best_total_cost < INF:
        cur_m = best_end_m
        path_segments = []
        for k in range(K, 0, -1):
            prev_m = parent[k][cur_m]
            path_segments.append((k - 1, acoustic_sections[prev_m][0], acoustic_sections[cur_m - 1][1]))
            cur_m = prev_m
        path_segments.reverse()
        stanza_spans = [(p[1], p[2]) for p in path_segments]
        log.info("全局动态规划求解成功 (最优代价: %.2f)", best_total_cost)
    else:
        log.warning("声学块动态规划未闭合，采用基于生理语速的前向比例自适应映射")
        tot_target = sum(stanza_target_durs)
        cur_t = min_start
        for k in range(K):
            s_dur = stanza_target_durs[k] * (total_audio_sec - min_start) / max(1.0, tot_target)
            stanza_spans.append((round(cur_t, 2), round(min(total_audio_sec, cur_t + s_dur), 2)))
            cur_t += s_dur

    # 6.5 上下文前后文夹逼检验与复核 (Context Sandwich Validation)
    for k in range(K):
        if is_repeated_stanza[k]:
            prev_anchor_t = min_start
            for j in range(k - 1, -1, -1):
                if not is_repeated_stanza[j]:
                    prev_anchor_t = stanza_spans[j][1]
                    break
            next_anchor_t = total_audio_sec
            for j in range(k + 1, K):
                if not is_repeated_stanza[j]:
                    next_anchor_t = stanza_spans[j][0]
                    break

            cur_s, cur_e = stanza_spans[k]
            if cur_s < prev_anchor_t or cur_e > next_anchor_t:
                log.warning("🛡️ [上下文夹逼触发] 第 %d 段 (重复段落) 越界，已强制锁死在合法上下文内 [%.2fs ~ %.2fs]",
                            k + 1, prev_anchor_t, next_anchor_t)
                clamped_s = max(cur_s, prev_anchor_t + 0.2)
                clamped_e = min(cur_e, next_anchor_t - 0.2)
                if clamped_e > clamped_s:
                    stanza_spans[k] = (clamped_s, clamped_e)

    # 6.6 声学遗漏审计 (Acoustic Voicing Gap Audit)
    for k in range(len(stanza_spans) - 1):
        gap_s = stanza_spans[k][1]
        gap_e = stanza_spans[k + 1][0]
        if gap_e - gap_s >= 3.5:
            g_start_idx = int(gap_s / 0.1)
            g_end_idx = int(gap_e / 0.1)
            g_rms = rms_vals[g_start_idx:g_end_idx] if g_end_idx > g_start_idx else []
            vocal_ratio = (sum(r > 0.02 for r in g_rms) / len(g_rms)) if g_rms else 0.0
            if vocal_ratio > 0.40:
                log.warning("⚠️ [声学遗漏审计] 发现区间 %.2fs ~ %.2fs 存在密集人声发音 (占比 %.0f%%)，但歌词中缺少对应内容！",
                            gap_s, gap_e, vocal_ratio * 100)

    last_stanza_end = stanza_spans[-1][1] if stanza_spans else 0.0
    if total_audio_sec - last_stanza_end >= 5.0:
        tail_start_idx = int(last_stanza_end / 0.1)
        tail_rms = rms_vals[tail_start_idx:]
        tail_vocal_ratio = (sum(r > 0.02 for r in tail_rms) / len(tail_rms)) if tail_rms else 0.0
        if tail_vocal_ratio > 0.45:
            log.warning("⚠️ [声学遗漏审计] 歌曲尾部 %.2fs ~ %.2fs (时长=%.1fs) 存在密集演唱，原歌词可能缺少重复副歌段落！",
                        last_stanza_end, total_audio_sec, total_audio_sec - last_stanza_end)

    # 6.7 逐段执行 CTC 精确打点 (Intra-Stanza CTC Fine Alignment)
    for k, st in enumerate(stanzas):
        span_s, span_e = stanza_spans[k]
        lines_with_idx = st
        langs_in_st = [detect_line_lang(ly.text) for _, ly in lines_with_idx]

        if all(l == "en" for l in langs_in_st):
            _align_en(lines_with_idx, span_s, span_e)
        elif all(l == "zh" for l in langs_in_st):
            _align_zh(lines_with_idx, span_s, span_e)
        else:
            sub_runs = []
            cur_r = []
            cur_rlang = None
            for idx_ly in lines_with_idx:
                l_lang = detect_line_lang(idx_ly[1].text)
                if cur_rlang is None or l_lang == cur_rlang:
                    cur_r.append(idx_ly)
                    cur_rlang = l_lang
                else:
                    sub_runs.append((cur_rlang, cur_r))
                    cur_r = [idx_ly]
                    cur_rlang = l_lang
            if cur_r:
                sub_runs.append((cur_rlang, cur_r))

            tot_st_lines = len(lines_with_idx)
            sub_dur = (span_e - span_s)
            c_s = span_s
            for sr_idx, (sr_lang, sr_lines) in enumerate(sub_runs):
                ratio = len(sr_lines) / tot_st_lines
                ideal_e = c_s + sub_dur * ratio
                if sr_idx < len(sub_runs) - 1:
                    idx_mid = int(ideal_e / 0.1)
                    w = int(1.2 / 0.1)
                    search_range = range(max(0, idx_mid - w), min(len(rms_vals), idx_mid + w))
                    if search_range:
                        best_k = min(search_range, key=lambda ki: rms_vals[ki])
                        c_e = round(times[best_k], 2)
                    else:
                        c_e = min(span_e, ideal_e)
                else:
                    c_e = span_e
                _dispatch_align(sr_lang, sr_lines, c_s, c_e)
                c_s = c_e

    aligned_lines = []
    for li, ly in enumerate(lyrics):
        if ly.is_annotation:
            aligned_lines.append(AlignedLine(
                text=ly.text,
                start=0.0,
                end=0.0,
                words=[WordTimestamp(word=ly.text, start=0.0, end=0.0)]
            ))
        elif li in aligned_line_map:
            aligned_lines.append(aligned_line_map[li])

    if len(aligned_line_map) != len(singing_lyrics):
        raise ValueError("声学对齐未覆盖全部演唱歌词，请检查字词与音频区间")

    # 回填编曲说明行的时间
    _fill_annotation_times(aligned_lines)

    # 审计时间戳单调性
    aligned_lines = _audit_alignment(aligned_lines)

    # 自动异常检测与局部自愈 (Self-Healing Anomaly Detector)
    if allow_self_heal and len(aligned_lines) >= 2:
        aligned_lines = _self_heal_alignment(
            vocals_path=vocals_path,
            aligned_lines=aligned_lines,
            singing_sections=singing_sections,
            total_audio_sec=total_audio_sec,
            config=config,
        )
        aligned_lines = _audit_alignment(aligned_lines)

    issue = alignment_quality_issue(aligned_lines)
    if issue:
        raise ValueError("声学对齐失败，未将异常时间轴视为成功结果：" + issue)
    result = AlignmentResult(lines=aligned_lines)
    log.info("【方案二: CTC Forced Alignment】对齐完成: %d 行, %d 个词",
             len(result.lines), sum(len(line.words) for line in result.lines))
    return result


# ---------------------------------------------------------------------------
# 无歌词场景: Whisper 纯文本听写 (ASR)
# ---------------------------------------------------------------------------

def transcribe_audio_with_anchors(
    vocals_path: Path,
    config: AlignerConfig | None = None,
) -> tuple[list[WhisperSegmentAnchor], str]:
    """
    使用 Whisper 提取带分段和词级时间戳的音频转写锚点 (ASR Anchors)。
    """
    if config is None:
        config = AlignerConfig()

    model = _get_whisper(config)
    lang = config.language if config.language and config.language != "auto" else None
    segments, info = model.transcribe(str(vocals_path), language=lang, beam_size=5, word_timestamps=True)

    detected_lang = info.language or "zh"
    anchors: list[WhisperSegmentAnchor] = []
    for idx, s in enumerate(segments):
        words = [
            WhisperWordAnchor(
                word=w.word.strip(),
                start=round(w.start, 3),
                end=round(w.end, 3),
                probability=getattr(w, "probability", 1.0),
            )
            for w in (s.words or [])
            if w.word.strip()
        ]
        anchors.append(WhisperSegmentAnchor(
            id=idx,
            text=s.text.strip(),
            start=round(s.start, 3),
            end=round(s.end, 3),
            language=detected_lang,
            words=words,
        ))

    log.info("Whisper 转写完成: %d 个时间锚点片段 (检测语言: %s)", len(anchors), detected_lang)
    return anchors, detected_lang


def transcribe_audio(
    vocals_path: Path,
    config: AlignerConfig | None = None,
) -> tuple[list[LyricLine], str]:
    """
    无歌词场景: 使用轻量 faster-whisper 仅转写音频文本 (ASR)，返回 (歌词行列表, 检测到的语言代码)。
    后续统一交给 align_lyrics (CTC Forced Alignment) 进行声学高精度时间戳打点。
    """
    anchors, detected_lang = transcribe_audio_with_anchors(vocals_path, config)
    lines = [LyricLine(text=a.text) for a in anchors if a.text.strip()]
    return lines, detected_lang


# ---------------------------------------------------------------------------
# 局部重对齐 (供时间轴编辑器拖拽/修正使用)
# ---------------------------------------------------------------------------

def realign_lines(
    vocals_path: Path,
    texts: list[str],
    rough_start: float,
    rough_end: float,
    config: AlignerConfig | None = None,
    buffer: float = 2.0,
) -> list[AlignedLine]:
    """
    对指定时间段内的几行歌词进行局部重对齐 (底层复用 CTC 声学对齐)。
    """
    import tempfile

    if config is None:
        config = AlignerConfig()

    clip_start = max(0.0, rough_start - buffer)
    clip_end = rough_end + buffer

    log.info("局部重对齐: %.2fs ~ %.2fs (片段 %.2fs ~ %.2fs, buffer=%.1fs)",
             rough_start, rough_end, clip_start, clip_end, buffer)

    audio_data, sample_rate = sf.read(str(vocals_path), dtype="float32", always_2d=False)
    start_sample = int(clip_start * sample_rate)
    end_sample = int(clip_end * sample_rate)
    end_sample = min(end_sample, len(audio_data))
    clip = audio_data[start_sample:end_sample]

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    sf.write(str(tmp_path), clip, sample_rate)

    local_cfg = AlignerConfig()
    if config is not None:
        for k, v in getattr(config, "__dict__", {}).items():
            if k != "lyrics_start_time":
                setattr(local_cfg, k, v)
    local_cfg.lyrics_start_time = 0.0

    try:
        lyrics = [LyricLine(text=t) for t in texts]
        local_result = align_lyrics(tmp_path, lyrics, local_cfg, allow_self_heal=False)
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass

    shifted: list[AlignedLine] = []
    for line in local_result.lines:
        new_words = [
            WordTimestamp(
                word=w.word,
                start=round(w.start + clip_start, 3),
                end=round(w.end + clip_start, 3),
            )
            for w in line.words
        ]
        shifted.append(AlignedLine(
            text=line.text,
            start=round(line.start + clip_start, 3),
            end=round(line.end + clip_start, 3),
            words=new_words,
        ))

    log.info("局部重对齐完成: %d 行", len(shifted))
    return shifted


# ---------------------------------------------------------------------------
# 异常检测与局部自愈 (Self-Healing Anomaly Detector)
# ---------------------------------------------------------------------------

def _self_heal_alignment(
    vocals_path: Path,
    aligned_lines: list[AlignedLine],
    singing_sections: list[tuple[float, float]],
    total_audio_sec: float,
    config: AlignerConfig | None = None,
) -> list[AlignedLine]:
    """
    自动检测 CTC 对齐结果中的异常压缩/提前坍缩 (Premature Collapse / Over-compression)，
    并针对受影响乐段区间自动触发局部声学重对齐自愈。
    """
    indexed_lines = [(i, l) for i, l in enumerate(aligned_lines) if not getattr(l, "is_annotation", False)]
    if len(indexed_lines) < 2:
        return aligned_lines

    # 1. 扫描异常压缩行
    anomalous_k_indices: list[int] = []
    last_vocal_end = singing_sections[-1][1] if singing_sections else total_audio_sec
    last_line_end = indexed_lines[-1][1].end
    tail_lag = last_vocal_end - last_line_end

    for k, (orig_i, line) in enumerate(indexed_lines):
        # 英文与欧系多语言词整体为一个发音单元；中日韩字符按单字计数
        char_count = len(re.findall(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]|[a-zA-Z0-9\u00C0-\u024F]+(?:['’\-][a-zA-Z0-9\u00C0-\u024F]+)*", line.text))
        dur = max(0.0, line.end - line.start)
        rate = dur / max(1, char_count)

        is_anom = False
        # 条件 1: 4字以上，整句时长 < 0.6s 或平均字均时长 < 0.085s (物理不可能的人声歌唱极限)
        if char_count >= 4 and (dur < 0.6 or rate < 0.085):
            is_anom = True
        # 条件 2: 6字以上，整句时长 < 0.85s 或平均字均时长 < 0.10s
        elif char_count >= 6 and (dur < 0.85 or rate < 0.10):
            is_anom = True
        # 条件 3: 尾部坍缩特异性检测 (末尾3句内，且全曲人声能量显著延伸超过歌词结束3.5s以上)
        elif k >= len(indexed_lines) - 3 and tail_lag > 3.5 and (dur < 1.2 or rate < 0.12):
            is_anom = True

        if is_anom:
            anomalous_k_indices.append(k)

    if not anomalous_k_indices:
        return aligned_lines

    # 2. 将相邻的异常索引聚类为修复段 (Group contiguous anomalies)
    clusters: list[list[int]] = []
    for ak in anomalous_k_indices:
        if not clusters or ak > clusters[-1][-1] + 1:
            clusters.append([ak])
        else:
            clusters[-1].append(ak)

    # 3. 对每个异常乐段执行局部自愈
    for cluster in clusters:
        k_first = cluster[0]
        k_last = cluster[-1]

        # 向前纳入 1 行正常句作为锚点 (恢复可能被挤压的尾字，如"幻梦")
        k_anchor_start = max(0, k_first - 1)
        target_items = indexed_lines[k_anchor_start : k_last + 1]
        texts = [item[1].text for item in target_items]

        rough_start = max(0.0, target_items[0][1].start - 1.0)
        is_tail = (k_last >= len(indexed_lines) - 2)
        if is_tail:
            rough_end = min(total_audio_sec, max(last_vocal_end + 1.5, target_items[-1][1].end + 5.0))
        else:
            k_next = min(len(indexed_lines) - 1, k_last + 1)
            rough_end = min(total_audio_sec, indexed_lines[k_next][1].start + 1.0)

        if rough_end <= rough_start + 1.0:
            continue

        try:
            old_dur = sum(item[1].end - item[1].start for item in target_items)
            log.info(
                "🛡️ [声学自愈监测] 发现第 %d~%d 行歌词异常压缩 (时长=%.2fs)，启动局部自愈重对齐 (区间: %.2fs ~ %.2fs)...",
                target_items[0][0] + 1,
                target_items[-1][0] + 1,
                old_dur,
                rough_start,
                rough_end,
            )
            repaired = realign_lines(
                vocals_path,
                texts,
                rough_start=rough_start,
                rough_end=rough_end,
                config=config,
                buffer=0.5,
            )
            if len(repaired) == len(target_items):
                new_dur = sum(r.end - r.start for r in repaired)
                old_end = target_items[-1][1].end
                new_end = repaired[-1].end

                # 自愈有效性仲裁: 新时长显著伸展，结尾延展到真实人声结束点，或被压缩异常行显著舒展恢复
                anom_improved = any(
                    (repaired[it_idx].end - repaired[it_idx].start) > max(0.8, (target_items[it_idx][1].end - target_items[it_idx][1].start) * 1.5)
                    for it_idx in range(len(target_items))
                    if (target_items[it_idx][1].end - target_items[it_idx][1].start) < 0.6
                )
                if not alignment_quality_issue(repaired) and (new_dur > old_dur * 1.2 or new_end > old_end + 2.0 or anom_improved):
                    for item_idx, r_line in enumerate(repaired):
                        orig_idx = target_items[item_idx][0]
                        orig_line = target_items[item_idx][1]
                        aligned_lines[orig_idx] = AlignedLine(
                            text=r_line.text,
                            start=r_line.start,
                            end=r_line.end,
                            words=r_line.words,
                            style_overrides=getattr(orig_line, "style_overrides", {}),
                            section=getattr(orig_line, "section", ""),
                        )
                    log.info(
                        "✨ [局部自愈成功] 第 %d~%d 行时间轴已精准自愈: 总时长 %.2fs -> %.2fs, 结尾 %.2fs -> %.2fs",
                        target_items[0][0] + 1,
                        target_items[-1][0] + 1,
                        old_dur,
                        new_dur,
                        old_end,
                        new_end,
                    )
        except Exception as e:
            log.warning("局部自愈执行异常 (已自动保留原对齐): %s", e)

    return aligned_lines
