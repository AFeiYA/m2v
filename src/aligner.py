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
import hashlib
import json
import re
import sys
from dataclasses import replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

import numpy as np
import soundfile as sf
import torch
import torchaudio
from torchaudio.functional import forced_align, merge_tokens
from transformers import AutoModelForCTC, AutoProcessor
import pypinyin

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
        try:
            _whisper_cache[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
        except Exception as error:
            if device != "cuda" or not _is_cuda_failure(error):
                raise
            log.warning("Whisper CUDA 初始化失败，改用 CPU/int8: %s", error)
            return _get_whisper(replace(config, device="cpu", compute_type="int8"))
    return _whisper_cache[key]


def _is_cuda_failure(error: Exception) -> bool:
    return any(word in str(error).lower() for word in ("cuda", "cublas", "cudnn"))


def _transcribe_whisper(audio_path: str, config: AlignerConfig | None = None, **options):
    """Consume lazy segments inside the retry boundary (CUDA may fail on iteration)."""
    cfg = config or AlignerConfig()
    try:
        segments, info = _get_whisper(cfg).transcribe(audio_path, **options)
        return list(segments), info
    except Exception as error:
        if cfg.device != "cuda" or not _is_cuda_failure(error):
            raise
        log.warning("Whisper CUDA 推理失败，重新用 CPU/int8 完整提取锚点: %s", error)
        cpu_config = replace(cfg, device="cpu", compute_type="int8")
        segments, info = _get_whisper(cpu_config).transcribe(audio_path, **options)
        return list(segments), info


def _validate_asr_evidence(asr_words: list[dict], line_count: int, singing_sections: list) -> None:
    if line_count <= 1:
        return
    if not asr_words:
        raise RuntimeError("歌词对齐失败：未能提取句级 ASR 锚点，不能用估算窗口生成整首歌。请重试或检查 Whisper 运行环境。")
    if singing_sections:
        voice_end = max(end for _, end in singing_sections)
        asr_end = max(word["end"] for word in asr_words)
        if voice_end - asr_end > max(20.0, voice_end * 0.2):
            raise RuntimeError(f"歌词对齐失败：ASR 锚点仅到 {asr_end:.1f}s，人声延续到 {voice_end:.1f}s，后段覆盖不足，请重新识别。")

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


def detect_song_language(lyrics: list[Any]) -> str:
    """
    根据全曲歌词统计判定歌曲的主体语言 (Song-level Language Prior):
    - zh: 纯中文 (或极少数拟声英文)
    - en: 纯英文 (绝大多数行为标准拉丁英文)
    - ja: 日文 (假名显著)
    - ko: 韩文 (谚文显著)
    - mixed: 中英混唱 / 多语言 (需启用 Whisper 多语言自动识别)
    - other: 变音符拉丁小语种
    """
    if not lyrics:
        return "en"
    texts = [getattr(l, "text", str(l)) for l in lyrics if not getattr(l, "is_annotation", False)]
    valid_texts = [t.strip() for t in texts if t.strip()]
    if not valid_texts:
        return "en"

    ja_count = sum(1 for t in valid_texts if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", t))
    ko_count = sum(1 for t in valid_texts if re.search(r"[\uac00-\ud7af]", t))
    if ja_count / len(valid_texts) >= 0.15:
        return "ja"
    if ko_count / len(valid_texts) >= 0.15:
        return "ko"

    zh_lines = sum(1 for t in valid_texts if len(_CHINESE_CHAR_RE.findall(t)) > 0)
    en_lines = sum(1 for t in valid_texts if len(re.findall(r"[a-zA-Z]", t)) > 0 and len(_CHINESE_CHAR_RE.findall(t)) == 0)
    total_lines = len(valid_texts)

    # 若同时存在明确的中文行与英文行 (中英双语歌)，判定为 mixed，不能强制指定单一语言截断另一门语言
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


def detect_line_lang(text: str, song_lang: str | None = None) -> str:
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
        return "zh" if zh > 0 else (song_lang if song_lang not in ("mixed", None) else "en")
    accented = len(re.findall(r"[\u00C0-\u024F]", text))
    if accented > 0:
        return "other"

    # 若全曲主语言确认为纯英文，且无变音符/中日韩字符，坚决遵循全曲英文主干，杜绝单字碰撞小语种误判
    if song_lang == "en":
        return "en"

    tokens = set(re.findall(r"[a-zA-Z]+", text.lower()))
    # 严格小语种特征词表：已剔除与常用英文重叠的 "die", "con", "la", "so", "in", "an", "est" 等
    other_distinctive = {
        "les", "des", "sur", "avec", "dans", "pour", "une", "croissants",
        "moi", "toi", "doux", "quand", "sont", "nous", "vous",
        "el", "los", "las", "del", "por", "para", "una",
        "und", "der", "das", "mit", "nicht", "eine", "einer"
    }
    matched = tokens & other_distinctive
    if len(matched) >= 2 or (len(matched) >= 1 and any(w in matched for w in ["croissants", "nicht", "avec", "moi", "toi", "pour", "dans", "und", "der", "das"])):
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
    - 连字符复合词: 按音节切分 (如 'BRO-KEN-MAN' -> ['BRO-', 'KEN-', 'MAN'])
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
        elif char.isalnum() or char == "'":
            # 英文单词连续捕获
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "'"):
                j += 1
            # 若紧随连字符且连字符后接字母 (如 BRO-KEN-MAN)，将连字符吸附至当前音节词尾，保留独立音节对齐
            if j < n and text[j] == "-" and j + 1 < n and (text[j + 1].isalnum() or text[j + 1] == "'"):
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
    for i, line in enumerate(lines):
        if re.fullmatch(r'\[.*\]|[（(].*[）)]', line.text.strip()):
            continue
        vocal = [w for w in line.words if re.search(r"[\w\u4e00-\u9fff]", w.word)]
        if len(vocal) >= 4 and (line.end - line.start < 0.25 or
                               sum(w.end - w.start <= 0.035 for w in vocal) / len(vocal) >= 0.8):
            return f"第 {i + 1} 行存在整句时间坍缩，需要重新定位，不能作为成功结果"
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
            style_overrides=dict(line.style_overrides) if line.style_overrides else {},
        ))
        prev_end = line_end
    return out


# ---------------------------------------------------------------------------
# 多语言语义 ASR 锚点提取与单调序列对齐模块 (ASR-Anchored Monotonic Matcher)
# ---------------------------------------------------------------------------

def tokenize_lyric_phonetic(text: str) -> list[dict]:
    """提取歌词行的发音 token (中文转拼音，英文转小写单词)"""
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


def extract_asr_words(
    vocals_path: Path,
    lyrics_prompt: str = "",
    config: AlignerConfig | None = None,
    language: str | None = None,
    force_refresh: bool = False,
) -> list[dict]:
    """
    使用 faster-whisper 提取 ASR 词级时间戳锚点 (支持磁盘缓存与元数据校验)。
    识别文字仅作为定位证据，绝不篡改原歌词。
    """
    cache_path = vocals_path.parent / f".{vocals_path.stem}_asr_words.json"
    req_lang = language or (config.language if config and config.language != "auto" else None)

    if cache_path.exists() and not force_refresh:
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "words" in data:
                meta = data.get("meta", {})
                cached_words = data.get("words", [])
                st = vocals_path.stat()
                mtime_ok = abs(meta.get("mtime", 0.0) - st.st_mtime) < 2.0
                lang_ok = (meta.get("language") == req_lang) or (not req_lang)
                model_ok = meta.get("model") == (config.whisper_model if config else "large-v3")
                size_ok = meta.get("size") == st.st_size
                if data.get("version") == 4 and mtime_ok and lang_ok and model_ok and size_ok and cached_words:
                    log.info("🎯 复用已缓存的 ASR 词级时间戳 (v4): %s (%d 个词, lang=%s)",
                             cache_path.name, len(cached_words), meta.get("language"))
                    return cached_words
        except Exception:
            pass

    try:
        transcribe_opts: dict[str, Any] = {
            "beam_size": 5,
            "word_timestamps": True,
            "condition_on_previous_text": False,
            "vad_filter": False,  # 歌曲人声禁止默认 Silero VAD，避免弱音/呢喃/嘶吼被大面积截断
        }
        if req_lang in ("en", "zh", "ja", "ko"):
            transcribe_opts["language"] = req_lang
            transcribe_opts["multilingual"] = False
        else:
            transcribe_opts["multilingual"] = True

        # 仅在非英文或特殊提示场景下传入 prompt，避免英文歌曲 prompt 造成注意力重复循环
        if lyrics_prompt and req_lang != "en":
            transcribe_opts["initial_prompt"] = lyrics_prompt[:250]

        segments, _ = _transcribe_whisper(str(vocals_path), config, **transcribe_opts)

        asr_words: list[dict] = []
        for s in segments:
            for w in (s.words or []):
                w_text = w.word.strip()
                if not w_text:
                    continue
                for token in tokenize_lyric_phonetic(w_text):
                    asr_words.append({**token, 'start': round(w.start, 3), 'end': round(w.end, 3)})

        if asr_words:
            cache_payload = {
                "version": 4,
                "meta": {
                    "mtime": vocals_path.stat().st_mtime,
                    "size": vocals_path.stat().st_size,
                    "language": req_lang,
                    "model": getattr(config, "whisper_model", "base") if config else "large-v3",
                },
                "words": asr_words,
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_payload, f, ensure_ascii=False, indent=2)
            log.info("ASR 锚点提取并缓存完成: %d 个词 (lang=%s)", len(asr_words), req_lang or "auto")
        return asr_words
    except Exception as e:
        log.warning("多语言 ASR 锚点提取失败 (不生成无锚点整曲估算结果): %s", e)
        return []


def _asr_gap_windows(asr_words: list[dict], singing_sections: list, duration: float) -> list[tuple[float, float]]:
    """Internal ASR omissions only: long gaps with substantial detected vocals.

    A short tail of the preceding verse must not pull the retry into an
    instrumental break. Retry the first substantial voiced interval instead.
    """
    ordered = sorted(asr_words, key=lambda w: (w["start"], w["end"]))
    windows = []
    covered_end = ordered[0]["end"] if ordered else 0.0
    for word in ordered[1:]:
        if word["start"] - covered_end >= 8.0:
            voiced = [(max(s, covered_end), min(e, word["start"]))
                      for s, e in singing_sections
                      if min(e, word["start"]) - max(s, covered_end) >= 2.0]
            if sum(e - s for s, e in voiced) >= 5.0:
                start = max(covered_end, voiced[0][0] - 0.4)
                end = min(duration, word["start"] + 4.0, start + 30.0)
                windows.append((round(start, 3), round(end, 3)))
        covered_end = max(covered_end, word["end"])
    return windows[:2]  # Bounded work; no recursive full-song retries.


def _recover_asr_gaps(vocals_path: Path, asr_words: list[dict], singing_sections: list,
                      duration: float, config: AlignerConfig, language: str) -> list[dict]:
    """Retry voiced internal gaps before estimating lyric windows; preserve source text."""
    windows = _asr_gap_windows(asr_words, singing_sections, duration)
    if not windows:
        return asr_words
    st = vocals_path.stat()
    meta = {"version": 2, "mtime": st.st_mtime, "size": st.st_size,
            "model": config.whisper_model, "language": language, "windows": windows,
            "anchors": hashlib.sha256(json.dumps(asr_words, sort_keys=True).encode()).hexdigest()}
    # JSON roundtrip makes tuple/list window representation consistent.
    meta = json.loads(json.dumps(meta))
    cache = vocals_path.parent / f".{vocals_path.stem}_asr_gap_recovery.json"
    if cache.exists():
        try:
            saved = json.loads(cache.read_text())
            if saved.get("meta") == meta and saved.get("words"):
                log.info("复用 ASR 人声缺口局部恢复缓存: %d 个窗口", len(windows))
                return saved["words"]
        except (ValueError, OSError):
            pass

    import tempfile
    wav, sr = sf.read(str(vocals_path), dtype="float32")
    merged = list(asr_words)
    recovered_any = False
    for start, end in windows:
        log.warning("ASR 在有人声区间存在长缺口，局部重识别 %.2f–%.2fs", start, end)
        with tempfile.TemporaryDirectory(prefix="m2v_asr_gap_") as temp:
            clip = Path(temp) / "vocals.wav"
            sf.write(clip, wav[int(start * sr):int(end * sr)], sr)
            local = extract_asr_words(clip, config=config, language=language)
        valid = [w for w in local if 0 <= w["start"] < w["end"] <= end - start + 0.01]
        # Recovery must add meaningful evidence inside the original empty region,
        # rather than just recognizing its already-known trailing words again.
        first_known = min((w["start"] for w in asr_words if w["start"] > start), default=end)
        novel = [w for w in valid if start + w["end"] < first_known - 0.5]
        if len(novel) < 4:
            log.warning("ASR 缺口局部重识别未获得足够新证据，保留原结果待复核")
            continue
        shifted = [{**w, "start": round(start + w["start"], 3),
                    "end": round(start + w["end"], 3)} for w in valid]
        recovered_start = min(w["start"] for w in shifted)
        recovered_end = max(w["end"] for w in shifted)
        # A retry may only recognize part of the crop. Do not erase valid old
        # trailing evidence merely because it was inside that crop.
        merged = [w for w in merged if w["end"] <= recovered_start or w["start"] >= recovered_end] + shifted
        recovered_any = True
    merged.sort(key=lambda w: (w["start"], w["end"]))
    if recovered_any:
        cache.write_text(json.dumps({"meta": meta, "words": merged}, ensure_ascii=False))
    return merged


def find_silence_snap(
    t_ideal: float,
    wav_np: np.ndarray | None,
    sr: int = 16000,
    window: float = 2.5,
    min_t: float = 0.0,
    max_t: float = float("inf"),
) -> float:
    """在给定时间附近寻找能量 (RMS) 极小值点，将段落或乐句边界吸附至声学停顿，避免切在发音中央。"""
    if wav_np is None or len(wav_np) == 0:
        return round(max(min_t, min(max_t, t_ideal)), 2)
    t_min = max(min_t, t_ideal - window)
    t_max = min(max_t, min(len(wav_np) / sr, t_ideal + window))
    if t_max <= t_min:
        return round(max(min_t, min(max_t, t_ideal)), 2)
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
    return round(best_t, 2)


def _unique_phrase_anchors(paras: dict, asr_words: list[dict]) -> dict[int, tuple[float, float]]:
    """Find conservative local evidence; repeated or out-of-order phrases are not anchors.

    Require at least four consecutive phonetic tokens, covering half a line
    (or six tokens), occurring exactly once in both lyrics and ASR. These
    constrain windows, but do not establish the unmatched line's boundaries.
    """
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

    # Choose the largest monotonic evidence chain instead of trusting the first
    # textual match. This also keeps conflicting detections from crossing verses.
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


def anchor_stanzas_with_asr(
    singing_lyrics: list[tuple[int, LyricLine]],
    asr_words: list[dict],
    total_audio_sec: float,
    min_start: float = 0.0,
    wav_np: np.ndarray | None = None,
    sr: int = 16000,
    song_lang: str | None = None,
    start_is_explicit: bool = False,
) -> tuple[dict[int, list[tuple[int, LyricLine]]], dict[int, tuple[float, float]]]:
    """
    匹配证据优先、估算补缺的乐段定位。
    1. 原歌词决定段落、句界与顺序；过滤无效 ASR 时间戳。
    2. 唯一且单调的连续词组匹配约束窗口，段落模糊匹配补充范围。
    3. 重复副歌在相邻锚点之间单调分配，不能仅凭相似文本跨段取用。
    4. 未匹配部分才按词量/静音估算；估算及静音吸附不能截掉已匹配词组。
    局部证据只保护其覆盖区间，不代表整句或整段已准确定位。
    """
    has_explicit = any(ly.paragraph > 0 for _, ly in singing_lyrics)
    paras: dict[int, list[tuple[int, LyricLine]]] = {}
    if has_explicit:
        for i, ly in singing_lyrics:
            p = ly.paragraph
            if p not in paras:
                paras[p] = []
            paras[p].append((i, ly))
    else:
        cur_lang = None
        cur_p = 0
        for i, ly in singing_lyrics:
            l_lang = detect_line_lang(ly.text, song_lang=song_lang)
            if cur_p not in paras:
                paras[cur_p] = []
            if cur_lang is not None and (l_lang != cur_lang or len(paras[cur_p]) >= 4):
                cur_p += 1
                paras[cur_p] = []
            paras[cur_p].append((i, ly))
            cur_lang = l_lang

    valid_asr = []
    prev_key = None
    for w in asr_words:
        dur = w.get("end", 0.0) - w.get("start", 0.0)
        key = (round(w.get("start", 0.0), 2), round(w.get("end", 0.0), 2), w.get("py", ""))
        if dur >= 0.03 and key != prev_key:
            valid_asr.append(w)
            prev_key = key
    K = len(valid_asr)

    p_tokens: dict[int, list[str]] = {}
    for p, lines in paras.items():
        toks = [c["py"] for _, ly in lines for c in tokenize_lyric_phonetic(ly.text)]
        p_tokens[p] = toks

    sig_counts: dict[str, int] = {}
    for p, toks in p_tokens.items():
        sig = "".join(toks)
        sig_counts[sig] = sig_counts.get(sig, 0) + 1

    c_tokens = [w["py"] for w in valid_asr]
    evidence_words = [w for w in valid_asr if w["start"] >= min_start] if start_is_explicit else valid_asr
    phrase_anchors = _unique_phrase_anchors(paras, evidence_words)
    first_p = min(paras, default=0)
    if not start_is_explicit and first_p in phrase_anchors and phrase_anchors[first_p][0] < min_start:
        log.warning("自动开唱点 %.2fs 晚于连续词组证据 %.2fs，采用证据扩展首段窗口",
                    min_start, phrase_anchors[first_p][0])
        min_start = max(0.0, phrase_anchors[first_p][0])
    log.info("连续词组定位证据覆盖 %d/%d 个歌词段（非整段置信度）", len(phrase_anchors), len(paras))

    def constrain_window(p, start, end, lower, upper):
        previous = [e for pp, (_, e) in phrase_anchors.items() if pp < p]
        following = [s for pp, (s, _) in phrase_anchors.items() if pp > p]
        lower = max(lower, max(previous, default=lower))
        upper = min(upper, min(following, default=upper))
        if p in phrase_anchors:
            evidence_s, evidence_e = phrase_anchors[p]
            if evidence_s < lower or evidence_e > upper:
                raise ValueError(f"乐段 {p} 的词组证据与相邻窗口冲突，需要重新定位，不能估算覆盖")
            start, end = min(start, evidence_s), max(end, evidence_e)
        return max(lower, start), min(upper, end)

    candidates = {}
    for p in sorted(paras.keys()):
        l_toks = p_tokens[p]
        n = len(l_toks)
        min_span = max(1, int(n * 0.5))
        max_span = int(n * 1.6) + 4
        best_sc = -1.0
        best_match = None
        for si in range(0, K):
            for ei in range(si + min_span, min(K + 1, si + max_span)):
                matcher = SequenceMatcher(None, l_toks, c_tokens[si:ei])
                sc = matcher.ratio()
                if sc > best_sc:
                    best_sc = sc
                    best_match = (si, ei, matcher.get_matching_blocks())
        if best_match and best_sc > 0:
            si, ei, blocks = best_match
            valid_blocks = [b for b in blocks if b.size > 0]
            if valid_blocks:
                sig_blocks = [b for b in valid_blocks if b.size >= 2] or valid_blocks
                first_b = sig_blocks[0]
                last_b = sig_blocks[-1]
                first_cand_idx = si + first_b.b
                last_cand_idx = si + last_b.b + last_b.size - 1
                missed_head = first_b.a
                missed_tail = len(l_toks) - (last_b.a + last_b.size)
                raw_s = min_start if p == 0 else max(min_start, valid_asr[first_cand_idx]["start"] - missed_head * 0.45)
                raw_e = min(total_audio_sec, valid_asr[last_cand_idx]["end"] + missed_tail * 0.45)
                raw_s, raw_e = constrain_window(p, raw_s, raw_e, min_start, total_audio_sec)
                if raw_e <= raw_s:
                    continue
                sig = "".join(l_toks)
                candidates[p] = {
                    "score": best_sc,
                    "start": raw_s,
                    "end": raw_e,
                    "unique": (sig_counts[sig] == 1),
                    "tok_len": n,
                }

    islands = {}
    for p in sorted(candidates.keys()):
        c = candidates[p]
        if c["unique"] and (c["score"] >= 0.55 or (c["score"] >= 0.45 and c["tok_len"] >= 20)):
            islands[p] = (c["start"], c["end"], c["score"])

    valid_islands = {}
    last_e = min_start
    for p in sorted(islands.keys()):
        s, e, sc = islands[p]
        if s >= last_e - 1.0:
            valid_islands[p] = (min_start if p == 0 else max(min_start, s), e)
            last_e = e

    p_keys = sorted(paras.keys())
    para_bounds = dict(valid_islands)

    gap_groups: list[list[int]] = []
    curr_group: list[int] = []
    for p in p_keys:
        if p not in valid_islands:
            curr_group.append(p)
        else:
            if curr_group:
                gap_groups.append(curr_group)
                curr_group = []
    if curr_group:
        gap_groups.append(curr_group)

    for group in gap_groups:
        first_p = group[0]
        last_p = group[-1]
        prev_e = min_start
        for pp in range(first_p - 1, -1, -1):
            if pp in valid_islands:
                prev_e = valid_islands[pp][1]
                break
        next_s = total_audio_sec
        for pp in range(last_p + 1, max(p_keys) + 1):
            if pp in valid_islands:
                next_s = valid_islands[pp][0]
                break

        cand_indices = [idx for idx, w in enumerate(valid_asr) if prev_e - 1.0 <= w["start"] <= next_s + 1.0]
        group_candidates: dict[int, list[tuple[float, float, float]]] = {}
        for p in group:
            l_toks = p_tokens[p]
            n = len(l_toks)
            min_span = max(1, int(n * 0.5))
            max_span = int(n * 1.6) + 4
            p_matches = []
            if len(cand_indices) >= 3:
                for si_idx in range(len(cand_indices)):
                    for ei_idx in range(si_idx + min_span, min(len(cand_indices) + 1, si_idx + max_span)):
                        si = cand_indices[si_idx]
                        ei = cand_indices[ei_idx - 1] + 1
                        matcher = SequenceMatcher(None, l_toks, c_tokens[si:ei])
                        sc = matcher.ratio()
                        if sc >= 0.40:
                            valid_blocks = [b for b in matcher.get_matching_blocks() if b.size > 0]
                            if valid_blocks:
                                sig_blocks = [b for b in valid_blocks if b.size >= 2] or valid_blocks
                                first_b = sig_blocks[0]
                                last_b = sig_blocks[-1]
                                first_cand_idx = si + first_b.b
                                last_cand_idx = si + last_b.b + last_b.size - 1
                                missed_head = first_b.a
                                missed_tail = len(l_toks) - (last_b.a + last_b.size)
                                raw_s = max(prev_e, valid_asr[first_cand_idx]["start"] - missed_head * 0.45)
                                raw_e = min(next_s, valid_asr[last_cand_idx]["end"] + missed_tail * 0.45)
                                raw_s, raw_e = constrain_window(p, raw_s, raw_e, prev_e, next_s)
                                if raw_e > raw_s:
                                    p_matches.append((raw_s, raw_e, sc))

            # 对重叠候选进行局部聚类，保留独立的时序候选段
            p_matches.sort(key=lambda m: (m[0], -m[2]))
            distinct: list[tuple[float, float, float]] = []
            for m in p_matches:
                s, e, sc = m
                merged = False
                for d_idx, (ds, de, dsc) in enumerate(distinct):
                    overlap = max(0.0, min(e, de) - max(s, ds))
                    if overlap > 0.5 * min(e - s, de - ds):
                        if sc > dsc:
                            distinct[d_idx] = (s, e, sc)
                        merged = True
                        break
                if not merged:
                    distinct.append((s, e, sc))
            distinct.sort(key=lambda x: x[0])
            group_candidates[p] = distinct

        # 动态规划求解全局时间单调唯一分配 (严格保证前句结束时间 <= 后句开始时间，杜绝重复副歌挤占同一区间)
        group_anchored: dict[int, tuple[float, float, float]] = {}
        m_len = len(group)
        memo: dict = {}

        def _dp(idx: int, last_end_t: float) -> tuple[float, list[tuple[int, tuple[float, float, float] | None]]]:
            key = (idx, round(last_end_t, 2))
            if key in memo:
                return memo[key]
            if idx == m_len:
                return (0.0, [])
            p_cur = group[idx]
            cands = group_candidates.get(p_cur, [])
            best_sc, best_choices = _dp(idx + 1, last_end_t)
            best_res = (best_sc, [(p_cur, None)] + best_choices)
            for c in cands:
                c_s, c_e, c_sc = c
                if c_s >= last_end_t - 0.5:
                    future_sc, future_choices = _dp(idx + 1, c_e)
                    tot_sc = c_sc + future_sc
                    if tot_sc > best_res[0]:
                        best_res = (tot_sc, [(p_cur, c)] + future_choices)
            memo[key] = best_res
            return best_res

        _, choices = _dp(0, prev_e)
        for p_chosen, c_chosen in choices:
            if c_chosen is not None:
                group_anchored[p_chosen] = c_chosen

        cur_anchor_t = prev_e
        i = 0
        while i < len(group):
            p = group[i]
            if p in group_anchored:
                para_bounds[p] = (group_anchored[p][0], group_anchored[p][1])
                cur_anchor_t = group_anchored[p][1]
                i += 1
            else:
                unanchored_sub = [p]
                j = i + 1
                while j < len(group) and group[j] not in group_anchored:
                    unanchored_sub.append(group[j])
                    j += 1
                next_anchor_t = group_anchored[group[j]][0] if j < len(group) else next_s
                sub_gap_dur = max(1.0, next_anchor_t - cur_anchor_t)
                sub_lens = [max(1, len(p_tokens[gp])) for gp in unanchored_sub]
                tot_l = sum(sub_lens)
                sub_cur = cur_anchor_t
                for gp_idx, (gp, sl) in enumerate(zip(unanchored_sub, sub_lens)):
                    p_dur = sub_gap_dur * (sl / tot_l)
                    # 避免在全曲尾声处因缺少锚点将伴奏尾奏/空白长区间全部摊入歌词
                    if next_anchor_t >= total_audio_sec - 1.0:
                        max_expected_dur = max(6.0, len(paras.get(gp, [])) * 4.5)
                        p_dur = min(p_dur, max_expected_dur)
                    raw_end = sub_cur + p_dur
                    if gp_idx < len(unanchored_sub) - 1:
                        snapped_end = find_silence_snap(raw_end, wav_np, sr, 2.5, min_t=sub_cur + 1.0)
                    else:
                        if next_anchor_t < total_audio_sec - 1.0:
                            snapped_end = find_silence_snap(next_anchor_t - 2.5, wav_np, sr, 2.0, min_t=sub_cur + 1.0)
                        else:
                            snapped_end = find_silence_snap(raw_end, wav_np, sr, 3.0, min_t=sub_cur + 1.0, max_t=total_audio_sec)
                    protected_start, protected_end = constrain_window(gp, sub_cur, snapped_end, cur_anchor_t, next_anchor_t)
                    if protected_end <= protected_start:
                        raise ValueError(f"乐段 {gp} 缺少可用的顺序窗口，需要重新定位，不能均匀挤入空区间")
                    log.warning("乐段 %d 整段匹配不足，采用词组证据约束的估算窗口: [%.2fs - %.2fs]（词组证据=%s）",
                                gp, protected_start, protected_end, gp in phrase_anchors)
                    para_bounds[gp] = (round(protected_start, 3), round(protected_end, 3))
                    sub_cur = protected_end
                cur_anchor_t = next_anchor_t
                i = j

    for pi in range(len(p_keys) - 1):
        p_curr = p_keys[pi]
        p_next = p_keys[pi + 1]
        e_curr = para_bounds[p_curr][1]
        s_next = para_bounds[p_next][0]
        gap = s_next - e_curr
        if 1.5 <= gap <= 4.0:
            mid = (e_curr + s_next) / 2
            snap_mid = find_silence_snap(mid, wav_np, sr, window=gap / 2, min_t=e_curr, max_t=s_next)
            snap_mid = max(e_curr, min(s_next, snap_mid))
            para_bounds[p_curr] = (para_bounds[p_curr][0], snap_mid)
            para_bounds[p_next] = (snap_mid, para_bounds[p_next][1])

    return paras, para_bounds


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

    # 4. 全曲主语言先验判定与歌词按语言分流
    singing_lyrics: list[tuple[int, LyricLine]] = [(idx, ly) for idx, ly in enumerate(lyrics) if not ly.is_annotation]
    forced_lang = config.language if (config and config.language and config.language != "auto") else None
    song_lang = forced_lang or detect_song_language([ly for _, ly in singing_lyrics])
    log.info("全曲主语言先验判定: %s (配置指定: %s)", song_lang, forced_lang)

    lang_runs: list[tuple[str, list[tuple[int, LyricLine]]]] = []
    cur_run: list[tuple[int, LyricLine]] = []
    cur_lang = None
    for item in singing_lyrics:
        idx, ly = item
        lang = detect_line_lang(ly.text, song_lang=song_lang)
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
            for orig_idx, ly in lines_with_idx:
                words = _fallback_even_split(ly.text, s_sec, e_sec)
                aligned_line_map[orig_idx] = AlignedLine(text=ly.text, start=s_sec, end=e_sec, words=words)
            return

        with torch.inference_mode():
            emissions = torch.cat([model_en(chunk)[0].log_softmax(dim=-1)
                                   for chunk in wav_slice.split(20 * 16000, dim=1)
                                   if chunk.size(1) >= 400], dim=1)

        # 构建显式 token-to-target 跨度映射，杜绝标点/撇号造成的索引漂移
        full_target_ids: list[int] = []
        full_tokens_with_spans = []  # [(orig_idx, ly, [(tok, s_pos, e_pos)])]
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
                aligned_line_map[orig_idx] = AlignedLine(text=ly.text, start=s_sec, end=e_sec, words=words)
            return

        targets = torch.tensor([full_target_ids], dtype=torch.int32)
        try:
            aligned_tokens, scores = forced_align(emissions, targets, blank=0)
            spans = merge_tokens(aligned_tokens[0], scores[0], blank=0)
        except Exception as e:
            log.warning("英文 CTC 对齐异常，回退均匀切分: %s", e)
            for orig_idx, ly in lines_with_idx:
                words = _fallback_even_split(ly.text, s_sec, e_sec)
                aligned_line_map[orig_idx] = AlignedLine(text=ly.text, start=s_sec, end=e_sec, words=words)
            return

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
                words.append(WordTimestamp(word=tok, start=round(w_s, 3), end=round(max(w_e, w_s + 0.05), 3)))

            # 校验发音词是否发生不合理坍缩 (忽略纯标点)
            vocal_words = [w for w in words if re.search(r"[\w\u4e00-\u9fff]", w.word)]
            if any((w.end - w.start) <= 0.035 for w in vocal_words):
                words = _fallback_even_split(ly.text, s_sec, e_sec)

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
            for orig_idx, ly in lines_with_idx:
                words = _fallback_even_split(ly.text, s_sec, e_sec)
                aligned_line_map[orig_idx] = AlignedLine(text=ly.text, start=s_sec, end=e_sec, words=words)
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
        target_ids = [tid for tid in target_ids if tid is not None and tid != blank_zh]
        if not target_ids:
            for orig_idx, ly in lines_with_idx:
                words = _fallback_even_split(ly.text, s_sec, e_sec)
                aligned_line_map[orig_idx] = AlignedLine(text=ly.text, start=s_sec, end=e_sec, words=words)
            return

        targets = torch.tensor([target_ids], dtype=torch.int32)
        try:
            aligned_tokens, scores = forced_align(emissions, targets, blank=blank_zh)
            spans = merge_tokens(aligned_tokens[0], scores[0], blank=blank_zh)
        except Exception as e:
            log.warning("中文 CTC 对齐异常，回退均匀切分: %s", e)
            for orig_idx, ly in lines_with_idx:
                words = _fallback_even_split(ly.text, s_sec, e_sec)
                aligned_line_map[orig_idx] = AlignedLine(text=ly.text, start=s_sec, end=e_sec, words=words)
            return
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

            # 校验发音字是否发生不合理坍缩 (忽略纯标点)
            vocal_words = [w for w in words if re.search(r"[\w\u4e00-\u9fff]", w.word)]
            if any((w.end - w.start) <= 0.035 for w in vocal_words):
                words = _fallback_even_split(ly.text, s_sec, e_sec)

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
                # 局部切片同样在 CUDA 失败时完整重试 CPU。
                segments, _ = _transcribe_whisper(tmp_path, config, word_timestamps=True)
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

    # 6. 多语言语义 ASR 粗定位与可信乐段/句级音频窗口建立 (Semantic ASR Anchoring & Monotonic Matching)
    # 步骤 A: 提取全曲 ASR 词级时间戳锚点 (单曲一次，缓存复用)
    prompt_text = "\n".join(ly.text for _, ly in singing_lyrics)
    asr_words = extract_asr_words(vocals_path, lyrics_prompt=prompt_text, config=config, language=song_lang)
    asr_words = _recover_asr_gaps(vocals_path, asr_words, singing_sections, total_audio_sec, config, song_lang)
    _validate_asr_evidence(asr_words, len(singing_lyrics), singing_sections)
    wav_np = wav_16k.squeeze(0).cpu().numpy()

    # 步骤 B: 两阶段岛驱动宏观乐段定位与声学停顿吸附
    paras, para_bounds = anchor_stanzas_with_asr(
        singing_lyrics=singing_lyrics,
        asr_words=asr_words,
        total_audio_sec=total_audio_sec,
        min_start=min_start,
        wav_np=wav_np,
        sr=16000,
        song_lang=song_lang,
        start_is_explicit=config.lyrics_start_time > 0,
    )
    log.info("乐段窗口定位完成: %d 个自然段（含估算窗口，不能视为全部高置信度）", len(para_bounds))

    # 步骤 C: 逐段执行独立中/英文 CTC 精确打点 (同语言整段联合 Viterbi 解码，混语言声学停顿切分)
    for p in sorted(paras.keys()):
        p_s, p_e = para_bounds[p]
        p_lines = paras[p]
        langs = [detect_line_lang(ly.text, song_lang=song_lang) for _, ly in p_lines]
        if all(l == "en" for l in langs):
            _dispatch_align("en", p_lines, p_s, p_e)
        elif all(l == "zh" for l in langs):
            _dispatch_align("zh", p_lines, p_s, p_e)
        else:
            # 混语言段落：拆分为连续同语言 sub_runs，由 ASR 锚点或发音单元比例吸附声学停顿切分
            runs: list[tuple[str, list[tuple[int, LyricLine]]]] = []
            cur_r: list[tuple[int, LyricLine]] = []
            cur_l = None
            for idx_ly in p_lines:
                ll = detect_line_lang(idx_ly[1].text, song_lang=song_lang)
                if cur_l is None or ll == cur_l:
                    cur_r.append(idx_ly)
                    cur_l = ll
                else:
                    runs.append((cur_l, cur_r))
                    cur_r = [idx_ly]
                    cur_l = ll
            if cur_r:
                runs.append((cur_l, cur_r))

            sub_dur = p_e - p_s
            run_tok_counts = [sum(len(tokenize_lyric_phonetic(ly.text)) for _, ly in r_lines) for _, r_lines in runs]
            tot_toks = max(1, sum(run_tok_counts))
            c_s = p_s
            for r_idx, (r_lang, r_lines) in enumerate(runs):
                if r_idx == len(runs) - 1:
                    c_e = p_e
                else:
                    r_toks = run_tok_counts[r_idx]
                    ideal_split = c_s + sub_dur * (r_toks / tot_toks)
                    next_run_lines = runs[r_idx + 1][1]
                    next_run_toks = [c["py"] for _, ly in next_run_lines for c in tokenize_lyric_phonetic(ly.text)]
                    cand_in_p = [w for w in asr_words if c_s - 0.5 <= w["start"] <= p_e + 0.5]
                    found_next_s = None
                    if len(cand_in_p) >= len(next_run_toks):
                        c_in_toks = [w["py"] for w in cand_in_p]
                        m = SequenceMatcher(None, next_run_toks, c_in_toks)
                        if m.ratio() >= 0.40:
                            vbs = [b for b in m.get_matching_blocks() if b.size > 0]
                            if vbs:
                                found_next_s = cand_in_p[vbs[0].b]["start"]
                    target_split = found_next_s if found_next_s else ideal_split
                    min_run_dur = max(0.8, r_toks * 0.30)
                    c_e = find_silence_snap(target_split, wav_np, 16000, 2.0, min_t=c_s + min_run_dur)
                _dispatch_align(r_lang, r_lines, c_s, c_e)
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

    lang = config.language if config.language and config.language != "auto" else None
    segments, info = _transcribe_whisper(str(vocals_path), config, language=lang, beam_size=5, word_timestamps=True)

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

                # 自愈有效性仲裁: 必须真正改善了异常行的坍缩，且严格受限于前后邻句边界，不能因盲目拉长时间就判定成功
                anom_improved = any(
                    (repaired[it_idx].end - repaired[it_idx].start) > max(0.8, (target_items[it_idx][1].end - target_items[it_idx][1].start) * 1.5)
                    for it_idx in range(len(target_items))
                    if (target_items[it_idx][1].end - target_items[it_idx][1].start) < 0.6
                )
                # 严格边界保护: 自愈区间不得越过邻句划定的安全范围
                strictly_bounded = (repaired[0].start >= rough_start - 0.05 and repaired[-1].end <= rough_end + 0.05)

                if not alignment_quality_issue(repaired) and strictly_bounded and anom_improved:
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
                else:
                    # 自愈未通过严格校验时，保留由前后邻句约束的安全边界，并打上 needs_review 标记
                    log.warning(
                        "⚠️ [局部自愈未通过严格校验] 第 %d~%d 行保留原安全边界，标记为待人工复核",
                        target_items[0][0] + 1,
                        target_items[-1][0] + 1,
                    )
                    for item_idx in range(len(target_items)):
                        orig_idx = target_items[item_idx][0]
                        cur_overrides = dict(getattr(aligned_lines[orig_idx], "style_overrides", {}) or {})
                        cur_overrides["needs_review"] = True
                        aligned_lines[orig_idx].style_overrides = cur_overrides
        except Exception as e:
            log.warning("局部自愈执行异常 (已自动保留原对齐): %s", e)

    return aligned_lines
