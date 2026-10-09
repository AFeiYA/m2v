"""
Alignment Quality Auditing and Self-Healing.
Monitors alignment quality, detects over-compression, trims silence absorption,
and triggers targeted self-healing where appropriate.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.storyboard_schema import AlignedLine, WordTimestamp

if TYPE_CHECKING:
    from src.config import AlignerConfig

log = logging.getLogger("m2v")


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
            audited_words.append(WordTimestamp(
                word=w.word,
                start=round(ws, 3),
                end=round(we, 3),
                syllables=getattr(w, "syllables", None),
            ))
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


def _self_heal_alignment(
    vocals_path: Path,
    aligned_lines: list[AlignedLine],
    singing_sections: list[tuple[float, float]],
    total_audio_sec: float,
    config: AlignerConfig | None = None,
    realign_func: Any = None,
) -> list[AlignedLine]:
    """自动检测 CTC 对齐结果中的异常压缩/提前坍缩，并针对受影响乐段区间自动触发局部声学重对齐自愈。"""
    indexed_lines = [(i, l) for i, l in enumerate(aligned_lines) if not getattr(l, "is_annotation", False)]
    if len(indexed_lines) < 2:
        return aligned_lines

    # 1. 扫描异常压缩行
    anomalous_k_indices: list[int] = []
    last_vocal_end = singing_sections[-1][1] if singing_sections else total_audio_sec
    last_line_end = indexed_lines[-1][1].end
    tail_lag = last_vocal_end - last_line_end

    for k, (orig_i, line) in enumerate(indexed_lines):
        char_count = len(re.findall(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]|[a-zA-Z0-9\u00C0-\u024F]+(?:['’\-][a-zA-Z0-9\u00C0-\u024F]+)*", line.text))
        dur = max(0.0, line.end - line.start)
        rate = dur / max(1, char_count)

        is_anom = False
        if char_count >= 4 and (dur < 0.6 or rate < 0.085):
            is_anom = True
        elif char_count >= 6 and (dur < 0.85 or rate < 0.10):
            is_anom = True
        elif k >= len(indexed_lines) - 3 and tail_lag > 3.5 and (dur < 1.2 or rate < 0.12):
            is_anom = True

        if is_anom:
            anomalous_k_indices.append(k)

    if not anomalous_k_indices:
        return aligned_lines

    clusters: list[list[int]] = []
    for ak in anomalous_k_indices:
        if not clusters or ak > clusters[-1][-1] + 1:
            clusters.append([ak])
        else:
            clusters[-1].append(ak)

    for cluster in clusters:
        k_first = cluster[0]
        k_last = cluster[-1]

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

        if rough_end <= rough_start + 1.0 or realign_func is None:
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
            repaired = realign_func(
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

                anom_improved = any(
                    (repaired[it_idx].end - repaired[it_idx].start) > max(0.8, (target_items[it_idx][1].end - target_items[it_idx][1].start) * 1.5)
                    for it_idx in range(len(target_items))
                    if (target_items[it_idx][1].end - target_items[it_idx][1].start) < 0.6
                )
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
            log.warning("局部声学自愈执行失败 (保留原安全边界): %s", e)

    return aligned_lines
