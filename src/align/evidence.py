"""
Acoustic and Phonetic Evidence Processing.
Provides phonetic tokenization, sequence matching, phrase anchoring,
and silence-snapped boundary refinement.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

import numpy as np
import pypinyin

from src.storyboard_schema import WordTimestamp

if TYPE_CHECKING:
    from src.preprocessor import LyricLine

log = logging.getLogger("m2v")

_CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


def tokenize_lyric_line(text: str) -> list[str]:
    """将单行歌词拆分为最小对齐单元 (Tokens)。"""
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if _CHINESE_CHAR_RE.match(char):
            j = i + 1
            while j < n and not _CHINESE_CHAR_RE.match(text[j]) and not text[j].isalnum() and not text[j].isspace():
                j += 1
            tokens.append(text[i:j])
            i = j
        elif char.isalnum() or char == "'":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "'"):
                j += 1
            if j < n and text[j] == "-" and j + 1 < n and (text[j + 1].isalnum() or text[j + 1] == "'"):
                j += 1
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


def tokenize_lyric_phonetic(text: str) -> list[dict]:
    """提取歌词行的发音 token (中文转拼音，英文转小写单词)。"""
    text = text.translate(str.maketrans({"’": "'", "‘": "'", "`": "'", "\u2060": "", "\u200b": "", "\ufeff": ""}))
    parts = re.findall(r'[\u4e00-\u9fff]|[a-zA-Z0-9\']+', text)
    tokens = []
    for p in parts:
        if '\u4e00' <= p <= '\u9fff':
            pys = pypinyin.lazy_pinyin(p)
            py = pys[0].lower() if pys else p.lower()
            tokens.append({'raw': p, 'py': py})
        else:
            clean = re.sub(r'[^a-zA-Z0-9]', '', p).lower()
            if clean:
                tokens.append({'raw': clean, 'py': clean})
    return tokens


def _fallback_even_split(
    text: str,
    start: float,
    end: float,
) -> list[WordTimestamp]:
    """将一行文本按字符均分时长 (兜底 fallback 策略)。"""
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


def _mixed_run_split_bounds(start: float, end: float, remaining_counts: list[int]) -> tuple[float, float, float]:
    """Allocate the remaining window; duration budgets are heuristics, not evidence."""
    if end <= start or len(remaining_counts) < 2:
        raise ValueError("混合语言切分需要有效窗口和至少两个语言块")
    counts = [max(1, n) for n in remaining_counts]
    duration = end - start
    ideal = start + duration * counts[0] / sum(counts)
    budgets = [max(0.8, n * 0.30) for n in counts]
    if sum(budgets) > duration:
        log.warning("混合语言窗口 %.2fs 不足建议时长 %.2fs，按剩余词量分配；需复核", duration, sum(budgets))
        return ideal, ideal, ideal
    return ideal, start + budgets[0], end - sum(budgets[1:])


def find_silence_snap(
    t_ideal: float,
    wav_np: np.ndarray | None,
    sr: int = 16000,
    window: float = 2.5,
    min_t: float = 0.0,
    max_t: float = float("inf"),
) -> float:
    """在给定时间附近寻找能量 (RMS) 极小值点，将段落或乐句边界吸附至声学停顿，避免切在发音中央。"""
    if min_t > max_t:
        raise ValueError("静音吸附边界冲突，不能在空窗口内定位")
    def bounded(t: float) -> float:
        return max(min_t, min(max_t, round(t, 2)))
    if wav_np is None or len(wav_np) == 0:
        return bounded(t_ideal)
    t_min = max(min_t, t_ideal - window)
    t_max = min(max_t, min(len(wav_np) / sr, t_ideal + window))
    if t_max <= t_min:
        return bounded(t_ideal)
    step = 0.05
    best_t = t_ideal
    best_rms = float("inf")
    for t in np.arange(t_min, t_max, step):
        s1 = int(t * sr)
        s2 = int((t + step) * sr)
        if s2 > len(wav_np):
            break
        rms = np.sqrt(np.mean(wav_np[s1:s2] ** 2))
        if rms < best_rms:
            best_rms = rms
            best_t = t + step / 2
    return bounded(best_t)


def _unique_phrase_anchors(paras: dict, asr_words: list[dict]) -> dict[int, tuple[float, float]]:
    """Find conservative local evidence; repeated or out-of-order phrases are not anchors."""
    lyric_tokens = [(p, [t["py"] for t in tokenize_lyric_phonetic(ly.text)])
                    for p, lines in paras.items() for _, ly in lines]
    audio_tokens = [w["py"] for w in asr_words]

    def occurrences(tokens, phrase):
        n = len(phrase)
        return sum(tokens[i:i + n] == phrase for i in range(len(tokens) - n + 1))

    matches = []
    for order, (p, tokens) in enumerate(lyric_tokens):
        for block in SequenceMatcher(None, tokens, audio_tokens, autojunk=False).get_matching_blocks():
            if block.size < 4 or (block.size < 6 and block.size * 2 < len(tokens)):
                continue
            phrase = tokens[block.a:block.a + block.size]
            if occurrences(audio_tokens, phrase) != 1:
                continue
            if sum(occurrences(ts, phrase) for _, ts in lyric_tokens) != 1:
                continue
            words = asr_words[block.b:block.b + block.size]
            if any(b["start"] < a["end"] or b["start"] - a["end"] > 1.5
                   for a, b in zip(words, words[1:])):
                continue
            matches.append((order, block.a, p, words[0]["start"], words[-1]["end"], block.size))

    matches.sort(key=lambda m: (m[0], m[1]))
    scores, paths = [], []
    for i, match in enumerate(matches):
        best, path = match[5], [i]
        for j in range(i):
            if matches[j][4] <= match[3] and scores[j] + match[5] > best:
                best, path = scores[j] + match[5], paths[j] + [i]
        scores.append(best)
        paths.append(path)
    anchors = {}
    if scores:
        for i in paths[max(range(len(scores)), key=scores.__getitem__)]:
            _, _, p, start, end, _ = matches[i]
            old = anchors.get(p, (start, end))
            anchors[p] = (min(old[0], start), max(old[1], end))
    return anchors


def detect_line_lang(text: str, song_lang: str | None = None) -> str:
    """检测歌词行的语言类型 (zh, ja, ko, en, other)。"""
    if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    zh = len(_CHINESE_CHAR_RE.findall(text))
    latin = len(re.findall(r"[a-zA-Z\u00C0-\u024F]", text))
    if zh > latin:
        return "zh"
    if latin > 0:
        accented = len(re.findall(r"[\u00C0-\u024F]", text))
        if accented > 0 and (accented / max(1, latin) > 0.15):
            return "other"
        return "en"
    if song_lang and song_lang not in ("mixed", "auto"):
        return song_lang
    return "en"


def detect_song_primary_language(lines: list[LyricLine], explicit_lang: str | None = None) -> str:
    """检测全曲主语言判定 (zh, en, mixed, other)。"""
    if explicit_lang and explicit_lang not in ("auto", "mixed"):
        return explicit_lang

    valid_texts = [l.text.strip() for l in lines if l.text.strip() and not re.fullmatch(r"\[.*\]|[（(].*[）)]", l.text.strip())]
    if not valid_texts:
        return explicit_lang or "zh"

    zh_lines = sum(1 for t in valid_texts if len(_CHINESE_CHAR_RE.findall(t)) > 0)
    en_lines = sum(1 for t in valid_texts if len(re.findall(r"[a-zA-Z]", t)) > 0 and len(_CHINESE_CHAR_RE.findall(t)) == 0)
    total_lines = len(valid_texts)

    if zh_lines >= 2 and en_lines >= 2:
        return "mixed"

    accented_chars = sum(len(re.findall(r"[\u00C0-\u024F]", t)) for t in valid_texts)
    latin_chars = sum(len(re.findall(r"[a-zA-Z]", t)) for t in valid_texts)
    if accented_chars > 15 and accented_chars / max(1, latin_chars) > 0.1:
        return "other"

    if zh_lines / total_lines >= 0.60:
        return "zh"
    if en_lines / total_lines >= 0.75:
        return "en"
    return "mixed"
