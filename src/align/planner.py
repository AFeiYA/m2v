"""
Alignment Task Planner.
Pure logic component that transforms raw lyrics, ASR evidence, and audio features
into a strictly validated, immutable list of AlignmentTask objects before inference.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

import numpy as np

from src.align.evidence import (
    _fallback_even_split,
    _mixed_run_split_bounds,
    _unique_phrase_anchors,
    detect_line_lang,
    find_silence_snap,
    tokenize_lyric_phonetic,
)
from src.align.task import AlignmentTask

if TYPE_CHECKING:
    from src.preprocessor import LyricLine

log = logging.getLogger("m2v")


def _refine_boundaries_with_silence(
    paras: dict[int, list[tuple[int, LyricLine]]],
    para_bounds: dict[int, tuple[float, float]],
    phrase_anchors: dict[int, tuple[float, float]],
    valid_asr: list[dict],
    wav_np: np.ndarray | None,
    sr: int = 16000,
    total_audio_sec: float = 0.0,
) -> dict[int, tuple[float, float]]:
    """细化相邻段落边界：在声学停顿/静音区精准闭合，防止前段拖音或后段起唱被生硬切断。"""
    p_keys = sorted(paras.keys())
    refined_bounds = dict(para_bounds)

    for pi in range(len(p_keys) - 1):
        p_curr = p_keys[pi]
        p_next = p_keys[pi + 1]
        e_curr = refined_bounds[p_curr][1]
        s_next = refined_bounds[p_next][0]
        gap = s_next - e_curr
        if 0.4 <= gap <= 4.0:
            next_head_toks = [c["py"] for c in tokenize_lyric_phonetic(paras[p_next][0][1].text)]
            cand_near_gap = [w for w in valid_asr if e_curr - 1.0 <= w["start"] <= s_next + 1.0]
            cand_toks = [w["py"] for w in cand_near_gap]
            head_onset = None
            if len(next_head_toks) >= 2 and len(cand_toks) >= 2:
                m_head = SequenceMatcher(None, next_head_toks, cand_toks)
                blocks = [b for b in m_head.get_matching_blocks() if b.size >= 2]
                for b in blocks:
                    if b.a <= 1:
                        head_onset = cand_near_gap[b.b]["start"]
                        break
                    elif b.a <= 6:
                        if b.b >= b.a:
                            head_onset = cand_near_gap[b.b - b.a]["start"]
                        else:
                            head_onset = max(e_curr, cand_near_gap[b.b]["start"] - b.a * 0.30)
                        break

            target_boundary = (e_curr + s_next) / 2
            max_bound = s_next
            if head_onset is not None and head_onset < s_next:
                max_bound = min(max_bound, head_onset)
                target_boundary = min(target_boundary, head_onset)
                if e_curr > max_bound:
                    e_curr = find_silence_snap(max_bound - 0.2, wav_np, sr, window=1.0, max_t=max_bound)

            if e_curr < max_bound:
                snap_mid = find_silence_snap(target_boundary, wav_np, sr, window=max(0.4, gap / 2), min_t=e_curr, max_t=max_bound)
                snap_mid = max(e_curr, min(max_bound, snap_mid))
            else:
                snap_mid = max_bound
            refined_bounds[p_curr] = (refined_bounds[p_curr][0], snap_mid)
            refined_bounds[p_next] = (snap_mid, refined_bounds[p_next][1])

    return refined_bounds


def _estimate_span_from_block(
    valid_asr: list[dict],
    first_cand_idx: int,
    last_cand_idx: int,
    missed_head: int,
    missed_tail: int,
    max_gap: float = 1.2,
    token_rate: float = 0.30,
) -> tuple[float, float]:
    """根据声学词流与未匹配词数，沿真实词时间回溯/前推，遇到长停顿则停止，防止跨段越界。"""
    cur_idx = first_cand_idx
    step = 0
    while cur_idx > 0 and step < missed_head:
        prev_w = valid_asr[cur_idx - 1]
        cur_w = valid_asr[cur_idx]
        if cur_w["start"] - prev_w["end"] > max_gap:
            break
        cur_idx -= 1
        step += 1
    rem_head = missed_head - step
    raw_s = valid_asr[cur_idx]["start"] - rem_head * token_rate

    cur_idx = last_cand_idx
    step = 0
    while cur_idx < len(valid_asr) - 1 and step < missed_tail:
        cur_w = valid_asr[cur_idx]
        next_w = valid_asr[cur_idx + 1]
        if next_w["start"] - cur_w["end"] > max_gap:
            break
        cur_idx += 1
        step += 1
    rem_tail = missed_tail - step
    raw_e = valid_asr[cur_idx]["end"] + rem_tail * token_rate

    return raw_s, raw_e



def build_alignment_tasks(
    singing_lyrics: list[tuple[int, LyricLine]],
    asr_words: list[dict],
    total_audio_sec: float,
    min_start: float = 0.0,
    wav_np: np.ndarray | None = None,
    sr: int = 16000,
    song_lang: str | None = None,
    start_is_explicit: bool = False,
) -> list[AlignmentTask]:
    """生成全曲确定性对齐任务计划表 (Task Planning)。"""
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
            if evidence_s < lower - 0.5 or evidence_e > upper + 0.5:
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
                raw_s, raw_e = _estimate_span_from_block(valid_asr, first_cand_idx, last_cand_idx, missed_head, missed_tail)
                raw_s = min_start if p == 0 else max(min_start, raw_s)
                raw_e = min(total_audio_sec, raw_e)
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
                    "missed_head": missed_head,
                    "missed_tail": missed_tail,
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
                                raw_s, raw_e = _estimate_span_from_block(valid_asr, first_cand_idx, last_cand_idx, missed_head, missed_tail)
                                raw_s = max(prev_e, raw_s)
                                raw_e = min(next_s, raw_e)
                                raw_s, raw_e = constrain_window(p, raw_s, raw_e, prev_e, next_s)
                                if raw_e > raw_s:
                                    p_matches.append((raw_s, raw_e, sc))

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
                    para_bounds[gp] = (round(protected_start, 3), round(protected_end, 3))
                    sub_cur = protected_end
                cur_anchor_t = next_anchor_t
                i = j

    # 执行全局声学停顿吸附与邻接边界精细闭合
    para_bounds = _refine_boundaries_with_silence(
        paras=paras,
        para_bounds=para_bounds,
        phrase_anchors=phrase_anchors,
        valid_asr=valid_asr,
        wav_np=wav_np,
        sr=sr,
        total_audio_sec=total_audio_sec,
    )

    tasks: list[AlignmentTask] = []
    task_counter = 0

    def _max_continuous_silence(t1: float, t2: float, thresh: float = 0.012) -> float:
        if wav_np is None or len(wav_np) == 0:
            return 0.0
        i1 = max(0, int(t1 * 16000))
        i2 = min(len(wav_np), int(t2 * 16000))
        if i2 <= i1:
            return 0.0
        chunk = wav_np[i1:i2]
        hop = int(16000 * 0.05)
        if len(chunk) < hop:
            return 0.0
        rms_arr = [float(np.sqrt(np.mean(chunk[i:i + hop] ** 2))) for i in range(0, len(chunk) - hop, hop)]
        max_c, cur_c = 0, 0
        for r in rms_arr:
            if r < thresh:
                cur_c += 1
                max_c = max(max_c, cur_c)
            else:
                cur_c = 0
        return max_c * 0.05

    def _occurrences(tokens: list[str], phrase: list[str]) -> int:
        if not phrase or len(phrase) > len(tokens):
            return 0
        k = len(phrase)
        return sum(1 for i in range(len(tokens) - k + 1) if tokens[i:i + k] == phrase)

    lyric_tokens_all = [[c["py"] for c in tokenize_lyric_phonetic(ly.text)] for _, ly in singing_lyrics]
    asr_tokens_all = [w["py"] for w in asr_words]

    for p in p_keys:
        p_lines = paras[p]
        p_s, p_e = para_bounds[p]
        langs = [detect_line_lang(ly.text, song_lang=song_lang) for _, ly in p_lines]

        # 检查段内静音分割 (Intra-stanza Silence-Gated Sub-runs)
        intra_runs: list[tuple[list[tuple[int, LyricLine]], float, float]] = []
        is_homogeneous = len(set(langs)) == 1
        if is_homogeneous and len(p_lines) >= 2 and wav_np is not None:
            cand_in_p = [w for w in asr_words if p_s - 0.5 <= w["start"] <= p_e + 0.5]
            c_in_toks = [w["py"] for w in cand_in_p]
            split_indices = []
            cur_min_t = p_s
            for li in range(len(p_lines) - 1):
                next_ly = p_lines[li + 1][1]
                next_toks = [c["py"] for c in tokenize_lyric_phonetic(next_ly.text)]
                if len(next_toks) < 3:
                    continue
                m = SequenceMatcher(None, next_toks, c_in_toks)
                blocks = [b for b in m.get_matching_blocks() if b.size >= 4 or (b.size >= 3 and b.size / len(next_toks) >= 0.5)]
                for b in blocks:
                    if b.a > 1:
                        continue
                    phrase = next_toks[b.a:b.a + b.size]
                    if _occurrences(asr_tokens_all, phrase) != 1 or sum(_occurrences(lt, phrase) for lt in lyric_tokens_all) != 1:
                        continue
                    asr_s = cand_in_p[b.b]["start"]
                    prev_li = split_indices[-1][0] if split_indices else 0
                    curr_block_toks = sum(len(tokenize_lyric_phonetic(ly.text)) for _, ly in p_lines[prev_li:li + 1])
                    min_curr_dur = max(0.8, curr_block_toks * 0.20)

                    silence_dur = _max_continuous_silence(cur_min_t + min_curr_dur, asr_s)
                    if silence_dur >= 0.8 and asr_s > cur_min_t + min_curr_dur:
                        split_t = find_silence_snap(asr_s - silence_dur / 2, wav_np, 16000, window=silence_dur / 2,
                                                    min_t=cur_min_t + min_curr_dur, max_t=asr_s)
                        split_indices.append((li + 1, split_t))
                        cur_min_t = split_t
                        break

            if split_indices:
                start_li = 0
                start_t = p_s
                for s_li, s_t in split_indices:
                    intra_runs.append((p_lines[start_li:s_li], start_t, s_t))
                    start_li = s_li
                    start_t = s_t
                intra_runs.append((p_lines[start_li:], start_t, p_e))

        if not intra_runs:
            intra_runs = [(p_lines, p_s, p_e)]

        for sub_p_lines, sub_s, sub_e in intra_runs:
            sub_langs = [detect_line_lang(ly.text, song_lang=song_lang) for _, ly in sub_p_lines]
            if all(l == "en" for l in sub_langs):
                task_counter += 1
                tasks.append(AlignmentTask(
                    task_id=f"task_{task_counter:03d}_p{p}",
                    paragraph_idx=p,
                    line_indices=[orig_idx for orig_idx, _ in sub_p_lines],
                    lyrics=sub_p_lines,
                    language="en",
                    window_start=sub_s,
                    window_end=sub_e,
                    anchor_source="stanza_window",
                    is_estimated=(p not in phrase_anchors and p not in valid_islands),
                ))
                continue
            elif all(l == "zh" for l in sub_langs):
                task_counter += 1
                tasks.append(AlignmentTask(
                    task_id=f"task_{task_counter:03d}_p{p}",
                    paragraph_idx=p,
                    line_indices=[orig_idx for orig_idx, _ in sub_p_lines],
                    lyrics=sub_p_lines,
                    language="zh",
                    window_start=sub_s,
                    window_end=sub_e,
                    anchor_source="stanza_window",
                    is_estimated=(p not in phrase_anchors and p not in valid_islands),
                ))
                continue
            elif all(l not in ("en", "zh") for l in sub_langs):
                task_counter += 1
                tasks.append(AlignmentTask(
                    task_id=f"task_{task_counter:03d}_p{p}",
                    paragraph_idx=p,
                    line_indices=[orig_idx for orig_idx, _ in sub_p_lines],
                    lyrics=sub_p_lines,
                    language="other",
                    window_start=sub_s,
                    window_end=sub_e,
                    anchor_source="stanza_window",
                    is_estimated=(p not in phrase_anchors and p not in valid_islands),
                ))
                continue

            # 混语言段落：按语言块细分
            runs: list[tuple[str, list[tuple[int, LyricLine]]]] = []
            cur_r: list[tuple[int, LyricLine]] = []
            cur_l = None
            for idx_ly in sub_p_lines:
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

            run_tok_counts = [sum(len(tokenize_lyric_phonetic(ly.text)) for _, ly in r_lines) for _, r_lines in runs]
            c_s = sub_s
            for r_idx, (r_lang, r_lines) in enumerate(runs):
                if r_idx == len(runs) - 1:
                    c_e = sub_e
                else:
                    ideal_split, min_split, max_split = _mixed_run_split_bounds(
                        c_s, sub_e, run_tok_counts[r_idx:])
                    next_run_lines = runs[r_idx + 1][1]
                    next_run_toks = [c["py"] for _, ly in next_run_lines for c in tokenize_lyric_phonetic(ly.text)]
                    first_line_tok_count = len(tokenize_lyric_phonetic(next_run_lines[0][1].text)) if next_run_lines else 0

                    cand_in_p = [w for w in asr_words if c_s - 0.5 <= w["start"] <= sub_e + 0.5]
                    found_next_s = None
                    if len(cand_in_p) >= len(next_run_toks):
                        c_in_toks = [w["py"] for w in cand_in_p]
                        m = SequenceMatcher(None, next_run_toks, c_in_toks)
                        if m.ratio() >= 0.40:
                            vbs = [b for b in m.get_matching_blocks() if b.size > 0]
                            if vbs:
                                head_tok_idx = vbs[0].a
                                if head_tok_idx < first_line_tok_count:
                                    matched_asr_s = cand_in_p[vbs[0].b]["start"]
                                    if head_tok_idx == 0:
                                        found_next_s = matched_asr_s
                                    else:
                                        found_next_s = matched_asr_s - head_tok_idx * 0.35
                                else:
                                    found_next_s = ideal_split

                    target_split = found_next_s if found_next_s is not None else ideal_split
                    c_e = find_silence_snap(target_split, wav_np, sr, window=1.5, min_t=min_split, max_t=max_split)

                task_counter += 1
                tasks.append(AlignmentTask(
                    task_id=f"task_{task_counter:03d}_p{p}_r{r_idx}",
                    paragraph_idx=p,
                    line_indices=[orig_idx for orig_idx, _ in r_lines],
                    lyrics=r_lines,
                    language=r_lang,
                    window_start=c_s,
                    window_end=c_e,
                    anchor_source="mixed_lang_split",
                    is_estimated=True,
                ))
                c_s = c_e

    # 完整性校验：验证输入所有行均恰好属于一个对齐任务
    all_task_lines = [idx for t in tasks for idx in t.line_indices]
    expected_lines = [i for i, _ in singing_lyrics]
    if sorted(all_task_lines) != sorted(expected_lines):
        raise ValueError(f"任务规划覆盖异常: 期望 {len(expected_lines)} 行, 规划得到 {len(all_task_lines)} 行")

    log.info("🎯 对齐任务规划完成: 成功创建 %d 个独立对齐任务，覆盖 %d 行歌词",
             len(tasks), len(singing_lyrics))
    return tasks
