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

import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch
import torchaudio
from torchaudio.functional import forced_align, merge_tokens
from transformers import AutoModelForCTC, AutoProcessor

from src.config import AlignerConfig
from src.preprocessor import LyricLine
from src.utils import log

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


def _requires_ordered_bilingual(lang_runs, dominant):
    """Short foreign shouts can use anchors; longer foreign passages cannot."""
    minority = [ly for lang, items in lang_runs if lang != dominant for _, ly in items]
    units = sum(len(re.findall(r"[\u4e00-\u9fff]|[a-zA-Z]+(?:['’\-][a-zA-Z]+)*", ly.text)) for ly in minority)
    return bool(minority) and (len(minority) >= 4 or units >= 12)


def _ordered_run_windows(bounds, start, end):
    """Partition acoustic anchors into ordered, non-overlapping search windows."""
    if not bounds or any(b <= a or a < start or b > end for a, b in bounds):
        raise ValueError("双语声学定位产生无效段落范围")
    if any(bounds[i][1] > bounds[i+1][0] for i in range(len(bounds)-1)):
        raise ValueError("双语声学定位段落顺序冲突")
    cuts = [start, *((bounds[i][1]+bounds[i+1][0])/2 for i in range(len(bounds)-1)), end]
    return list(zip(cuts, cuts[1:]))


def _trim_word_over_silence(start, end, singing_sections):
    """A word must not absorb a long silent intro before its acoustic match."""
    if end-start > 4:
        for before, after in zip(singing_sections, singing_sections[1:]):
            if start < before[1] and end > after[0] and after[0]-before[1] >= 3.5 and end-after[0] <= 4:
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
    def _detect_line_lang(text: str) -> str:
        zh = len(_CHINESE_CHAR_RE.findall(text))
        en = len(re.findall(r"[a-zA-Z]", text))
        return "zh" if zh >= en else "en"

    singing_lyrics: list[tuple[int, LyricLine]] = [(idx, ly) for idx, ly in enumerate(lyrics) if not ly.is_annotation]

    lang_runs: list[tuple[str, list[tuple[int, LyricLine]]]] = []
    cur_run: list[tuple[int, LyricLine]] = []
    cur_lang = None
    for item in singing_lyrics:
        idx, ly = item
        lang = _detect_line_lang(ly.text)
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
        proc_zh = AutoProcessor.from_pretrained(model_zh_name)
        model_zh = AutoModelForCTC.from_pretrained(model_zh_name)
        model_zh.eval()
        blank_zh = proc_zh.tokenizer.pad_token_id or 0

    aligned_line_map: dict[int, AlignedLine] = {}

    def _align_en(lines_with_idx: list[tuple[int, LyricLine]], s_sec: float, e_sec: float):
        s_sec = max(0.0, s_sec - (0.0 if ordered_bilingual else 0.2))
        e_sec = min(total_audio_sec, e_sec + (0.0 if ordered_bilingual else 0.3))
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
        s_sec = max(0.0, s_sec - (0.0 if ordered_bilingual else 0.2))
        e_sec = min(total_audio_sec, e_sec + (0.0 if ordered_bilingual else 0.3))
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
                w_s = s_sec + w_spans[0].start * frame_dur
                w_e = s_sec + w_spans[-1].end * frame_dur
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

    # Short foreign shouts may use dominant-language anchors. Substantial bilingual
    # sections require an ordered acoustic pass containing BOTH languages first.
    dominant = max(("zh", "en"), key=lambda lang: sum(len(re.sub(r"\W", "", ly.text))
                    for block_lang, items in lang_runs if block_lang == lang for _, ly in items))
    ordered_bilingual = has_en and has_zh and _requires_ordered_bilingual(lang_runs, dominant)
    if ordered_bilingual:
        log.info("双语顺序定位：联合两种语言的声学证据，保持全部歌词段落顺序")
        # Project each acoustic model onto only the symbols present in this song.
        # No full Chinese vocabulary is retained across the entire audio.
        symbols: list[tuple[str, str]] = []
        run_targets: list[list[int]] = []
        for lang, items in lang_runs:
            text = "|".join("|".join(ly.text.upper().split()) for _, ly in items) if lang == "en" else "".join(
                c for _, ly in items for c in ly.text if _CHINESE_CHAR_RE.match(c))
            ids = []
            for char in text:
                if lang == "en" and char not in dict_en:
                    continue
                if lang == "zh" and proc_zh.tokenizer.convert_tokens_to_ids(char) in (blank_zh, proc_zh.tokenizer.unk_token_id):
                    # Missing dictionary glyphs cannot anchor a section. They remain
                    # in the original lyrics for the subsequent fine alignment.
                    continue
                symbol = (lang, char)
                if symbol not in symbols:
                    symbols.append(symbol)
                ids.append(symbols.index(symbol) + 1)
            if not ids:
                raise ValueError("双语段落缺少可对齐的发音字符")
            run_targets.append(ids)
        en_ids = [dict_en[char] for lang, char in symbols if lang == "en"]
        zh_ids = proc_zh.tokenizer.convert_tokens_to_ids([char for lang, char in symbols if lang == "zh"])
        if any(idx in (blank_zh, proc_zh.tokenizer.unk_token_id) for idx in zh_ids):
            raise ValueError("中文声学模型缺少歌词字形，不能可靠定位双语段落")
        en_cols = [i+1 for i, (lang, _) in enumerate(symbols) if lang == "en"]
        zh_cols = [i+1 for i, (lang, _) in enumerate(symbols) if lang == "zh"]
        coarse_start = min_start
        sliced = wav_16k[:, int(coarse_start*16000):]
        projected = []
        with torch.inference_mode():
            for chunk in sliced.split(20*16000, dim=1):
                if chunk.size(1) < 400:
                    continue
                en = model_en(chunk)[0].log_softmax(dim=-1)
                zh = model_zh(chunk).logits.log_softmax(dim=-1)
                if zh.size(1) != en.size(1):
                    zh = torch.nn.functional.interpolate(zh.transpose(1, 2), size=en.size(1), mode="linear", align_corners=False).transpose(1, 2)
                joint = en.new_full((1, en.size(1), len(symbols)+1), -100.0)
                joint[:, :, 0] = torch.maximum(en[:, :, 0], zh[:, :, blank_zh])
                joint[:, :, en_cols] = en[:, :, en_ids]
                joint[:, :, zh_cols] = zh[:, :, zh_ids]
                projected.append(joint.log_softmax(dim=-1))
        emissions = torch.cat(projected, dim=1)
        targets = torch.tensor([sum(run_targets, [])], dtype=torch.int32)
        path, scores = forced_align(emissions, targets, blank=0)
        spans = merge_tokens(path[0], scores[0], blank=0)
        if len(spans) != targets.size(1):
            raise ValueError("双语声学定位未覆盖全部歌词字符")
        frame_duration = (sliced.size(1)/16000.0)/emissions.size(1)
        run_bounds = []
        offset = 0
        for ids in run_targets:
            selected = spans[offset:offset+len(ids)]
            offset += len(ids)
            run_bounds.append((coarse_start+selected[0].start*frame_duration,
                               coarse_start+selected[-1].end*frame_duration))
        del emissions, projected
        windows = _ordered_run_windows(run_bounds, min_start, total_audio_sec)
        for i, ((lang, items), (sec_s, sec_e)) in enumerate(zip(lang_runs, windows)):
            log.info("顺序语言段 %d：%s %d 行，声学区间 %.2fs ~ %.2fs", i+1, lang, len(items), sec_s, sec_e)
            (_align_en if lang == "en" else _align_zh)(items, sec_s, sec_e)
    else:
        # Language switches are lyric boundaries, not RMS-section boundaries.
        # Align the dominant language across the song, then locate short switches
        # inside the gaps between its neighboring lyric anchors.
        dominant = max(("zh", "en"), key=lambda lang: sum(len(re.sub(r"\W", "", ly.text))
                        for block_lang, items in lang_runs if block_lang == lang for _, ly in items))
        dominant_lines = [item for lang, items in lang_runs if lang == dominant for item in items]
        align_dominant = _align_zh if dominant == "zh" else _align_en
        align_dominant(dominant_lines, min_start, total_audio_sec)
        for lang, items in lang_runs:
            if lang == dominant:
                continue
            first, last = items[0][0], items[-1][0]
            before = [idx for idx, _ in dominant_lines if idx < first]
            after = [idx for idx, _ in dominant_lines if idx > last]
            sec_s = aligned_line_map[before[-1]].end if before else min_start
            sec_e = aligned_line_map[after[0]].start if after else total_audio_sec
            # CTC can let neighboring dominant-language tokens touch across a short
            # foreign-language shout. Allow bounded context, never whole sections.
            if sec_e < sec_s - 0.5:
                raise ValueError("跨语言歌词定位失败：相邻歌词没有有效声学区间，请检查歌词顺序或手动定位")
            interior = [(start, end) for start, end in singing_sections
                        if start >= sec_s and end <= sec_e]
            if len(interior) == 1:
                # A unique isolated vocal block inside lyric anchors is stronger
                # evidence than letting a short English shout span an interlude.
                sec_s, sec_e = interior[0]
            else:
                sec_s = max(min_start, sec_s - 1.0)
                sec_e = min(total_audio_sec, sec_e + 1.0)
            log.info("跨语言锚点定位: %s %d 行，区间 %.2fs ~ %.2fs", lang, len(items), sec_s, sec_e)
            (_align_en if lang == "en" else _align_zh)(items, sec_s, sec_e)


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

def transcribe_audio(
    vocals_path: Path,
    config: AlignerConfig | None = None,
) -> tuple[list[LyricLine], str]:
    """
    无歌词场景: 使用轻量 faster-whisper 仅转写音频文本 (ASR)，返回 (歌词行列表, 检测到的语言代码)。
    后续统一交给 align_lyrics (CTC Forced Alignment) 进行声学高精度时间戳打点。
    """
    from faster_whisper import WhisperModel

    if config is None:
        config = AlignerConfig()

    device = config.device
    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"
    compute_type = "int8" if device == "cpu" else "float16"

    model_size = config.whisper_model or "base"
    log.info("【无歌词 ASR 文本听写】加载 Whisper: %s (device=%s, compute=%s)", model_size, device, compute_type)
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    lang = config.language if config.language and config.language != "auto" else None
    segments, info = model.transcribe(str(vocals_path), language=lang, beam_size=5)

    detected_lang = info.language or "zh"
    lines: list[LyricLine] = []
    for s in segments:
        text = s.text.strip()
        if text:
            lines.append(LyricLine(text=text))

    log.info("Whisper 文本听写完成: %d 行有效歌词 (检测语言: %s)", len(lines), detected_lang)
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
        # English letters are not separate sung words; counting them falsely
        # marks healthy English phrases as collapsed and repeatedly reloads models.
        char_count = len(re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+(?:['’\-][a-zA-Z0-9]+)*", line.text))
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

                # 自愈有效性仲裁: 新时长显著伸展，或者结尾延展到真实人声结束点
                if not alignment_quality_issue(repaired) and (new_dur > old_dur * 1.2 or new_end > old_end + 2.0):
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
