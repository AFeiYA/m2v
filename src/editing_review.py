"""Non-destructive timing anomaly inspection and smart excerpt recommendations for Phase 2B."""
from __future__ import annotations

import math
import re
from typing import Any

PORTRAIT_SAFE_AREA: dict[str, Any] = {
    "aspect_ratio": "9:16",
    "top_pct": 0.14,
    "bottom_pct": 0.76,
    "left_pct": 0.08,
    "right_pct": 0.86,
    "unsafe_zones": {
        "top": "Top 14%: status bar, creator handle, and live/search chrome",
        "bottom": "Bottom 24% (76%–100%): caption copy, sound marquee, and playback scrub bar",
        "right": "Right 14% (86%–100%): like, comment, share, and bookmark action rail",
        "left": "Left 8% (0%–8%): screen edge breathing margin",
    },
}


def _count_vocal_units(text: str) -> int:
    """Estimate pronounceable syllable/character units in CJK + Latin lyric text."""
    cleaned = re.sub(r"\\N", " ", str(text or "")).strip()
    if not cleaned:
        return 0
    cjk_chars = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", cleaned)
    non_cjk = re.sub(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", " ", cleaned)
    latin_words = [w for w in re.findall(r"[A-Za-z0-9']+", non_cjk) if w]
    latin_units = 0
    for word in latin_words:
        vowel_groups = re.findall(r"[aeiouyAEIOUY]+", word)
        latin_units += max(1, min(4, len(vowel_groups)))
    return len(cjk_chars) + latin_units


def inspect_timing_anomalies(payload: dict[str, Any] | None) -> dict[str, Any]:
    """
    Inspect alignment lines and words for timing anomalies without mutating the payload.

    Detects:
    - overlap: line-to-line or word-to-word timestamp overlap, inverted durations, or out-of-bounds words
    - compressed_duration: words or lines squeezed into implausibly short durations
    - excessive_gap: abnormally long intra-line gaps or single tail words stretched across instrumental breaks
    - low_confidence: lines/words flagged by the aligner (`needs_review`, `unresolved_compound`)
    """
    counts_by_kind = {
        "overlap": 0,
        "compressed_duration": 0,
        "excessive_gap": 0,
        "low_confidence": 0,
    }
    if not isinstance(payload, dict):
        return {
            "total_warnings": 0,
            "flagged_line_indices": [],
            "counts_by_kind": counts_by_kind,
            "warnings": [],
        }

    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list):
        return {
            "total_warnings": 0,
            "flagged_line_indices": [],
            "counts_by_kind": counts_by_kind,
            "warnings": [],
        }

    warnings: list[dict[str, Any]] = []
    flagged_lines: set[int] = set()

    def add_warning(
        *,
        kind: str,
        severity: str,
        line_index: int,
        word_index: int | None,
        start: float,
        end: float,
        title: str,
        message: str,
        evidence: dict[str, Any],
    ) -> None:
        counts_by_kind[kind] = counts_by_kind.get(kind, 0) + 1
        flagged_lines.add(line_index)
        w_suffix = f"w{word_index}" if word_index is not None else "line"
        warnings.append(
            {
                "id": f"L{line_index}_{w_suffix}_{kind}_{len(warnings)}",
                "kind": kind,
                "severity": severity,
                "line_index": line_index,
                "word_index": word_index,
                "start": round(float(start), 3),
                "end": round(float(end), 3),
                "title": title,
                "message": message,
                "evidence": evidence,
            }
        )

    prev_line_end: float | None = None
    prev_line_idx: int | None = None

    for line_idx, line in enumerate(raw_lines):
        if not isinstance(line, dict):
            continue
        line_text = str(line.get("text") or "").strip()
        try:
            l_start = float(line.get("start", 0.0))
            l_end = float(line.get("end", l_start))
        except (TypeError, ValueError):
            continue

        l_dur = l_end - l_start
        line_units = _count_vocal_units(line_text)

        # 1. Line-level overlap or inverted bounds
        if l_dur <= 0.0:
            add_warning(
                kind="overlap",
                severity="error",
                line_index=line_idx,
                word_index=None,
                start=l_start,
                end=l_end,
                title="Non-positive line duration",
                message=f"Line #{line_idx + 1} ends ({l_end:.2f}s) at or before it starts ({l_start:.2f}s).",
                evidence={
                    "line_start": round(l_start, 3),
                    "line_end": round(l_end, 3),
                    "duration_ms": round(l_dur * 1000, 1),
                },
            )
        if prev_line_end is not None and prev_line_idx is not None and l_start < prev_line_end - 0.015:
            overlap_sec = prev_line_end - l_start
            add_warning(
                kind="overlap",
                severity="error",
                line_index=line_idx,
                word_index=None,
                start=l_start,
                end=l_end,
                title="Overlaps previous line",
                message=(
                    f"Line #{line_idx + 1} starts at {l_start:.2f}s, which is {overlap_sec * 1000:.0f}ms "
                    f"before Line #{prev_line_idx + 1} ends ({prev_line_end:.2f}s)."
                ),
                evidence={
                    "previous_line_index": prev_line_idx,
                    "previous_line_end": round(prev_line_end, 3),
                    "line_start": round(l_start, 3),
                    "overlap_ms": round(overlap_sec * 1000, 1),
                },
            )

        # 2. Line-level compressed duration
        if line_units >= 2 and l_dur > 0.0:
            min_expected = max(0.18, line_units * 0.055)
            if l_dur < min_expected:
                ms_per_unit = (l_dur * 1000.0) / max(1, line_units)
                add_warning(
                    kind="compressed_duration",
                    severity="warning",
                    line_index=line_idx,
                    word_index=None,
                    start=l_start,
                    end=l_end,
                    title="Compressed line timing",
                    message=(
                        f"Line #{line_idx + 1} packs {line_units} vocal units into {l_dur * 1000:.0f}ms "
                        f"({ms_per_unit:.0f}ms/unit < 55ms/unit threshold)."
                    ),
                    evidence={
                        "vocal_units": line_units,
                        "duration_ms": round(l_dur * 1000, 1),
                        "ms_per_unit": round(ms_per_unit, 1),
                        "threshold_ms": round(min_expected * 1000, 1),
                    },
                )

        # 3. Aligner low-confidence / review flags on the line
        if bool(line.get("needs_review")):
            conf = line.get("confidence")
            conf_val = round(float(conf), 3) if isinstance(conf, (int, float)) else None
            add_warning(
                kind="low_confidence",
                severity="info",
                line_index=line_idx,
                word_index=None,
                start=l_start,
                end=l_end,
                title="Flagged for alignment review",
                message=(
                    f"Line #{line_idx + 1} was marked for review by the aligner"
                    + (f" (confidence {conf_val:.2f})." if conf_val is not None else ".")
                ),
                evidence={
                    "needs_review": True,
                    "confidence": conf_val,
                },
            )

        words = line.get("words")
        if isinstance(words, list) and words:
            prev_w_end: float | None = None
            prev_w_idx: int | None = None
            prev_w_text: str = ""

            for w_idx, word in enumerate(words):
                if not isinstance(word, dict):
                    continue
                w_text = str(word.get("word") or "").replace("\\N", "").strip()
                try:
                    w_start = float(word.get("start", l_start))
                    w_end = float(word.get("end", w_start))
                except (TypeError, ValueError):
                    continue
                w_dur = w_end - w_start
                w_units = max(1, _count_vocal_units(w_text)) if w_text else 0

                if w_dur <= 0.0:
                    add_warning(
                        kind="overlap",
                        severity="error",
                        line_index=line_idx,
                        word_index=w_idx,
                        start=w_start,
                        end=w_end,
                        title="Non-positive word duration",
                        message=f"Word '{w_text or f'#{w_idx + 1}'}' has zero or negative duration ({w_dur * 1000:.0f}ms).",
                        evidence={
                            "word": w_text,
                            "word_start": round(w_start, 3),
                            "word_end": round(w_end, 3),
                            "duration_ms": round(w_dur * 1000, 1),
                        },
                    )
                elif w_units > 0:
                    min_w_dur = max(0.045, w_units * 0.035)
                    if w_dur < min_w_dur - 1e-4:
                        add_warning(
                            kind="compressed_duration",
                            severity="warning",
                            line_index=line_idx,
                            word_index=w_idx,
                            start=w_start,
                            end=w_end,
                            title="Compressed word duration",
                            message=(
                                f"Word '{w_text}' lasts {w_dur * 1000:.0f}ms "
                                f"(< {min_w_dur * 1000:.0f}ms threshold for {w_units} unit(s))."
                            ),
                            evidence={
                                "word": w_text,
                                "vocal_units": w_units,
                                "duration_ms": round(w_dur * 1000, 1),
                                "threshold_ms": round(min_w_dur * 1000, 1),
                            },
                        )

                if w_start < l_start - 0.05 or w_end > l_end + 0.05:
                    add_warning(
                        kind="overlap",
                        severity="warning",
                        line_index=line_idx,
                        word_index=w_idx,
                        start=w_start,
                        end=w_end,
                        title="Word outside line bounds",
                        message=(
                            f"Word '{w_text}' ({w_start:.2f}s–{w_end:.2f}s) extends outside "
                            f"Line #{line_idx + 1} bounds ({l_start:.2f}s–{l_end:.2f}s)."
                        ),
                        evidence={
                            "word": w_text,
                            "word_start": round(w_start, 3),
                            "word_end": round(w_end, 3),
                            "line_start": round(l_start, 3),
                            "line_end": round(l_end, 3),
                        },
                    )

                if prev_w_end is not None and prev_w_idx is not None:
                    gap = w_start - prev_w_end
                    if gap < -0.01:
                        overlap_ms = abs(gap) * 1000.0
                        add_warning(
                            kind="overlap",
                            severity="error",
                            line_index=line_idx,
                            word_index=w_idx,
                            start=w_start,
                            end=w_end,
                            title="Overlaps previous word",
                            message=(
                                f"Word '{w_text}' starts at {w_start:.2f}s, overlapping '{prev_w_text}' "
                                f"(ends {prev_w_end:.2f}s) by {overlap_ms:.0f}ms."
                            ),
                            evidence={
                                "word": w_text,
                                "previous_word": prev_w_text,
                                "previous_word_index": prev_w_idx,
                                "previous_word_end": round(prev_w_end, 3),
                                "word_start": round(w_start, 3),
                                "overlap_ms": round(overlap_ms, 1),
                            },
                        )
                    elif gap > 1.2:
                        add_warning(
                            kind="excessive_gap",
                            severity="warning",
                            line_index=line_idx,
                            word_index=w_idx,
                            start=prev_w_end,
                            end=w_start,
                            title="Large intra-line gap",
                            message=(
                                f"{gap:.2f}s gap inside Line #{line_idx + 1} between "
                                f"'{prev_w_text}' and '{w_text}' (> 1.20s threshold)."
                            ),
                            evidence={
                                "previous_word": prev_w_text,
                                "word": w_text,
                                "gap_seconds": round(gap, 3),
                                "threshold_seconds": 1.2,
                            },
                        )

                if len(words) >= 2 and l_dur > 0.0 and w_dur > 3.5 and (w_dur / l_dur) > 0.72:
                    add_warning(
                        kind="excessive_gap",
                        severity="warning",
                        line_index=line_idx,
                        word_index=w_idx,
                        start=w_start,
                        end=w_end,
                        title="Stretched word duration",
                        message=(
                            f"Word '{w_text}' spans {w_dur:.2f}s ({w_dur / l_dur * 100:.0f}% of Line #{line_idx + 1}), "
                            f"which often indicates trailing instrumental drift."
                        ),
                        evidence={
                            "word": w_text,
                            "word_duration_seconds": round(w_dur, 3),
                            "line_duration_seconds": round(l_dur, 3),
                            "line_share_ratio": round(w_dur / l_dur, 3),
                        },
                    )

                if bool(word.get("unresolved_compound")):
                    add_warning(
                        kind="low_confidence",
                        severity="info",
                        line_index=line_idx,
                        word_index=w_idx,
                        start=w_start,
                        end=w_end,
                        title="Unresolved compound token",
                        message=f"Word '{w_text}' is marked as an unresolved compound token.",
                        evidence={
                            "word": w_text,
                            "unresolved_compound": True,
                        },
                    )

                prev_w_end = max(prev_w_end, w_end) if prev_w_end is not None else w_end
                prev_w_idx = w_idx
                prev_w_text = w_text

        prev_line_end = max(prev_line_end, l_end) if prev_line_end is not None else l_end
        prev_line_idx = line_idx

    return {
        "total_warnings": len(warnings),
        "flagged_line_indices": sorted(flagged_lines),
        "counts_by_kind": counts_by_kind,
        "warnings": warnings,
    }


def snap_excerpt_to_sentence_bounds(
    payload: dict[str, Any] | None,
    start_time: float = 0.0,
    end_time: float | None = None,
    duration_limit: float | None = None,
) -> dict[str, Any]:
    """
    Snap an arbitrary time window to complete lyric sentence (line) boundaries.

    Never cuts through the middle of a lyric line when lines are available.
    """
    raw_lines = (payload or {}).get("lines") if isinstance(payload, dict) else []
    valid_lines: list[tuple[int, float, float, str]] = []
    if isinstance(raw_lines, list):
        for idx, line in enumerate(raw_lines):
            if not isinstance(line, dict):
                continue
            try:
                ls = float(line.get("start", 0.0))
                le = float(line.get("end", ls))
            except (TypeError, ValueError):
                continue
            text = str(line.get("text") or "").replace("\\N", " ").strip()
            if le > ls:
                valid_lines.append((idx, ls, le, text))

    req_start = max(0.0, float(start_time or 0.0))
    if end_time is not None and float(end_time) > req_start:
        req_end = float(end_time)
    elif duration_limit is not None and float(duration_limit) > 0:
        req_end = req_start + float(duration_limit)
    else:
        req_end = req_start + 25.0

    if not valid_lines:
        dur = max(1.0, req_end - req_start)
        return {
            "start_time": round(req_start, 3),
            "end_time": round(req_start + dur, 3),
            "duration": round(dur, 3),
            "start_line_index": 0,
            "end_line_index": 0,
            "line_count": 0,
            "preview_text": "",
        }

    # Find start sentence: first line whose end is after req_start + 0.15s, or closest line start
    start_pos = 0
    best_start_dist = float("inf")
    for pos, (_, ls, le, _) in enumerate(valid_lines):
        if ls <= req_start < le - 0.15:
            start_pos = pos
            break
        dist = abs(ls - req_start)
        if dist < best_start_dist:
            best_start_dist = dist
            start_pos = pos

    # Find end sentence >= start_pos whose end is closest to req_end
    end_pos = start_pos
    best_end_dist = float("inf")
    for pos in range(start_pos, len(valid_lines)):
        _, ls, le, _ = valid_lines[pos]
        dist = abs(le - req_end)
        if dist < best_end_dist:
            best_end_dist = dist
            end_pos = pos
        if le >= req_end and pos > start_pos:
            break

    snapped_start = valid_lines[start_pos][1]
    snapped_end = valid_lines[end_pos][2]
    preview_lines = [valid_lines[p][3] for p in range(start_pos, end_pos + 1) if valid_lines[p][3]]
    preview_text = " / ".join(preview_lines[:3])
    if len(preview_lines) > 3:
        preview_text += " …"

    return {
        "start_time": round(snapped_start, 3),
        "end_time": round(snapped_end, 3),
        "duration": round(max(0.1, snapped_end - snapped_start), 3),
        "start_line_index": valid_lines[start_pos][0],
        "end_line_index": valid_lines[end_pos][0],
        "line_count": end_pos - start_pos + 1,
        "preview_text": preview_text,
    }


def _average_energy_in_window(energy_curve: list[Any], start: float, end: float) -> float | None:
    if not isinstance(energy_curve, list) or not energy_curve or end <= start:
        return None
    samples: list[float] = []
    for pt in energy_curve:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            t, val = float(pt[0]), float(pt[1])
        elif isinstance(pt, dict) and "time" in pt and "energy" in pt:
            t, val = float(pt["time"]), float(pt["energy"])
        else:
            continue
        if start <= t <= end:
            samples.append(val)
    if not samples:
        return None
    return sum(samples) / len(samples)


def recommend_excerpt_candidates(
    payload: dict[str, Any] | None,
    *,
    target_duration: float = 25.0,
    min_duration: float = 12.0,
    max_duration: float = 45.0,
    max_candidates: int = 4,
) -> list[dict[str, Any]]:
    """
    Recommend promotional clip candidates aligned to complete lyric sentence boundaries.

    Combines:
    - Structural sections (`sections` from Suno metadata or alignment)
    - Lyric density and vocal hooks (`lines`)
    - Musical energy and cut candidates (`analysis.energy_curve`, `analysis.cut_candidates`)
    """
    if not isinstance(payload, dict):
        return []
    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        return []

    lines: list[dict[str, Any]] = []
    for idx, line in enumerate(raw_lines):
        if not isinstance(line, dict):
            continue
        try:
            ls = float(line.get("start", 0.0))
            le = float(line.get("end", ls))
        except (TypeError, ValueError):
            continue
        text = str(line.get("text") or "").replace("\\N", " ").strip()
        if le <= ls or not text:
            continue
        lines.append(
            {
                "index": idx,
                "start": ls,
                "end": le,
                "duration": le - ls,
                "text": text,
                "units": _count_vocal_units(text),
            }
        )

    if not lines:
        return []

    sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
    energy_curve = analysis.get("energy_curve") if isinstance(analysis.get("energy_curve"), list) else []
    cut_candidates = analysis.get("cut_candidates") if isinstance(analysis.get("cut_candidates"), list) else []

    def _window_end_for_start(start_pos: int, preferred_end_time: float | None = None) -> int:
        s_time = lines[start_pos]["start"]
        best_pos = start_pos
        best_diff = float("inf")
        goal_end = preferred_end_time if (preferred_end_time and preferred_end_time > s_time + min_duration) else (s_time + target_duration)
        goal_end = min(s_time + max_duration, max(s_time + min_duration, goal_end))

        for pos in range(start_pos, len(lines)):
            e_time = lines[pos]["end"]
            dur = e_time - s_time
            if dur > max_duration and pos > start_pos:
                break
            diff = abs(e_time - goal_end)
            if diff < best_diff:
                best_diff = diff
                best_pos = pos
        return best_pos

    raw_candidates: list[dict[str, Any]] = []

    # 1. Section-anchored candidates (Chorus, Hook, Drop, Verse 1, Bridge, etc.)
    for sec_idx, sec in enumerate(sections):
        if not isinstance(sec, dict):
            continue
        sec_name = str(sec.get("name") or sec.get("section_type") or f"Section {sec_idx + 1}").strip()
        sec_type = str(sec.get("section_type") or sec_name).lower()
        try:
            sec_start = float(sec.get("start", 0.0))
            sec_end = float(sec.get("end", 0.0)) if sec.get("end") is not None else None
        except (TypeError, ValueError):
            continue

        # Skip pure instrumental intros/outros if they have no lyrics nearby
        start_pos = None
        for pos, ln in enumerate(lines):
            if ln["end"] > sec_start + 0.2:
                start_pos = pos
                break
        if start_pos is None:
            continue

        end_pos = _window_end_for_start(start_pos, sec_end)
        c_start = lines[start_pos]["start"]
        c_end = lines[end_pos]["end"]
        c_dur = c_end - c_start
        if c_dur < 4.0:
            continue

        is_chorus = bool(re.search(r"chorus|hook|drop|副歌|高潮", sec_name, re.I) or "chorus" in sec_type)
        is_verse = bool(re.search(r"verse|主歌", sec_name, re.I) or "verse" in sec_type)
        is_bridge = bool(re.search(r"bridge|pre-chorus|过渡|导歌", sec_name, re.I))

        base_score = 0.65
        reasons = [f"Aligned to {sec_name} sentence boundaries"]
        kind = "section"
        if is_chorus:
            base_score = 0.92
            kind = "chorus_hook"
            reasons.insert(0, "Primary chorus / vocal hook section")
        elif is_bridge:
            base_score = 0.78
            kind = "bridge_build"
            reasons.insert(0, "Pre-chorus / bridge emotional build")
        elif is_verse:
            base_score = 0.74
            kind = "story_opening"
            reasons.insert(0, "Clear narrative verse entrance")

        raw_candidates.append(
            {
                "kind": kind,
                "label": f"{sec_name}",
                "section_name": sec_name,
                "start_pos": start_pos,
                "end_pos": end_pos,
                "base_score": base_score,
                "reasons": reasons,
            }
        )

    # 2. Sliding multi-sentence windows scored by lyric hook density + audio energy + cut candidates
    step = max(1, len(lines) // 10)
    for start_pos in range(0, len(lines), step):
        end_pos = _window_end_for_start(start_pos)
        c_start = lines[start_pos]["start"]
        c_end = lines[end_pos]["end"]
        c_dur = c_end - c_start
        if c_dur < min(8.0, min_duration) and len(lines) > 3:
            continue

        window_lines = lines[start_pos : end_pos + 1]
        total_units = sum(ln["units"] for ln in window_lines)
        units_per_sec = total_units / max(1.0, c_dur)
        # Ideal vocal pacing is ~2.2 to 4.5 units/sec
        pacing_score = max(0.2, 1.0 - min(1.0, abs(units_per_sec - 3.2) / 3.2))
        duration_fit = max(0.2, 1.0 - min(1.0, abs(c_dur - target_duration) / max(10.0, target_duration)))

        energy_val = _average_energy_in_window(energy_curve, c_start, c_end)
        energy_score = float(energy_val) if energy_val is not None else 0.55

        # Boost if near a high-Everything cut candidate or downbeat
        cut_boost = 0.0
        for cut in cut_candidates:
            if isinstance(cut, dict):
                ct = float(cut.get("time", -999.0))
                cs = float(cut.get("score", 0.5))
                if abs(ct - c_start) <= 1.2:
                    cut_boost = max(cut_boost, 0.08 * cs)

        score = 0.40 * pacing_score + 0.35 * energy_score + 0.25 * duration_fit + cut_boost
        reasons: list[str] = [f"{len(window_lines)} complete lyric sentences ({c_dur:.1f}s)"]
        if energy_val is not None and energy_val >= 0.65:
            reasons.insert(0, f"High musical energy peak ({int(energy_val * 100)}%)")
        elif pacing_score >= 0.75:
            reasons.insert(0, f"Strong vocal hook density ({total_units} vocal units)")

        label = "Energy Peak Excerpt" if (energy_val and energy_val >= 0.65) else (
            "Opening Vocal Hook" if start_pos == 0 else f"Lyric Highlight (L{lines[start_pos]['index'] + 1}–L{lines[end_pos]['index'] + 1})"
        )
        raw_candidates.append(
            {
                "kind": "energy_peak" if (energy_val and energy_val >= 0.65) else "lyric_hook",
                "label": label,
                "section_name": "",
                "start_pos": start_pos,
                "end_pos": end_pos,
                "base_score": score,
                "reasons": reasons,
            }
        )

    # Enrich, score, and deduplicate overlapping windows so user gets diverse choices
    scored: list[dict[str, Any]] = []
    for item in raw_candidates:
        sp = item["start_pos"]
        ep = item["end_pos"]
        c_start = lines[sp]["start"]
        c_end = lines[ep]["end"]
        c_dur = max(0.1, c_end - c_start)
        window_lines = lines[sp : ep + 1]
        total_units = sum(ln["units"] for ln in window_lines)
        energy_val = _average_energy_in_window(energy_curve, c_start, c_end)
        final_score = float(item["base_score"])
        if energy_val is not None:
            final_score = min(0.99, final_score * 0.8 + energy_val * 0.2)

        preview_text = " / ".join(ln["text"] for ln in window_lines[:3])
        if len(window_lines) > 3:
            preview_text += " …"

        scored.append(
            {
                "kind": item["kind"],
                "label": item["label"],
                "section_name": item["section_name"],
                "start_time": round(c_start, 3),
                "end_time": round(c_end, 3),
                "duration": round(c_dur, 3),
                "start_line_index": lines[sp]["index"],
                "end_line_index": lines[ep]["index"],
                "line_count": len(window_lines),
                "preview_text": preview_text,
                "score": round(final_score, 3),
                "reasons": item["reasons"],
                "evidence": {
                    "vocal_units": total_units,
                    "units_per_second": round(total_units / c_dur, 2),
                    "mean_energy": round(energy_val, 3) if energy_val is not None else None,
                    "sentence_aligned": True,
                },
            }
        )

    scored.sort(key=lambda c: (-c["score"], c["start_time"]))

    selected: list[dict[str, Any]] = []
    for cand in scored:
        # Avoid near-duplicate windows (overlap > 65% of shorter window)
        is_duplicate = False
        for existing in selected:
            inter_start = max(cand["start_time"], existing["start_time"])
            inter_end = min(cand["end_time"], existing["end_time"])
            inter = max(0.0, inter_end - inter_start)
            shorter = max(0.1, min(cand["duration"], existing["duration"]))
            if (inter / shorter) > 0.65 or (
                cand["start_line_index"] == existing["start_line_index"]
                and cand["end_line_index"] == existing["end_line_index"]
            ):
                is_duplicate = True
                break
        if not is_duplicate:
            cand_with_id = {"id": f"excerpt_{len(selected) + 1}", **cand}
            selected.append(cand_with_id)
            if len(selected) >= max_candidates:
                break

    # If song is short and only 1 window was selected, offer a shorter punchy hook window if possible
    if len(selected) == 1 and len(lines) >= 2:
        mid = len(lines) // 2
        alt_start = lines[mid]["start"]
        alt_end = lines[-1]["end"]
        if alt_end > alt_start and (lines[mid]["index"] != selected[0]["start_line_index"]):
            alt_lines = lines[mid:]
            selected.append(
                {
                    "id": "excerpt_2",
                    "kind": "closing_hook",
                    "label": "Closing Hook",
                    "section_name": "",
                    "start_time": round(alt_start, 3),
                    "end_time": round(alt_end, 3),
                    "duration": round(alt_end - alt_start, 3),
                    "start_line_index": lines[mid]["index"],
                    "end_line_index": lines[-1]["index"],
                    "line_count": len(alt_lines),
                    "preview_text": " / ".join(ln["text"] for ln in alt_lines[:3]),
                    "score": round(max(0.5, selected[0]["score"] - 0.12), 3),
                    "reasons": ["Second-half vocal hook aligned to complete sentences"],
                    "evidence": {
                        "vocal_units": sum(ln["units"] for ln in alt_lines),
                        "units_per_second": round(sum(ln["units"] for ln in alt_lines) / max(0.1, alt_end - alt_start), 2),
                        "mean_energy": None,
                        "sentence_aligned": True,
                    },
                }
            )

    return selected
