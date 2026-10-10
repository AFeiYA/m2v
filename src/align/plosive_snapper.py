"""
Acoustic refinement for plosive consonant onsets, vocal melisma bridging, and syllable decomposition.

Features:
1. Plosive Snapping (辅音爆破点吸附):
   Voiceless stops (/k/, /p/, /t/) exhibit an acoustic closure dip followed by a sharp burst spike.
   This module snaps the word onset to the exact burst frame and prevents the preceding word from
   colliding with the burst.
2. Melisma Extension (转音/拖音智能延续):
   When a word is held across a syncopated delay/riff before the next plosive (e.g. 'never' before 'could'),
   detects continuous vocal energy (RMS > threshold) and extends the preceding word's end to the closure gap,
   eliminating awkward silent voids.
3. Syllable Decomposition (英文多音节拆分):
   Splits multi-syllable English words (e.g. 'ne-ver') and creates SyllableTimestamp objects,
   allocating melismas to the continuing sonorant syllable.
"""

from __future__ import annotations

import re
from typing import Optional
import numpy as np

from src.storyboard_schema import SyllableTimestamp, WordTimestamp
from src.utils import log

# Voiceless plosive onsets:
# /k/: k..., c(a/o/u/l/r)..., q...
# /p/: p... (not ph...)
# /t/: t... (not th...)
_PLOSIVE_ONSET_RE = re.compile(r"^(k|c[aoulr]|q|p(?!h)|t(?!h))", re.I)

# Syllable splitting vowels
_VOWELS = "aeiouy"


def split_english_syllable_texts(word: str) -> list[str]:
    """Rule-based syllabification for English words.
    
    Returns a list of syllable strings that concatenate back to the original word.
    """
    clean = re.sub(r"^[^\w']+|[^\w']+$", "", word.strip())
    if not clean or len(clean) <= 3 or re.search(r"[\u4e00-\u9fff]", clean):
        return [word]

    lower = clean.lower()
    nuclei: list[tuple[int, int]] = []
    i = 0
    while i < len(lower):
        if lower[i] in _VOWELS:
            start = i
            while i < len(lower) and lower[i] in _VOWELS:
                i += 1
            nuclei.append((start, i))
        else:
            i += 1

    # Drop silent e at end (e.g. 'take', 'make', 'could')
    if len(nuclei) > 1 and lower.endswith("e") and not lower.endswith("le") and not lower.endswith("ee"):
        if nuclei[-1] == (len(lower) - 1, len(lower)):
            nuclei.pop()

    if len(nuclei) <= 1:
        return [word]

    splits: list[int] = []
    for idx in range(len(nuclei) - 1):
        _n1_start, n1_end = nuclei[idx]
        n2_start, _n2_end = nuclei[idx + 1]
        cons = lower[n1_end:n2_start]
        if len(cons) == 0:
            sp = n1_end
        elif len(cons) == 1:
            # Open syllable (e.g. ne-ver, mo-ving)
            sp = n1_end
        elif len(cons) == 2:
            # Digraphs stay together or split between consonants
            if cons in ("th", "sh", "ch", "ph", "wh", "ck"):
                sp = n1_end
            else:
                sp = n1_end + 1
        else:
            sp = n1_end + 1
        splits.append(sp)

    res: list[str] = []
    p = 0
    for sp in splits:
        res.append(clean[p:sp])
        p = sp
    res.append(clean[p:])
    return [r for r in res if r]


def decompose_word_syllables(w: WordTimestamp) -> list[SyllableTimestamp] | None:
    """Decomposes an English word into SyllableTimestamp objects if it has multiple syllables.
    
    If the word is prolonged/held (melisma), the initial syllable receives standard conversational
    duration, and the continuing vowel/sonorant syllable receives the prolonged melisma duration.
    """
    # If syllables are already manually populated, do not overwrite
    if w.syllables:
        return w.syllables

    syl_texts = split_english_syllable_texts(w.word)
    if len(syl_texts) <= 1:
        return None

    dur = w.end - w.start
    if dur <= 0.05:
        return None

    num_syl = len(syl_texts)

    # Two-syllable word with prolonged duration (e.g. 'ne-ver' taking > 0.45s)
    if num_syl == 2 and dur >= 0.45:
        # Initial syllable is spoken quickly (0.20s ~ 0.32s)
        s1_dur = min(0.32, round(dur * 0.35, 3))
        s1_end = round(w.start + s1_dur, 3)
        return [
            SyllableTimestamp(text=syl_texts[0], start=w.start, end=s1_end),
            SyllableTimestamp(text=syl_texts[1], start=s1_end, end=w.end),
        ]

    # General multi-syllable distribution weighted by character length
    lens = [max(1, len(st)) for st in syl_texts]
    total_len = sum(lens)
    curr_t = w.start
    res: list[SyllableTimestamp] = []
    for s_idx, st in enumerate(syl_texts):
        if s_idx == num_syl - 1:
            res.append(SyllableTimestamp(text=st, start=round(curr_t, 3), end=w.end))
        else:
            s_dur = dur * (lens[s_idx] / total_len)
            next_t = round(curr_t + s_dur, 3)
            res.append(SyllableTimestamp(text=st, start=round(curr_t, 3), end=next_t))
            curr_t = next_t
    return res


def _extract_burst_candidates(
    clip: np.ndarray,
    s_bound: float,
    sr: int = 16000,
    min_score: float = 30.0,
) -> list[tuple[float, float, float]]:
    """Extracts burst candidates sorted by score descending: (score, burst_time, closure_time)."""
    if len(clip) < int(sr * 0.04):
        return []
    import librosa
    hop = int(sr * 0.005)  # 5ms
    win = int(sr * 0.015)  # 15ms
    rms = librosa.feature.rms(y=clip, frame_length=win, hop_length=hop)[0]
    n_fft = min(512, len(clip))
    onset = librosa.onset.onset_strength(y=clip, sr=sr, hop_length=hop, n_fft=n_fft)
    min_len = min(len(rms), len(onset))
    rms = rms[:min_len]
    onset = onset[:min_len]
    times = s_bound + np.arange(min_len) * 0.005
    pre_window = int(0.06 / 0.005)

    candidates: list[tuple[float, float, float]] = []
    for idx in range(1, min_len - 1):
        o_curr = onset[idx]
        pre_start = max(0, idx - pre_window)
        pre_rms = np.min(rms[pre_start:idx]) if idx > pre_start else rms[idx]
        if o_curr > 0.8:
            score = o_curr / (pre_rms + 0.005)
            if score >= min_score:
                c_idx = pre_start + int(np.argmin(rms[pre_start:idx])) if idx > pre_start else idx
                candidates.append((float(score), float(times[idx]), float(times[c_idx])))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates


def refine_plosives_and_melisma(
    words: list[WordTimestamp],
    wav_16k: np.ndarray,
    sr: int = 16000,
    clip_offset: float = 0.0,
) -> list[WordTimestamp]:
    """Detects plosive consonant onsets, snaps burst timings, bridges vocal melismas,
    and populates syllable-level breakdown.
    """
    if not words or len(wav_16k) < int(sr * 0.1):
        return words

    try:
        import librosa
    except ImportError:
        return words

    for i in range(len(words)):
        w = words[i]
        clean_w = re.sub(r"^[^\w']+|[^\w']+$", "", w.word).lower()
        if not _PLOSIVE_ONSET_RE.match(clean_w):
            continue

        w_start = w.start
        w_end = w.end
        dur = w_end - w_start
        prev_w = words[i - 1] if i > 0 else None
        is_mono = len(split_english_syllable_texts(w.word)) <= 1

        snapped = False
        # 1. 针对被 Whisper 误将前置转音/长音划入本词的异常超长辅音词 (如 'never could' 中 could 被拉长至 1.3s)
        # 如果是单音节词且 dur > 0.40s，或任意词 dur > 0.60s，且前词存在：
        # 向后广域搜索是否存在真实的后置卡点爆破
        if prev_w is not None and ((is_mono and dur > 0.40) or dur > 0.60):
            s_wide = w_start + 0.15
            e_wide = w_end - 0.05
            s_idx = max(0, int((s_wide - clip_offset) * sr))
            e_idx = min(len(wav_16k), int((e_wide - clip_offset) * sr))
            if e_idx - s_idx >= int(sr * 0.05):
                clip_wide = wav_16k[s_idx:e_idx]
                late_cands = _extract_burst_candidates(clip_wide, s_wide, sr=sr, min_score=50.0)
                late_cands = [c for c in late_cands if c[1] >= w_start + 0.25]
                for sc, b_t, c_t in late_cands:
                    # 检查从 prev_w.end 到该闭塞点之间是否为连续人声转音 (低静音率、高能量)
                    m_s = max(0, int((prev_w.end - clip_offset) * sr))
                    m_e = min(len(wav_16k), int((c_t - clip_offset) * sr))
                    if m_e - m_s >= int(sr * 0.05):
                        m_clip = wav_16k[m_s:m_e]
                        m_rms = librosa.feature.rms(y=m_clip, frame_length=int(sr * 0.03), hop_length=int(sr * 0.01))[0]
                        sil_ratio = np.mean(m_rms < 0.012)
                        mean_r = np.mean(m_rms)
                        if sil_ratio < 0.18 and mean_r > 0.025:
                            burst_time = round(float(b_t), 3)
                            closure_time = round(float(c_t), 3)
                            log.info(
                                "🎵 [爆破后移与转音贯通] '%s' 真实爆破在 %.3fs (闭塞点 %.3fs, 评分 %.1f)，将前词 '%s' 贯通至 %.3fs",
                                w.word,
                                burst_time,
                                closure_time,
                                sc,
                                prev_w.word,
                                closure_time,
                            )
                            w.start = burst_time
                            w.end = max(w.end, round(w.start + 0.22, 3))
                            prev_w.end = closure_time
                            prev_w.syllables = None  # 重新触发音节时长拆解
                            snapped = True
                            break

        if snapped:
            continue

        # 2. 常规近邻爆破搜索: [w_start - 0.25, w_start + 0.20]
        prev_start = prev_w.start if prev_w else w_start - 0.5
        s_bound = max(prev_start + 0.10, w_start - 0.25)
        e_bound = min(w_end - 0.05, w_start + 0.20)
        if e_bound <= s_bound + 0.04:
            continue

        s_idx = max(0, int((s_bound - clip_offset) * sr))
        e_idx = min(len(wav_16k), int((e_bound - clip_offset) * sr))
        if e_idx - s_idx < int(sr * 0.04):
            continue

        clip = wav_16k[s_idx:e_idx]
        local_cands = _extract_burst_candidates(clip, s_bound, sr=sr, min_score=30.0)
        if local_cands:
            sc, b_t, c_t = local_cands[0]
            burst_time = round(float(b_t), 3)
            closure_time = round(float(c_t), 3)
            w.start = burst_time

            if prev_w is not None:
                gap = closure_time - prev_w.end
                if gap > 0.15:
                    g_s = max(0, int((prev_w.end - clip_offset) * sr))
                    g_e = min(len(wav_16k), int((closure_time - clip_offset) * sr))
                    if g_e - g_s >= int(sr * 0.05):
                        g_clip = wav_16k[g_s:g_e]
                        g_rms = librosa.feature.rms(y=g_clip, frame_length=int(sr * 0.03), hop_length=int(sr * 0.01))[0]
                        if np.mean(g_rms > 0.02) > 0.40:
                            log.info(
                                "🎵 [转音智能延续] 检测到 '%s' 延展转音 (%.2fs ~ %.2fs)，桥接至爆破闭塞点 %.3fs",
                                prev_w.word,
                                prev_w.end,
                                closure_time,
                                closure_time,
                            )
                            prev_w.end = closure_time
                            prev_w.syllables = None
                elif prev_w.end > burst_time:
                    prev_w.end = max(prev_w.start + 0.05, closure_time)
                    prev_w.syllables = None

    # Populate syllable decomposition for all multi-syllable words in the line
    for w in words:
        if not w.syllables:
            syls = decompose_word_syllables(w)
            if syls:
                w.syllables = syls

    return words

