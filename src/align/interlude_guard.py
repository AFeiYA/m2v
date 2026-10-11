"""
Interlude Guard & Bounded Alignment Module (Phase 2).
Protects instrumental interludes, guitar solos, and outros from lyric intrusion
by partitioning audio and lyrics around detected acoustic gaps before fine-grained Whisper alignment.
Works seamlessly on both segmented and unsegmented lyrics.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import soundfile as sf
import torch
import torchaudio

from src.storyboard_schema import AlignedLine, AlignmentResult, WordTimestamp

if TYPE_CHECKING:
    from src.preprocessor import LyricLine

log = logging.getLogger("m2v.interlude_guard")

_CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


def detect_macro_interludes(
    wav: np.ndarray,
    sr: int = 16000,
    min_gap_sec: float = 4.5,
    energy_thresh: float = 0.015,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """通过声学 RMS 能量扫描与 VAD，检测音频中持续时间 >= min_gap_sec 的纯器乐/长间奏区间。

    Returns:
        interludes: [(gap_start, gap_end), ...] 纯器乐长间奏列表
        voice_clusters: [(cluster_start, cluster_end), ...] 有效人声簇列表
    """
    hop = int(sr * 0.1)  # 100ms 窗口
    if len(wav) <= hop:
        return [], []

    rms_vals = [
        float(np.sqrt(np.mean(wav[i : i + hop] ** 2)))
        for i in range(0, len(wav) - hop, hop)
    ]
    times = [i / sr for i in range(0, len(wav) - hop, hop)]
    is_voiced = [r > energy_thresh for r in rms_vals]

    # 1. 提取连续有声微块
    blocks: list[tuple[float, float]] = []
    in_voice = False
    start_t = 0.0
    for i, v in enumerate(is_voiced):
        t = times[i]
        if v and not in_voice:
            in_voice = True
            start_t = t
        elif not v and in_voice:
            in_voice = False
            if t - start_t >= 0.4:
                blocks.append((round(start_t, 2), round(t, 2)))
    if in_voice:
        blocks.append((round(start_t, 2), round(times[-1], 2)))

    if not blocks:
        return [], []

    # 2. 合并句间正常呼吸与微短停顿 (< 2.8s)
    clusters: list[tuple[float, float]] = []
    for b in blocks:
        if not clusters:
            clusters.append(b)
        else:
            prev_s, prev_e = clusters[-1]
            if b[0] - prev_e < 2.8:
                clusters[-1] = (prev_s, b[1])
            else:
                clusters.append(b)

    # 3. 识别簇间大间奏 (>= min_gap_sec)
    interludes: list[tuple[float, float]] = []
    for i in range(len(clusters) - 1):
        gap_s = clusters[i][1]
        gap_e = clusters[i + 1][0]
        gap_dur = gap_e - gap_s
        if gap_dur >= min_gap_sec:
            interludes.append((round(gap_s, 2), round(gap_e, 2)))

    return interludes, clusters


def partition_lyrics_by_interludes(
    lyrics: list[LyricLine],
    interludes: list[tuple[float, float]],
    rough_starts: list[float],
    total_audio_sec: float,
) -> list[dict[str, Any]]:
    """根据粗对齐时间戳与宏观间奏区间，将歌词及对应时间窗口划分到互不侵占的安全物理窗口中。"""
    if not interludes or not lyrics or len(rough_starts) != len(lyrics):
        return [
            {
                "lyrics": lyrics,
                "window_start": 0.0,
                "window_end": total_audio_sec,
            }
        ]

    split_indices: list[int] = []
    for gap_s, gap_e in interludes:
        # 寻找首个落在间奏内或间奏后的歌词行索引
        chosen_split = len(lyrics)
        for idx, st in enumerate(rough_starts):
            if st >= gap_s - 0.2:
                chosen_split = idx
                break
        split_indices.append(chosen_split)

    # 构建安全分区
    partitions: list[dict[str, Any]] = []
    prev_idx = 0
    prev_t = 0.0
    for i, s_idx in enumerate(split_indices):
        gap_s, gap_e = interludes[i]
        part_lyrics = lyrics[prev_idx:s_idx]
        if part_lyrics:
            partitions.append(
                {
                    "lyrics": part_lyrics,
                    "window_start": prev_t,
                    "window_end": gap_s,
                }
            )
        prev_idx = s_idx
        prev_t = gap_e

    # 最后一段
    tail_lyrics = lyrics[prev_idx:]
    if tail_lyrics:
        partitions.append(
            {
                "lyrics": tail_lyrics,
                "window_start": prev_t,
                "window_end": total_audio_sec,
            }
        )

    return partitions


def _single_pass_align(
    model: Any,
    wav_16k: np.ndarray,
    lyrics: list[LyricLine],
    full_text: str,
    language: str,
    nonspeech_skip: float | None = None,
) -> AlignmentResult:
    """对整曲执行单次直接声学微观对齐。"""
    from src.align.cjk_disambiguation import reconcile_aligned_words

    align_opts: dict[str, Any] = {"language": language, "original_split": True}
    if nonspeech_skip is not None:
        align_opts["nonspeech_skip"] = nonspeech_skip
    else:
        align_opts["nonspeech_skip"] = None

    whisper_res = model.align(wav_16k, full_text, **align_opts)
    segments = whisper_res.segments if whisper_res is not None else []
    aligned_lines: list[AlignedLine] = []
    for idx, ly in enumerate(lyrics):
        sec = getattr(ly, "section", "")
        if not sec and getattr(ly, "paragraph", 0):
            sec = f"Paragraph {ly.paragraph}"
        if idx < len(segments):
            seg = segments[idx]
            raw_words = [
                WordTimestamp(
                    word=str(w.word),
                    start=max(0.0, round(float(w.start), 3)),
                    end=max(round(float(w.start), 3), round(float(w.end), 3)),
                )
                for w in seg.words
            ]
            if not raw_words:
                raw_words = [WordTimestamp(word=ly.text, start=round(float(seg.start), 3), end=round(float(seg.end), 3))]

            # 运行字词消歧与声学下凹校验层
            words = reconcile_aligned_words(
                target_text=ly.text,
                whisper_words=raw_words,
                wav_16k=wav_16k,
                sr=16000,
                clip_offset=0.0,
            )
            l_start = words[0].start
            l_end = max(l_start, words[-1].end)
            aligned_lines.append(AlignedLine(text=ly.text, start=l_start, end=l_end, words=words, section=sec))
        else:
            prev_e = aligned_lines[-1].end if aligned_lines else 0.0
            aligned_lines.append(
                AlignedLine(text=ly.text, start=prev_e, end=prev_e + 1.0, words=[WordTimestamp(word=ly.text, start=prev_e, end=prev_e + 1.0)], section=sec)
            )
    return AlignmentResult(lines=aligned_lines)


def align_with_interlude_guard(
    vocals_path: Path | str,
    lyrics: list[LyricLine],
    model: Any,
    language: str | None = None,
    min_gap_sec: float = 4.5,
    buffer_sec: float = 0.5,
    nonspeech_skip: float | None = None,
) -> AlignmentResult:
    """带宏观间奏硬保护的 stable-ts 混合对齐执行器。

    执行流程:
    1. 扫描音频人声能量，提取 >= min_gap_sec 的长器乐 Solo / 间奏；
    2. 若不存在大间奏，直接单次全局对齐并返回；
    3. 若存在大间奏，执行一次轻量快速粗测确定歌词划分点，将歌词与音频切分为 N 个安全簇；
    4. 对每个安全簇独立调用 stable-ts 对齐，并在时间轴上精准偏移复位；
    5. 杜绝任何歌词侵占器乐 Solo。若分簇遇第三方库异常，安全回退单次全局对齐。
    """
    vocals_path = Path(vocals_path)
    wav, sr = sf.read(str(vocals_path), dtype="float32", always_2d=False)
    if wav.ndim > 1:
        wav = wav.mean(axis=1)

    wav_t = torch.from_numpy(wav).unsqueeze(0)
    wav_16k = torchaudio.functional.resample(wav_t, orig_freq=sr, new_freq=16000).squeeze(0).numpy()
    total_audio_sec = len(wav_16k) / 16000.0

    interludes, _clusters = detect_macro_interludes(wav_16k, sr=16000, min_gap_sec=min_gap_sec)

    from src.align.cjk_disambiguation import prepare_line_for_alignment, reconcile_aligned_words

    full_text = "\n".join(prepare_line_for_alignment(ly.text) for ly in lyrics)
    has_zh = bool(_CHINESE_CHAR_RE.search(full_text))
    norm_lang = None if (not language or language in ("mixed", "auto")) else language
    default_lang = norm_lang or ("zh" if has_zh else "en")

    if not interludes:
        log.info("未检测到 >= %.1fs 的大间奏/Solo，走单次全局微观对齐", min_gap_sec)
        return _single_pass_align(model, wav_16k, lyrics, full_text, default_lang, nonspeech_skip=nonspeech_skip)

    log.info("🛡️ [间奏硬保护] 检测到 %d 个长间奏/器乐Solo: %s", len(interludes), interludes)

    try:
        # 粗测第一遍获取大致行分布 (显式禁用底层静音片段切碎，防止子块回滚引发张量维度异常)
        rough_align_opts: dict[str, Any] = {"language": default_lang, "original_split": True, "nonspeech_skip": nonspeech_skip}
        rough_res = model.align(wav_16k, full_text, **rough_align_opts)
        rough_starts = [float(s.start) for s in (rough_res.segments if rough_res is not None else [])]
        while len(rough_starts) < len(lyrics):
            rough_starts.append(total_audio_sec)

        partitions = partition_lyrics_by_interludes(lyrics, interludes, rough_starts, total_audio_sec)
        log.info("🛡️ [间奏硬保护] 歌词与音频切分为 %d 个独立安全簇:", len(partitions))
        for p_i, p in enumerate(partitions):
            log.info("  簇 %d: [%.2fs ~ %.2fs] (%d 行歌词)", p_i + 1, p["window_start"], p["window_end"], len(p["lyrics"]))

        # 独立运行每个簇
        all_aligned_lines: list[AlignedLine] = []
        for p in partitions:
            p_lyrics = p["lyrics"]
            if not p_lyrics:
                continue
            p_s = max(0.0, p["window_start"] - buffer_sec)
            p_e = min(total_audio_sec, p["window_end"] + buffer_sec)
            s_sample = int(p_s * 16000)
            e_sample = int(p_e * 16000)
            clip = wav_16k[s_sample:e_sample]
            clip_offset = s_sample / 16000.0

            p_text = "\n".join(prepare_line_for_alignment(ly.text) for ly in p_lyrics)
            p_has_zh = bool(_CHINESE_CHAR_RE.search(p_text))
            p_lang = "zh" if p_has_zh else "en"

            cluster_opts: dict[str, Any] = {"language": p_lang, "original_split": True, "nonspeech_skip": nonspeech_skip}
            p_res = model.align(clip, p_text, **cluster_opts)
            p_segs = p_res.segments if p_res is not None else []

            for idx, ly in enumerate(p_lyrics):
                sec = getattr(ly, "section", "")
                if not sec and getattr(ly, "paragraph", 0):
                    sec = f"Paragraph {ly.paragraph}"

                if idx < len(p_segs):
                    seg = p_segs[idx]
                    raw_words: list[WordTimestamp] = []
                    for w in seg.words:
                        w_s = max(0.0, round(clip_offset + float(w.start), 3))
                        w_e = max(w_s, round(clip_offset + float(w.end), 3))
                        raw_words.append(WordTimestamp(word=str(w.word), start=w_s, end=w_e))
                    if not raw_words:
                        s_s = max(0.0, round(clip_offset + float(seg.start), 3))
                        s_e = max(s_s, round(clip_offset + float(seg.end), 3))
                        raw_words = [WordTimestamp(word=ly.text, start=s_s, end=s_e)]

                    # 字词消歧与声学下凹校验层
                    words = reconcile_aligned_words(
                        target_text=ly.text,
                        whisper_words=raw_words,
                        wav_16k=clip,
                        sr=16000,
                        clip_offset=clip_offset,
                    )

                    l_start = words[0].start
                    l_end = max(l_start, words[-1].end)
                    all_aligned_lines.append(AlignedLine(text=ly.text, start=l_start, end=l_end, words=words, section=sec))
                else:
                    prev_e = all_aligned_lines[-1].end if all_aligned_lines else clip_offset
                    all_aligned_lines.append(
                        AlignedLine(
                            text=ly.text,
                            start=prev_e,
                            end=prev_e + 1.0,
                            words=[WordTimestamp(word=ly.text, start=prev_e, end=prev_e + 1.0)],
                            section=sec,
                        )
                    )

        return AlignmentResult(lines=all_aligned_lines)
    except Exception as exc:
        log.warning("🛡️ [间奏硬保护] 分簇对齐受阻 (%s)，安全回退至单次全局微观对齐...", exc)
        return _single_pass_align(model, wav_16k, lyrics, full_text, default_lang, nonspeech_skip=nonspeech_skip)
