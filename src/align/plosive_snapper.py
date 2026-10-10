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
        prev_end = words[i - 1].end if i > 0 else w_start - 0.5
        prev_start = words[i - 1].start if i > 0 else prev_end

        # Search window for plosive burst near w.start: [w_start - 0.25, w_start + 0.20]
        s_bound = max(prev_start + 0.10, w_start - 0.25)
        e_bound = min(w.end - 0.05, w_start + 0.20)

        if e_bound <= s_bound + 0.04:
            continue

        s_idx = int((s_bound - clip_offset) * sr)
        e_idx = int((e_bound - clip_offset) * sr)
        if s_idx < 0 or e_idx > len(wav_16k) or e_idx - s_idx < int(sr * 0.04):
            continue

        clip = wav_16k[s_idx:e_idx]
        hop = int(sr * 0.005)  # 5ms
        win = int(sr * 0.015)  # 15ms
        rms = librosa.feature.rms(y=clip, frame_length=win, hop_length=hop)[0]
        n_fft = min(512, len(clip))
        onset = librosa.onset.onset_strength(y=clip, sr=sr, hop_length=hop, n_fft=n_fft)
        times = s_bound + np.arange(len(rms)) * 0.005

        best_burst_t: Optional[float] = None
        best_burst_score = 0.0
        best_closure_t: Optional[float] = None

        for idx in range(1, len(times) - 1):
            t_curr = times[idx]
            o_curr = onset[idx]
            pre_start = max(0, idx - int(0.06 / 0.005))
            pre_rms = np.min(rms[pre_start:idx]) if idx > pre_start else rms[idx]

            # Burst has significant onset and pre_rms is an acoustic dip
            if o_curr > 0.8:
                score = o_curr / (pre_rms + 0.005)
                if score > best_burst_score:
                    best_burst_score = score
                    best_burst_t = t_curr
                    c_idx = pre_start + int(np.argmin(rms[pre_start:idx]))
                    best_closure_t = times[c_idx]

        if best_burst_t is not None and best_burst_score > 30.0 and best_closure_t is not None:
            burst_time = round(float(best_burst_t), 3)
            closure_time = round(float(best_closure_t), 3)

            # Snap word start to burst
            w.start = burst_time

            # Refine previous word if in the same phrase
            if i > 0:
                prev_w = words[i - 1]
                gap = closure_time - prev_w.end
                if gap > 0.15:
                    # Check if there is vocal melisma / continuation in [prev_w.end, closure_time]
                    g_s_idx = int((prev_w.end - clip_offset) * sr)
                    g_e_idx = int((closure_time - clip_offset) * sr)
                    if g_e_idx > g_s_idx + int(sr * 0.05):
                        g_clip = wav_16k[g_s_idx:g_e_idx]
                        g_rms = librosa.feature.rms(y=g_clip, frame_length=int(sr * 0.03), hop_length=int(sr * 0.01))[0]
                        active_ratio = np.mean(g_rms > 0.02)
                        if active_ratio > 0.40:
                            log.info(
                                "🎵 [转音智能延续] 检测到 '%s' 延展转音 (%.2fs ~ %.2fs)，桥接至爆破闭塞点 %.3fs",
                                prev_w.word,
                                prev_w.end,
                                closure_time,
                                closure_time,
                            )
                            prev_w.end = closure_time
                elif prev_w.end > burst_time:
                    # Overlapping with burst: pull back to before closure
                    prev_w.end = max(prev_w.start + 0.05, closure_time)

    # Populate syllable decomposition for all multi-syllable words in the line
    for w in words:
        if not w.syllables:
            syls = decompose_word_syllables(w)
            if syls:
                w.syllables = syls

    return words
