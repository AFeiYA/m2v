from __future__ import annotations

import numpy as np
import pytest

from src.align.interlude_guard import detect_macro_interludes, partition_lyrics_by_interludes
from src.storyboard_schema import WordTimestamp


class DummyLyricLine:
    def __init__(self, text: str, paragraph: int = 1):
        self.text = text
        self.paragraph = paragraph
        self.is_annotation = False


def test_detect_macro_interludes_filters_isolated_transient():
    """Verify that an isolated transient blip (< 2.5s) in a long intro is filtered out."""
    sr = 16000
    total_dur = 60.0
    wav = np.zeros(int(total_dur * sr), dtype=np.float32)

    # 1. Transient noise blip at 25.8s - 27.2s (dur = 1.4s)
    # Surrounded by 25.8s silence before and (33.0 - 27.2 = 5.8s) silence after
    t_s = int(25.8 * sr)
    t_e = int(27.2 * sr)
    wav[t_s:t_e] = 0.05

    # 2. Real vocal phrase at 33.0s - 45.0s
    v_s = int(33.0 * sr)
    v_e = int(45.0 * sr)
    wav[v_s:v_e] = 0.08

    interludes, clusters = detect_macro_interludes(wav, sr=sr, min_gap_sec=4.5, energy_thresh=0.015)

    # The transient blip must be filtered; first cluster should be the true singing
    assert len(clusters) == 1
    assert clusters[0][0] >= 32.5 and clusters[0][1] <= 45.5


def test_partition_lyrics_by_interludes_with_intro_and_rough_ends():
    """Verify that partition_lyrics_by_interludes handles long intros and spans correctly."""
    lyrics = [
        DummyLyricLine("Line 1 (Verse 1)"),
        DummyLyricLine("Line 2 (Verse 1)"),
        DummyLyricLine("Line 3 (Verse 2)"),
        DummyLyricLine("Line 4 (Chorus)"),
    ]

    interludes = [(50.0, 65.0)]
    rough_starts = [33.0, 40.0, 66.0, 75.0]
    rough_ends = [38.0, 45.0, 72.0, 80.0]
    total_audio_sec = 100.0
    first_voice_start = 33.0

    partitions = partition_lyrics_by_interludes(
        lyrics=lyrics,
        interludes=interludes,
        rough_starts=rough_starts,
        total_audio_sec=total_audio_sec,
        first_voice_start=first_voice_start,
        rough_ends=rough_ends,
    )

    assert len(partitions) == 2
    # Partition 1 starts at intro offset, not 0.0s
    assert partitions[0]["window_start"] == pytest.approx(32.5, abs=0.1)
    assert partitions[0]["window_end"] == 50.0
    assert len(partitions[0]["lyrics"]) == 2
    assert partitions[0]["lyrics"][0].text == "Line 1 (Verse 1)"
    assert partitions[0]["lyrics"][1].text == "Line 2 (Verse 1)"

    # Partition 2 follows the interlude
    assert partitions[1]["window_start"] == 65.0
    assert len(partitions[1]["lyrics"]) == 2
    assert partitions[1]["lyrics"][0].text == "Line 3 (Verse 2)"
    assert partitions[1]["lyrics"][1].text == "Line 4 (Chorus)"
