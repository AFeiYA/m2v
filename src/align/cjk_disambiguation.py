"""
CJK (中文/日韩) 逐字对齐转换与声学下凹消歧层
--------------------------------------------------
解决 Whisper BPE 分词器将多字词（如 "世界" -> Token 24486, "这里" -> Token 38927）
合并为一个时间单元，导致前端无法逐字排版与编辑的根本问题。

核心原则：
1. 规则明确：中文/CJK 统一提供逐字编辑单位，英文/西文保留整词单位。
2. 拒绝伪精准：不机械平分时长；先通过事前 CJK 词素展开引导 Whisper 给出字级注意力；
   若仍有残留多字词，先分析短时声学能量下凹 (Acoustic Dip)；
   若无明显声学边界（连音/滑音），标记为 needs_review=True，交由创作者在 UI 中一键精准切分。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple
import numpy as np

from src.storyboard_schema import WordTimestamp
from src.utils import log

_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff]")
_WORD_OR_CJK_RE = re.compile(r"([a-zA-Z0-9_\'\-]+|[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff])")
_PUNCT_RE = re.compile(r"^[^\w\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff]+|[^\w\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff]+$")


def parse_target_units(text: str) -> list[str]:
    """将歌词行分解为排版与编辑器所期望的标准字/词单元。

    - CJK 汉字/假名拆为单字
    - 英文/数字连续词块保持为一个完整单词
    - 忽略空格与纯标点符号
    """
    return [m.group(1) for m in _WORD_OR_CJK_RE.finditer(text)]


def prepare_line_for_alignment(text: str) -> str:
    """对单行歌词进行事前 Token 展开，以便送入 Whisper/stable-ts 对齐。

    CJK 单字之间插入空格，使 BPE 分词器强制将其分词为单个字符 Token；
    西文单词保持完整，避免被截断成音节碎片。
    """
    units = parse_target_units(text)
    if not units:
        return text.strip()
    return " ".join(units)


def clean_token(token: str) -> str:
    """清理 Whisper 产生的首尾空格及偶发附带的标点符号。"""
    t = token.strip()
    cleaned = _PUNCT_RE.sub("", t)
    return cleaned if cleaned else t


def find_acoustic_split_points(
    wav_16k: np.ndarray,
    sr: int,
    start_s: float,
    end_s: float,
    num_splits: int,
) -> tuple[list[float], bool]:
    """在指定时间区间内，基于短时 RMS 能量谷底寻找声学切分点。

    Args:
        wav_16k: 16kHz 单声道音频信号
        sr: 采样率 (默认 16000)
        start_s: 起始绝对时间 (秒)
        end_s: 结束绝对时间 (秒)
        num_splits: 需要寻找的内部切分点数量 (字符数 - 1)

    Returns:
        (splits, is_confident): 切分时间戳列表 (秒) 及置信度布尔值
    """
    dur = end_s - start_s
    if dur <= 0.12 or num_splits <= 0:
        step = dur / (num_splits + 1)
        return [round(start_s + (i + 1) * step, 3) for i in range(num_splits)], False

    s_idx = max(0, int(start_s * sr))
    e_idx = min(len(wav_16k), int(end_s * sr))
    clip = wav_16k[s_idx:e_idx]
    if len(clip) < int(sr * 0.05):
        step = dur / (num_splits + 1)
        return [round(start_s + (i + 1) * step, 3) for i in range(num_splits)], False

    try:
        import librosa

        hop = int(sr * 0.005)  # 5ms 步长
        win = int(sr * 0.020)  # 20ms 窗口
        rms = librosa.feature.rms(y=clip, frame_length=win, hop_length=hop)[0]
        times = start_s + np.arange(len(rms)) * 0.005
        mean_val = float(np.mean(rms)) if len(rms) > 0 else 1.0
    except Exception as e:
        log.warning("声学能量计算失败 (%s)，回退至等分待复核", e)
        step = dur / (num_splits + 1)
        return [round(start_s + (i + 1) * step, 3) for i in range(num_splits)], False

    splits: list[float] = []
    all_confident = True
    ideal_step = dur / (num_splits + 1)

    for i in range(num_splits):
        expected_t = start_s + (i + 1) * ideal_step
        # 在理论边界左右 40% 的合理窗口内寻找局部能量谷底
        w_min = max(start_s + 0.04, expected_t - 0.40 * ideal_step)
        w_max = min(end_s - 0.04, expected_t + 0.40 * ideal_step)
        valid_mask = (times >= w_min) & (times <= w_max)
        if not np.any(valid_mask):
            splits.append(round(expected_t, 3))
            all_confident = False
            continue

        v_rms = rms[valid_mask]
        v_times = times[valid_mask]
        min_idx = int(np.argmin(v_rms))
        min_val = float(v_rms[min_idx])
        best_t = float(v_times[min_idx])

        # 如果谷底能量明显低于平均发音能量 (跌幅超过 35%)，视为可靠辅音起唱或气口转换点
        conf = (min_val < 0.65 * mean_val)
        if not conf:
            all_confident = False
        splits.append(round(best_t, 3))

    splits.sort()
    return splits, all_confident


def trim_intra_line_silence_gaps(
    words: list[WordTimestamp],
    wav_16k: Optional[np.ndarray],
    sr: int = 16000,
    clip_offset: float = 0.0,
    min_gap_sec: float = 0.15,
) -> list[WordTimestamp]:
    """探测并修剪句内连续重复词或长字之间的静音气口（如'失重 失重 失重'）。

    Whisper 贪婪注意力常将词间 0.5s~1.5s 的伴奏空白/换气气口错误挂在后一个词的 start 前端，
    导致后一个词被异常拉长并在静音区提前亮起。
    本算法自字词 end 处逆向扫描 RMS 能量，精确寻找发音起唱点，释放词间静音气口。
    """
    if not words or wav_16k is None or len(words) < 2:
        return words

    try:
        import librosa

        hop = int(sr * 0.005)  # 5ms 步长
        win = int(sr * 0.020)  # 20ms 窗口
        rms = librosa.feature.rms(y=wav_16k, frame_length=win, hop_length=hop)[0]
        times = clip_offset + np.arange(len(rms)) * 0.005

        active_rms = rms[rms > 0.015]
        if len(active_rms) == 0:
            return words
        thr = float(np.percentile(active_rms, 25)) * 0.6

        # 计算当前行中位字长，慢歌门槛自动宽容，快歌自动敏锐
        line_durs = [w.end - w.start for w in words]
        med_dur = float(np.median(line_durs)) if line_durs else 0.25

        for i in range(len(words)):
            w = words[i]
            dur = w.end - w.start
            # 动态门槛：首词使用 max(0.35s, med_dur) 拦截乐句开头静音吞噬；
            # 句内汉字为 max(0.40s, 1.6 * 中位字长)；句内西文为 max(0.70s, 2.0 * 中位字长)
            if i == 0:
                char_thr = max(0.35, med_dur)
            else:
                is_cjk = any("\u4e00" <= c <= "\u9fff" for c in w.word)
                char_thr = max(0.40, 1.6 * med_dur) if is_cjk else max(0.70, 2.0 * med_dur)
            if dur < char_thr:
                continue

            mask = (times >= w.start) & (times <= w.end)
            t_clip = times[mask]
            r_clip = rms[mask]
            if len(r_clip) < 20:
                continue

            # 从词尾逆向往前扫描
            idx = len(r_clip) - 1
            while idx >= 0 and r_clip[idx] < thr:
                idx -= 1
            if idx < 0:
                continue

            silence_count = 0
            onset_idx = idx
            while idx >= 0:
                if r_clip[idx] < thr:
                    silence_count += 1
                    if silence_count >= 16:  # 持续 80ms 低能量视为静音断层
                        break
                else:
                    silence_count = 0
                    onset_idx = idx
                idx -= 1

            true_onset = float(t_clip[onset_idx])
            # 若真实起唱点明显晚于当前 start，则修正起唱点
            if true_onset - w.start >= min_gap_sec:
                w.start = round(true_onset, 3)

    except Exception as e:
        log.warning("句内气口探测失败: %s", e)

    return words


def reconcile_aligned_words(
    target_text: str,
    whisper_words: list[WordTimestamp],
    wav_16k: Optional[np.ndarray] = None,
    sr: int = 16000,
    clip_offset: float = 0.0,
) -> list[WordTimestamp]:
    """将 Whisper 输出的字/词时间戳与目标歌词行的字词单元严格对齐。

    功能：
    1. 还原西文复合单词（Whisper 将 `riverside` 拆为 `rivers` 和 `ide` 时自动合并恢复，并保留起止区间）；
    2. 拆解中文多字词（Whisper 将 `世界` 合并为单个 token 时，利用声学谷底或标记 needs_review 拆解为 `世` 和 `界`）；
    3. 清洗多余空格和标点符号粘连，保证时间戳与 `line.text` 字词一一对应。
    """
    targets = parse_target_units(target_text)
    if not targets:
        return whisper_words

    if not whisper_words:
        # 无原始对齐时间戳时的安全降级
        return [WordTimestamp(word=t, start=0.0, end=1.0) for t in targets]

    out_words: list[WordTimestamp] = []
    t_idx = 0
    w_idx = 0

    while t_idx < len(targets) and w_idx < len(whisper_words):
        target = targets[t_idx]
        cur_w = whisper_words[w_idx]
        cur_clean = clean_token(cur_w.word)

        # 1. 精确匹配 (最常见情形)
        if cur_clean.lower() == target.lower():
            out_words.append(
                WordTimestamp(
                    word=target,
                    start=cur_w.start,
                    end=cur_w.end,
                    syllables=getattr(cur_w, "syllables", None),
                    needs_review=getattr(cur_w, "needs_review", None),
                    unresolved_compound=getattr(cur_w, "unresolved_compound", None),
                )
            )
            t_idx += 1
            w_idx += 1
            continue

        # 2. Whisper token 包含了连续多个目标单元 (如 Whisper 输出 '世界'，目标为 ['世', '界'])
        if cur_clean.lower().startswith(target.lower()) and len(cur_clean) > len(target):
            accum = ""
            matching_targets: list[str] = []
            temp_t = t_idx
            while temp_t < len(targets) and len(accum) < len(cur_clean):
                accum += targets[temp_t]
                matching_targets.append(targets[temp_t])
                temp_t += 1

            if accum.lower() == cur_clean.lower():
                num_splits = len(matching_targets) - 1
                if num_splits > 0:
                    dur = max(0.05, cur_w.end - cur_w.start)
                    splits: list[float] = []
                    confident = False

                    if wav_16k is not None:
                        local_s = max(0.0, cur_w.start - clip_offset)
                        local_e = max(local_s, cur_w.end - clip_offset)
                        local_splits, confident = find_acoustic_split_points(
                            wav_16k=wav_16k,
                            sr=sr,
                            start_s=local_s,
                            end_s=local_e,
                            num_splits=num_splits,
                        )
                        splits = [round(clip_offset + sp, 3) for sp in local_splits]
                    else:
                        step = dur / len(matching_targets)
                        splits = [round(cur_w.start + (i + 1) * step, 3) for i in range(num_splits)]

                    boundaries = [cur_w.start] + splits + [cur_w.end]
                    # 确保边界单调递增
                    for b_i in range(len(boundaries) - 1):
                        if boundaries[b_i + 1] < boundaries[b_i] + 0.02:
                            boundaries[b_i + 1] = boundaries[b_i] + 0.02

                    for i, mt in enumerate(matching_targets):
                        out_words.append(
                            WordTimestamp(
                                word=mt,
                                start=boundaries[i],
                                end=boundaries[i + 1],
                                needs_review=(True if not confident else None),
                                unresolved_compound=(True if not confident else None),
                            )
                        )
                    t_idx = temp_t
                    w_idx += 1
                    continue

        # 3. Whisper 将单个西文目标拆分成了多个子词 (如目标为 'riverside'，Whisper 为 ['rivers', 'ide'])
        accum = ""
        accum_words: list[WordTimestamp] = []
        temp_w = w_idx
        while temp_w < len(whisper_words) and len(accum) < len(target):
            accum += clean_token(whisper_words[temp_w].word)
            accum_words.append(whisper_words[temp_w])
            temp_w += 1

        if accum.lower() == target.lower():
            s = accum_words[0].start
            e = accum_words[-1].end
            out_words.append(WordTimestamp(word=target, start=s, end=e))
            t_idx += 1
            w_idx = temp_w
            continue

        # 4. 宽松兜底匹配：按位置继承
        out_words.append(
            WordTimestamp(
                word=target,
                start=cur_w.start,
                end=cur_w.end,
                needs_review=getattr(cur_w, "needs_review", None),
            )
        )
        t_idx += 1
        w_idx += 1

    # 5. 补齐剩余目标（若有）
    while t_idx < len(targets):
        prev_e = out_words[-1].end if out_words else 0.0
        out_words.append(WordTimestamp(word=targets[t_idx], start=prev_e, end=prev_e + 0.3))
        t_idx += 1

    # 6. 句内静音气口逆向探测与修剪 (解决重复词 '失重 失重 失重' 之间的换气伴奏空白)
    if wav_16k is not None:
        out_words = trim_intra_line_silence_gaps(
            words=out_words,
            wav_16k=wav_16k,
            sr=sr,
            clip_offset=clip_offset,
        )

    return out_words
