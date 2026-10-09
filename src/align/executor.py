"""
Alignment Task Execution Engine.
Executes individual AlignmentTask units using Wav2Vec2 CTC or Whisper without shared mutable state.
"""

from __future__ import annotations

import difflib
import logging
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import soundfile as sf
import torch
from torchaudio.functional import forced_align, merge_tokens

from src.align.evidence import _CHINESE_CHAR_RE, _fallback_even_split, tokenize_lyric_line
from src.align.quality import _trim_word_over_silence
from src.align.task import AlignmentTask
from src.storyboard_schema import AlignedLine, SyllableTimestamp, WordTimestamp

if TYPE_CHECKING:
    from src.config import AlignerConfig

log = logging.getLogger("m2v")


def execute_task(
    task: AlignmentTask,
    wav_16k: torch.Tensor,
    models: dict[str, Any],
    singing_sections: list[tuple[float, float]],
    total_audio_sec: float,
    config: AlignerConfig | None = None,
) -> dict[int, AlignedLine]:
    """执行单个对齐任务单元，返回行级对齐映射 {orig_idx: AlignedLine}。"""
    lines_with_idx = task.lyrics
    s_sec = task.window_start
    e_sec = task.window_end
    lang = task.language

    if lang == "zh":
        return _execute_zh_task(task, wav_16k, models, singing_sections, total_audio_sec)
    elif lang == "en":
        return _execute_en_task(task, wav_16k, models, singing_sections, total_audio_sec)
    else:
        return _execute_other_task(task, wav_16k, models, singing_sections, total_audio_sec, config)


def _execute_en_task(
    task: AlignmentTask,
    wav_16k: torch.Tensor,
    models: dict[str, Any],
    singing_sections: list[tuple[float, float]],
    total_audio_sec: float,
) -> dict[int, AlignedLine]:
    lines_with_idx = task.lyrics
    s_sec = max(0.0, task.window_start - 0.2)
    e_sec = min(total_audio_sec, task.window_end + 0.3)
    wav_slice = wav_16k[:, int(s_sec * 16000): int(e_sec * 16000)]

    res: dict[int, AlignedLine] = {}

    if wav_slice.size(1) < 400:
        for orig_idx, ly in lines_with_idx:
            words = _fallback_even_split(ly.text, s_sec, e_sec)
            res[orig_idx] = AlignedLine(text=ly.text, start=s_sec, end=e_sec, words=words)
        return res

    model_en = models["model_en"]
    dict_en = models["dict_en"]

    with torch.inference_mode():
        emissions = torch.cat([model_en(chunk)[0].log_softmax(dim=-1)
                               for chunk in wav_slice.split(20 * 16000, dim=1)
                               if chunk.size(1) >= 400], dim=1)

    full_target_ids: list[int] = []
    full_tokens_with_spans = []
    curr_span_pos = 0

    for li, (orig_idx, ly) in enumerate(lines_with_idx):
        tokens = tokenize_lyric_line(ly.text)
        tok_records: list[tuple[str, list[str]]] = []
        for tok in tokens:
            chars = [c.upper() for c in tok if c.upper() in dict_en and dict_en[c.upper()] != 0 and c != "|"]
            tok_records.append((tok, chars))

        line_tok_spans: list[tuple[str, int, int]] = []
        vocal_count = sum(1 for _, chars in tok_records if chars)
        vocal_idx = 0
        for tok, chars in tok_records:
            if not chars:
                line_tok_spans.append((tok, curr_span_pos, curr_span_pos))
                continue
            s_pos = curr_span_pos
            for c in chars:
                full_target_ids.append(dict_en[c])
            curr_span_pos += len(chars)
            e_pos = curr_span_pos
            line_tok_spans.append((tok, s_pos, e_pos))
            vocal_idx += 1
            if vocal_idx < vocal_count:
                full_target_ids.append(dict_en["|"])
                curr_span_pos += 1

        full_tokens_with_spans.append((orig_idx, ly, line_tok_spans))
        if li < len(lines_with_idx) - 1 and full_target_ids:
            full_target_ids.append(dict_en["|"])
            curr_span_pos += 1

    if not full_target_ids or wav_slice.size(1) < 400:
        for orig_idx, ly in lines_with_idx:
            words = _fallback_even_split(ly.text, s_sec, e_sec)
            res[orig_idx] = AlignedLine(text=ly.text, start=s_sec, end=e_sec, words=words)
        return res

    targets = torch.tensor([full_target_ids], dtype=torch.int32)
    try:
        aligned_tokens, scores = forced_align(emissions, targets, blank=0)
        spans = merge_tokens(aligned_tokens[0], scores[0], blank=0)
    except Exception as e:
        log.warning("英文 CTC 对齐异常，回退均匀切分: %s", e)
        for orig_idx, ly in lines_with_idx:
            words = _fallback_even_split(ly.text, s_sec, e_sec)
            res[orig_idx] = AlignedLine(text=ly.text, start=s_sec, end=e_sec, words=words)
        return res

    frame_dur = (wav_slice.size(1) / 16000.0) / emissions.size(1)

    for orig_idx, ly, line_tok_spans in full_tokens_with_spans:
        words: list[WordTimestamp] = []
        for tok, s_pos, e_pos in line_tok_spans:
            if s_pos == e_pos:
                prev_end = words[-1].end if words else s_sec
                words.append(WordTimestamp(word=tok, start=round(prev_end, 3), end=round(prev_end, 3)))
                continue
            w_spans = spans[s_pos:e_pos]
            if not w_spans:
                prev_end = words[-1].end if words else s_sec
                words.append(WordTimestamp(word=tok, start=round(prev_end, 3), end=round(prev_end + 0.1, 3)))
                continue
            w_s = s_sec + w_spans[0].start * frame_dur
            w_e = s_sec + w_spans[-1].end * frame_dur
            w_s = _trim_word_over_silence(w_s, w_e, singing_sections)
            if task.window_end < total_audio_sec - 0.5:
                w_e = min(w_e, task.window_end)
            w_e = max(w_e, w_s + 0.05)
            words.append(WordTimestamp(word=tok, start=round(w_s, 3), end=round(w_e, 3)))

        vocal_words = [w for w in words if re.search(r"[\w\u4e00-\u9fff]", w.word)]
        if any((w.end - w.start) <= 0.035 for w in vocal_words):
            words = _fallback_even_split(ly.text, s_sec, e_sec)

        res[orig_idx] = AlignedLine(
            text=ly.text,
            start=words[0].start if words else s_sec,
            end=words[-1].end if words else e_sec,
            words=words,
        )

    return res


def _execute_zh_task(
    task: AlignmentTask,
    wav_16k: torch.Tensor,
    models: dict[str, Any],
    singing_sections: list[tuple[float, float]],
    total_audio_sec: float,
) -> dict[int, AlignedLine]:
    lines_with_idx = task.lyrics
    s_sec = max(0.0, task.window_start - 0.2)
    e_sec = min(total_audio_sec, task.window_end + 0.3)
    wav_slice = wav_16k[:, int(s_sec * 16000): int(e_sec * 16000)]

    res: dict[int, AlignedLine] = {}

    if wav_slice.size(1) < 400:
        for orig_idx, ly in lines_with_idx:
            words = _fallback_even_split(ly.text, s_sec, e_sec)
            res[orig_idx] = AlignedLine(text=ly.text, start=s_sec, end=e_sec, words=words)
        return res

    model_zh = models["model_zh"]
    proc_zh = models["proc_zh"]
    blank_zh = models.get("blank_zh", 0)

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
    target_ids = [tid for tid in target_ids if tid is not None and tid != blank_zh]
    if not target_ids:
        for orig_idx, ly in lines_with_idx:
            words = _fallback_even_split(ly.text, s_sec, e_sec)
            res[orig_idx] = AlignedLine(text=ly.text, start=s_sec, end=e_sec, words=words)
        return res

    targets = torch.tensor([target_ids], dtype=torch.int32)
    try:
        aligned_tokens, scores = forced_align(emissions, targets, blank=blank_zh)
        spans = merge_tokens(aligned_tokens[0], scores[0], blank=blank_zh)
    except Exception as e:
        log.warning("中文 CTC 对齐异常，回退均匀切分: %s", e)
        for orig_idx, ly in lines_with_idx:
            words = _fallback_even_split(ly.text, s_sec, e_sec)
            res[orig_idx] = AlignedLine(text=ly.text, start=s_sec, end=e_sec, words=words)
        return res

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

        vocal_words = [w for w in words if re.search(r"[\w\u4e00-\u9fff]", w.word)]
        if any((w.end - w.start) <= 0.035 for w in vocal_words):
            words = _fallback_even_split(ly.text, s_sec, e_sec)

        res[orig_idx] = AlignedLine(
            text=ly.text,
            start=words[0].start if words else s_sec,
            end=words[-1].end if words else e_sec,
            words=words,
        )

    return res


def _execute_other_task(
    task: AlignmentTask,
    wav_16k: torch.Tensor,
    models: dict[str, Any],
    singing_sections: list[tuple[float, float]],
    total_audio_sec: float,
    config: AlignerConfig | None = None,
) -> dict[int, AlignedLine]:
    lines_with_idx = task.lyrics
    s_sec = task.window_start
    e_sec = task.window_end
    sr = 16000

    wav_np = wav_16k.squeeze(0).cpu().numpy()
    sub_slice = wav_np[int(s_sec * sr): int(e_sec * sr)]

    all_w: list[tuple[float, float, str]] = []
    transcribe_func = models.get("transcribe_whisper_func")
    if len(sub_slice) > int(sr * 0.5) and transcribe_func is not None:
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                tmp_path = tf.name
            sf.write(tmp_path, sub_slice, sr)
            segments, _ = transcribe_func(tmp_path, config, word_timestamps=True)
            for s in segments:
                if getattr(s, "words", None):
                    for w in s.words:
                        w_str = w.word.strip()
                        if w_str:
                            all_w.append((s_sec + w.start, s_sec + w.end, w_str))
            Path(tmp_path).unlink(missing_ok=True)
        except Exception as e:
            log.warning("多语言 Whisper 局部转写异常，转为平滑插值: %s", e)

    all_line_toks: list[tuple[int, str, str]] = []
    for orig_idx, ly in lines_with_idx:
        tokens = tokenize_lyric_line(ly.text)
        for tok in tokens:
            clean = "".join(c.lower() for c in tok if c.isalnum())
            all_line_toks.append((orig_idx, tok, clean))

    token_times: list[tuple[float, float] | None] = [None] * len(all_line_toks)
    match_sim = 0.0

    if all_w and all_line_toks:
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

    res: dict[int, AlignedLine] = {}
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

        res[orig_idx] = AlignedLine(
            text=ly.text,
            start=words[0].start if words else exp_s,
            end=words[-1].end if words else exp_e,
            words=words,
            style_overrides={"confidence": "low" if is_low_conf else "normal"},
        )

    return res


def execute_all_tasks(
    tasks: list[AlignmentTask],
    wav_16k: torch.Tensor,
    models: dict[str, Any],
    singing_sections: list[tuple[float, float]],
    total_audio_sec: float,
    config: AlignerConfig | None = None,
) -> dict[int, AlignedLine]:
    """执行全部规划的 AlignmentTask 单元并聚合行级对齐结果。"""
    all_lines: dict[int, AlignedLine] = {}
    for task in tasks:
        task_res = execute_task(
            task=task,
            wav_16k=wav_16k,
            models=models,
            singing_sections=singing_sections,
            total_audio_sec=total_audio_sec,
            config=config,
        )
        for orig_idx, line in task_res.items():
            if orig_idx in all_lines:
                raise ValueError(f"严重冲突: 行索引 {orig_idx} 被重复执行并覆盖！")
            all_lines[orig_idx] = line
    return all_lines
