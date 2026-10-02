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
                w_s = s_sec + w_spans[0].start * frame_dur
                w_e = s_sec + w_spans[-1].end * frame_dur
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

    # 6. 乐段与语言块智能映射
    if len(lang_runs) == 1:
        lang, r_lines = lang_runs[0]
        sec_s = min_start
        sec_e = max(singing_sections[-1][1] if singing_sections else total_audio_sec, total_audio_sec - 1.0)
        log.info("单语言全曲对齐: 纵跨所有乐段 (%.2fs - %.2fs), 共 %d 行", sec_s, sec_e, len(r_lines))
        if lang == "en":
            _align_en(r_lines, sec_s, sec_e)
        else:
            _align_zh(r_lines, sec_s, sec_e)
    elif len(lang_runs) == len(singing_sections):
        for ri, (lang, r_lines) in enumerate(lang_runs):
            sec_s, sec_e = singing_sections[ri]
            if ri == len(lang_runs) - 1:
                sec_e = max(sec_e, total_audio_sec - 1.0)
            if lang == "en":
                _align_en(r_lines, sec_s, sec_e)
            else:
                _align_zh(r_lines, sec_s, sec_e)
    else:
        cur_sec_idx = 0
        ri = 0
        while ri < len(lang_runs) and cur_sec_idx < len(singing_sections):
            sec_s, sec_e = singing_sections[cur_sec_idx]
            if ri == len(lang_runs) - 1:
                sec_e = max(sec_e, singing_sections[-1][1], total_audio_sec - 1.0)
            sec_dur = sec_e - sec_s
            lang, r_lines = lang_runs[ri]

            # 容量检查：若当前乐段时长严重不足以容纳当前语言块（如开场杂音仅1-2s，而歌词有十多行），
            # 且后续乐段具有充足容量，则跳过此虚假乐段
            min_needed_dur = max(2.0, len(r_lines) * 1.0)
            if (sec_dur < min_needed_dur and cur_sec_idx + 1 < len(singing_sections)
                    and (singing_sections[cur_sec_idx + 1][1] - singing_sections[cur_sec_idx + 1][0]) >= min_needed_dur):
                log.info("乐段 %d (%.2fs - %.2fs, 时长=%.2fs) 不足容纳 %d 行歌词，跳过并移至下一乐段",
                         cur_sec_idx, sec_s, sec_e, sec_dur, len(r_lines))
                cur_sec_idx += 1
                continue

            should_pair = False
            if ri + 1 < len(lang_runs) and lang_runs[ri + 1][0] != lang:
                r_lines2 = lang_runs[ri + 1][1]
                n1, n2 = len(r_lines), len(r_lines2)
                if n1 <= 6 and n2 <= 6:
                    rate_single = sec_dur / n1
                    rate_both = sec_dur / (n1 + n2)
                    if rate_single > 4.0 and 1.5 <= rate_both <= 6.0:
                        should_pair = True
                    elif (len(lang_runs) - ri) > (len(singing_sections) - cur_sec_idx) and rate_both >= 1.2:
                        should_pair = True

            if should_pair:
                r_lines2 = lang_runs[ri + 1][1]
                sub_hop = int(sr * 0.05)
                s_sample, e_sample = int(sec_s * sr), int(sec_e * sr)
                sub_wav = wav[s_sample:e_sample]
                sub_rms = [float(np.sqrt(np.mean(sub_wav[i:i + sub_hop] ** 2))) for i in range(0, len(sub_wav) - sub_hop, sub_hop)]

                base_ratio = len(r_lines) / (len(r_lines) + len(r_lines2))
                ratio = base_ratio * (0.93 if lang == "en" else 1.07)
                center_idx = int(len(sub_rms) * ratio)
                search_w = int(1.5 / 0.05)
                best_score = float("inf")
                best_idx = center_idx
                for k in range(max(0, center_idx - search_w), min(len(sub_rms), center_idx + search_w)):
                    dist_sec = abs(k - center_idx) * 0.05
                    score = sub_rms[k] + 0.05 * dist_sec
                    if score < best_score:
                        best_score = score
                        best_idx = k
                mid_t = sec_s + (best_idx * sub_hop) / sr

                log.info(
                    "乐段 %d (%.2fs - %.2fs) 智能双语切分点: %.2fs (前段 %s: %d行, 后段 %s: %d行)",
                    cur_sec_idx, sec_s, sec_e, mid_t, lang, len(r_lines), lang_runs[ri + 1][0], len(r_lines2)
                )

                if lang == "en":
                    _align_en(r_lines, sec_s, mid_t)
                else:
                    _align_zh(r_lines, sec_s, mid_t)
                ri += 1

                lang2, _ = lang_runs[ri]
                if lang2 == "en":
                    _align_en(r_lines2, mid_t, sec_e)
                else:
                    _align_zh(r_lines2, mid_t, sec_e)
                ri += 1
                cur_sec_idx += 1
            else:
                log.info("乐段 %d (%.2fs - %.2fs) 单语言对齐: %s (%d 行)", cur_sec_idx, sec_s, sec_e, lang, len(r_lines))
                if lang == "en":
                    _align_en(r_lines, sec_s, sec_e)
                else:
                    _align_zh(r_lines, sec_s, sec_e)
                ri += 1
                cur_sec_idx += 1

        while ri < len(lang_runs):
            lang, r_lines = lang_runs[ri]
            last_end = singing_sections[-1][1] if singing_sections else min_start
            rem_s = max(min_start, last_end)
            rem_e = total_audio_sec
            log.warning("乐段用尽兜底对齐: 语言块 %d (%s, %d 行) 分配至尾部 %.2fs ~ %.2fs", ri, lang, len(r_lines), rem_s, rem_e)
            if lang == "en":
                _align_en(r_lines, rem_s, rem_e)
            else:
                _align_zh(r_lines, rem_s, rem_e)
            ri += 1

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
        clean_chars = [c for c in line.text if not c.isspace() and c not in '.,!?:;...~—"\'()[]（）【】']
        char_count = len(clean_chars)
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
