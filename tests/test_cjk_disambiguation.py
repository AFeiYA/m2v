"""
Unit tests for CJK character-level disambiguation and acoustic dip detection.
"""
import numpy as np
import pytest
from src.storyboard_schema import WordTimestamp
from src.align.cjk_disambiguation import (
    parse_target_units,
    prepare_line_for_alignment,
    find_acoustic_split_points,
    reconcile_aligned_words,
)


def test_parse_target_units_english():
    text = "The riverside unrolls like ribbon"
    units = parse_target_units(text)
    assert units == ["The", "riverside", "unrolls", "like", "ribbon"]


def test_parse_target_units_chinese():
    text = "中间是　你正在瓦解的　世界"
    units = parse_target_units(text)
    assert units == ["中", "间", "是", "你", "正", "在", "瓦", "解", "的", "世", "界"]


def test_parse_target_units_mixed():
    text = "Hold my hand 在这无尽夜色里!"
    units = parse_target_units(text)
    assert units == ["Hold", "my", "hand", "在", "这", "无", "尽", "夜", "色", "里"]


def test_parse_target_units_quotes():
    text = '喝下一瓶名为"现实"的药水'
    units = parse_target_units(text)
    assert units == ["喝", "下", "一", "瓶", "名", "为", "现", "实", "的", "药", "水"]


def test_prepare_line_for_alignment():
    assert prepare_line_for_alignment("世界") == "世 界"
    assert prepare_line_for_alignment("Hold on") == "Hold on"
    assert prepare_line_for_alignment("Hold my hand 在这无尽夜色里") == "Hold my hand 在 这 无 尽 夜 色 里"


def test_reconcile_english_subwords():
    # Whisper broke 'riverside' into 'rivers' and 'ide'
    raw = [
        WordTimestamp(word=" The", start=1.0, end=1.2),
        WordTimestamp(word=" rivers", start=1.2, end=1.5),
        WordTimestamp(word="ide", start=1.5, end=1.8),
        WordTimestamp(word=" like", start=1.8, end=2.0),
    ]
    reconciled = reconcile_aligned_words("The riverside like", raw)
    assert len(reconciled) == 3
    assert reconciled[0].word == "The"
    assert reconciled[1].word == "riverside"
    assert reconciled[1].start == 1.2
    assert reconciled[1].end == 1.8
    assert reconciled[2].word == "like"


def test_reconcile_chinese_merged_tokens():
    # Whisper merged '世界' into one 620ms token
    raw = [
        WordTimestamp(word=" 的", start=128.24, end=128.46),
        WordTimestamp(word=" 世界", start=128.46, end=129.08),
    ]
    reconciled = reconcile_aligned_words("的 世界", raw)
    assert len(reconciled) == 3
    assert reconciled[0].word == "的"
    assert reconciled[1].word == "世"
    assert reconciled[2].word == "界"
    assert reconciled[1].start == 128.46
    assert reconciled[2].end == 129.08
    assert reconciled[1].end == reconciled[2].start


def test_find_acoustic_split_points_sine_wave():
    # Synthesize two sound bursts separated by silence (energy dip)
    sr = 16000
    t = np.linspace(0, 1.0, sr)
    # Burst 1: 0 to 0.4s (loud)
    # Silence/Dip: 0.4s to 0.5s
    # Burst 2: 0.5s to 1.0s (loud)
    y = np.sin(2 * np.pi * 440 * t)
    y[int(0.38 * sr):int(0.52 * sr)] = 0.001

    splits, confident = find_acoustic_split_points(
        wav_16k=y,
        sr=sr,
        start_s=0.0,
        end_s=1.0,
        num_splits=1,
    )
    assert len(splits) == 1
    assert 0.35 <= splits[0] <= 0.55
    assert confident is True
