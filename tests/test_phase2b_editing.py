"""Unit tests for Phase 2B Editing, Timing Review, Safe Area, and Resolution Profiles."""
from __future__ import annotations

import pytest

from src.editing_review import (
    PORTRAIT_SAFE_AREA,
    inspect_timing_anomalies,
    snap_excerpt_to_sentence_bounds,
    recommend_excerpt_candidates,
)
from src.editor_operations import VideoOptions, video_options
from src.lyric_engine import (
    CURATED_THEMES,
    RESOLUTION_PROFILES,
    get_lyric_video_options,
)
from src.subtitle import SubtitleConfig, generate_ass


def test_portrait_safe_area_constants():
    assert PORTRAIT_SAFE_AREA["aspect_ratio"] == "9:16"
    assert PORTRAIT_SAFE_AREA["top_pct"] == 0.14
    assert PORTRAIT_SAFE_AREA["bottom_pct"] == 0.76
    assert PORTRAIT_SAFE_AREA["left_pct"] == 0.08
    assert PORTRAIT_SAFE_AREA["right_pct"] == 0.86
    assert "top" in PORTRAIT_SAFE_AREA["unsafe_zones"]
    assert "bottom" in PORTRAIT_SAFE_AREA["unsafe_zones"]
    assert "right" in PORTRAIT_SAFE_AREA["unsafe_zones"]
    assert "left" in PORTRAIT_SAFE_AREA["unsafe_zones"]


def test_inspect_timing_anomalies_non_destructive():
    payload = {
        "lines": [
            {
                "start": 2.0,
                "end": 5.0,
                "text": "第一行歌词唱完",
                "words": [
                    {"word": "第一行", "start": 2.0, "end": 3.0},
                    {"word": "歌词", "start": 3.0, "end": 4.0},
                    {"word": "唱完", "start": 4.0, "end": 5.0},
                ],
            },
            {
                "start": 4.8,  # Overlaps by 200ms with line 0
                "end": 4.82,  # Compressed duration (20ms < 45ms)
                "text": "重叠且紧缩的下一行",
                "words": [
                    {"word": "重叠", "start": 4.8, "end": 4.81},
                    {"word": "紧缩", "start": 4.81, "end": 4.82},
                ],
            },
            {
                "start": 6.0,
                "end": 12.0,
                "text": "尾音拖长很长",
                "words": [
                    {"word": "尾音", "start": 6.0, "end": 6.5},
                    {"word": "拖长很长", "start": 6.5, "end": 12.0},  # 5.5s tail stretch (91.7% of line)
                ],
            },
            {
                "start": 13.0,
                "end": 15.0,
                "text": "复核标记词句",
                "needs_review": True,
                "words": [
                    {"word": "复核", "start": 13.0, "end": 14.0, "needs_review": True},
                    {"word": "词句", "start": 14.0, "end": 15.0, "unresolved_compound": True},
                ],
            },
        ]
    }

    import copy
    original_copy = copy.deepcopy(payload)

    result = inspect_timing_anomalies(payload)

    # Verify non-destructive behavior
    assert payload == original_copy

    assert result["total_warnings"] > 0
    assert 1 in result["flagged_line_indices"]
    assert 2 in result["flagged_line_indices"]
    assert 3 in result["flagged_line_indices"]
    assert result["counts_by_kind"]["overlap"] >= 1
    assert result["counts_by_kind"]["compressed_duration"] >= 1
    assert result["counts_by_kind"]["excessive_gap"] >= 1
    assert result["counts_by_kind"]["low_confidence"] >= 1

    overlap_w = [w for w in result["warnings"] if w["kind"] == "overlap" and w["line_index"] == 1]
    assert len(overlap_w) >= 1
    assert overlap_w[0]["evidence"]["overlap_ms"] == 200


def test_inspect_timing_anomalies_clean_payload():
    clean_payload = {
        "lines": [
            {
                "start": 1.0,
                "end": 4.0,
                "text": "微风轻轻吹过山岗",
                "words": [
                    {"word": "微风", "start": 1.0, "end": 2.0},
                    {"word": "轻轻", "start": 2.0, "end": 3.0},
                    {"word": "吹过山岗", "start": 3.0, "end": 4.0},
                ],
            },
            {
                "start": 4.5,
                "end": 7.5,
                "text": "阳光洒下金色光芒",
                "words": [
                    {"word": "阳光", "start": 4.5, "end": 5.5},
                    {"word": "洒下", "start": 5.5, "end": 6.5},
                    {"word": "金色光芒", "start": 6.5, "end": 7.5},
                ],
            },
        ]
    }
    result = inspect_timing_anomalies(clean_payload)
    assert result["total_warnings"] == 0
    assert result["flagged_line_indices"] == []


def test_snap_excerpt_to_sentence_bounds():
    payload = {
        "lines": [
            {"start": 10.0, "end": 14.0, "text": "第一句歌词起唱"},
            {"start": 14.5, "end": 18.0, "text": "第二句旋律扬起"},
            {"start": 18.5, "end": 23.0, "text": "第三句副歌高潮到达"},
            {"start": 23.5, "end": 28.0, "text": "第四句高音回荡悠长"},
            {"start": 29.0, "end": 34.0, "text": "第五句尾声渐弱落幕"},
        ]
    }

    # Cut between 12.0 and 25.0: start snaps to line 0 (10.0), end snaps to line 2 (23.0)
    snapped = snap_excerpt_to_sentence_bounds(payload, start_time=12.0, end_time=25.0)
    assert snapped["start_time"] == 10.0
    assert snapped["end_time"] == 23.0
    assert snapped["start_line_index"] == 0
    assert snapped["end_line_index"] == 2
    assert snapped["line_count"] == 3
    assert "第一句歌词起唱" in snapped["preview_text"]

    # Cut between 12.0 and 27.0: end snaps to line 3 (28.0)
    snapped2 = snap_excerpt_to_sentence_bounds(payload, start_time=12.0, end_time=27.0)
    assert snapped2["start_time"] == 10.0
    assert snapped2["end_time"] == 28.0
    assert snapped2["start_line_index"] == 0
    assert snapped2["end_line_index"] == 3
    assert snapped2["line_count"] == 4


def test_recommend_excerpt_candidates():
    payload = {
        "sections": [
            {"name": "Intro", "label": "前奏", "start": 0.0, "end": 15.0},
            {"name": "Verse 1", "label": "主歌 1", "start": 15.0, "end": 38.0},
            {"name": "Chorus 1", "label": "副歌 1 (高潮)", "start": 38.0, "end": 65.0},
            {"name": "Verse 2", "label": "主歌 2", "start": 65.0, "end": 88.0},
            {"name": "Chorus 2", "label": "副歌 2 (终极大高潮)", "start": 88.0, "end": 118.0},
        ],
        "lines": [
            {"start": 15.0, "end": 19.0, "text": "安静的夜里"},
            {"start": 19.5, "end": 24.0, "text": "微风轻轻吹"},
            {"start": 25.0, "end": 30.0, "text": "思念随风远去"},
            {"start": 31.0, "end": 37.0, "text": "回到最初的起点"},
            # Chorus lines
            {"start": 38.5, "end": 43.0, "text": "如果这就是爱"},
            {"start": 43.5, "end": 49.0, "text": "请不要放开我的手"},
            {"start": 49.5, "end": 55.0, "text": "在每一个漫长的黑夜里"},
            {"start": 55.5, "end": 63.0, "text": "都有你温柔陪伴左右"},
            # Verse 2
            {"start": 66.0, "end": 71.0, "text": "走过这片熟悉的街角"},
            {"start": 71.5, "end": 77.0, "text": "回忆依然清晰如昨"},
            # Chorus 2
            {"start": 88.5, "end": 94.0, "text": "如果这就是爱"},
            {"start": 94.5, "end": 100.0, "text": "请用一生来守护"},
            {"start": 100.5, "end": 107.0, "text": "直到世界尽头也无悔"},
            {"start": 107.5, "end": 115.0, "text": "爱是最耀眼的光辉"},
        ],
    }

    candidates = recommend_excerpt_candidates(payload, target_duration=25.0, max_candidates=4)
    assert len(candidates) >= 2
    chorus_cand = next(c for c in candidates if "chorus" in c["kind"])
    assert chorus_cand["score"] >= 0.85
    assert chorus_cand["start_time"] == 38.5
    assert chorus_cand["duration"] >= 12.0
    assert "如果这就是爱" in chorus_cand["preview_text"]


def test_video_options_phase2b_snapping_and_resolution():
    payload = {
        "lines": [
            {"start": 10.0, "end": 14.0, "text": "第一句歌词起唱"},
            {"start": 14.5, "end": 18.0, "text": "第二句旋律扬起"},
            {"start": 18.5, "end": 23.0, "text": "第三句副歌高潮到达"},
        ]
    }

    # 1. Default 1080p, no snapping
    opts1 = VideoOptions(aspect_ratio="9:16", start_time=10.0, end_time=20.0).model_dump()
    transformed1 = video_options(payload, opts1)
    assert "resolution" not in transformed1  # 1080p omitted for compatibility
    assert transformed1["start_time"] == 10.0
    assert transformed1["end_time"] == 20.0

    # 2. Explicit 720p with snap_to_sentence
    opts2 = VideoOptions(
        aspect_ratio="9:16",
        resolution="720p",
        start_time=11.0,
        end_time=17.0,
        snap_to_sentence=True,
    ).model_dump()
    transformed2 = video_options(payload, opts2)
    assert transformed2["resolution"] == "720p"
    # Snapped to sentence boundaries: line 0 start (10.0) and line 1 end (18.0)
    assert transformed2["start_time"] == 10.0
    assert transformed2["end_time"] == 18.0


def test_lyric_options_include_phase2b_curated_themes_and_resolutions():
    opts = get_lyric_video_options()
    assert "curated_themes" in opts
    assert len(opts["curated_themes"]) == 5
    assert "resolutions" in opts
    res_ids = [r["id"] for r in opts["resolutions"]]
    assert "1080p" in res_ids
    assert "720p" in res_ids
    assert "safe_area" in opts
    assert opts["safe_area"]["aspect_ratio"] == "9:16"


def test_portrait_ass_subtitles_adhere_to_safe_area(tmp_path):
    from src.aligner import AlignedLine, AlignmentResult, WordTimestamp

    alignment = AlignmentResult(
        lines=[
            AlignedLine(
                start=1.0,
                end=4.0,
                text="这是测试竖屏安全区的一行比较长的歌词内容展现",
                words=[
                    WordTimestamp(word="这是", start=1.0, end=1.5),
                    WordTimestamp(word="测试", start=1.5, end=2.0),
                    WordTimestamp(word="竖屏", start=2.0, end=2.5),
                    WordTimestamp(word="安全区", start=2.5, end=3.0),
                    WordTimestamp(word="歌词", start=3.0, end=4.0),
                ],
            )
        ]
    )

    # Generate ASS for portrait 9:16 (1080x1920)
    cfg = SubtitleConfig(
        play_res_x=1080,
        play_res_y=1920,
        margin_x=86,
        center_y=int(1920 * 0.48),
        render_mode="apple",
    )
    ass_path = tmp_path / "portrait_test.ass"
    generate_ass(alignment, ass_path, config=cfg)

    ass_content = ass_path.read_text(encoding="utf-8")

    # In 9:16 portrait, lines should be restricted to safe area
    assert "PlayResX: 1080" in ass_content
    assert "PlayResY: 1920" in ass_content
    # MarginL should be at least 86 (safe area margin)
    assert "MarginL" in ass_content
    # Vertical coordinates in Dialogue events should not be in the top 14% (<268px) or bottom 24% (>1459px)
    import re
    pos_matches = re.findall(r"\\pos\((\d+),(\d+)\)", ass_content)
    for x_str, y_str in pos_matches:
        y = int(y_str)
        # Verify vertical coordinates stay within [14% * 1920, 76% * 1920] = [268, 1460]
        assert 260 <= y <= 1470, f"Y coordinate {y} violates 9:16 portrait safe area bounds [268, 1460]"
