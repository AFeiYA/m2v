"""对齐模块 单元测试 — 测试 fallback 策略和数据结构"""

import json
import tempfile
from pathlib import Path

from src.aligner import (
    AlignmentResult,
    AlignedLine,
    WordTimestamp,
    _fallback_even_split,
)


class TestFallbackEvenSplit:
    def test_basic(self):
        words = _fallback_even_split("你好世界", start=1.0, end=3.0)
        assert len(words) == 4
        assert words[0].word == "你"
        assert abs(words[0].start - 1.0) < 0.01
        assert abs(words[-1].end - 3.0) < 0.01

    def test_single_char(self):
        words = _fallback_even_split("好", start=0.0, end=1.0)
        assert len(words) == 1
        assert words[0].word == "好"
        assert abs(words[0].end - 1.0) < 0.01

    def test_empty_text(self):
        words = _fallback_even_split("", start=0.0, end=1.0)
        assert len(words) == 0

    def test_spaces_ignored(self):
        words = _fallback_even_split("你 好", start=0.0, end=1.0)
        assert len(words) == 2  # 空格被过滤


class TestAlignmentResult:
    def _make_result(self) -> AlignmentResult:
        return AlignmentResult(lines=[
            AlignedLine(
                text="测试",
                start=0.0,
                end=1.0,
                words=[
                    WordTimestamp(word="测", start=0.0, end=0.5),
                    WordTimestamp(word="试", start=0.5, end=1.0),
                ],
            ),
        ])

    def test_to_dict(self):
        result = self._make_result()
        d = result.to_dict()
        assert "lines" in d
        assert len(d["lines"]) == 1
        assert len(d["lines"][0]["words"]) == 2

    def test_save_and_load_json(self):
        result = self._make_result()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.json"
            result.save_json(path)
            assert path.exists()

            loaded = AlignmentResult.load_json(path)
            assert len(loaded.lines) == 1
            assert loaded.lines[0].words[0].word == "测"
            assert abs(loaded.lines[0].words[0].start - 0.0) < 0.01


class TestSelfHealAlignment:
    def test_healthy_lines_untouched(self):
        from src.aligner import _self_heal_alignment
        healthy_lines = [
            AlignedLine(
                text="第一句歌词测试",
                start=10.0,
                end=13.0,
                words=[WordTimestamp(word="第", start=10.0, end=13.0)]
            ),
            AlignedLine(
                text="第二句歌词测试",
                start=14.0,
                end=17.0,
                words=[WordTimestamp(word="第", start=14.0, end=17.0)]
            ),
        ]
        out = _self_heal_alignment(
            vocals_path=Path("fake.wav"),
            aligned_lines=healthy_lines,
            singing_sections=[(10.0, 17.0)],
            total_audio_sec=20.0,
        )
        assert len(out) == 2
        assert out[0].start == 10.0
        assert out[1].end == 17.0




def test_quality_rejects_dense_floor_timestamps():
    from src.aligner import alignment_quality_issue
    words=[WordTimestamp(word="字",start=i*.02,end=(i+1)*.02) for i in range(20)]
    line=AlignedLine(text="字"*20,start=0,end=.4,words=words)
    assert "大面积时间挤压" in alignment_quality_issue([line])


def test_quality_preserves_fast_but_plausible_rap():
    from src.aligner import alignment_quality_issue
    words=[WordTimestamp(word="字",start=i*.1,end=(i+1)*.1) for i in range(20)]
    line=AlignedLine(text="字"*20,start=0,end=2,words=words)
    assert alignment_quality_issue([line]) is None


def test_quality_rejects_word_spanning_long_instrumental_gap():
    from src.aligner import alignment_quality_issue
    line=AlignedLine(text="而",start=1,end=36,words=[WordTimestamp(word="而",start=1,end=36)])
    assert "超过 20 秒" in alignment_quality_issue([line])


def test_onset_keeps_opening_voice_before_a_long_pause(tmp_path):
    import numpy as np
    import soundfile as sf
    from src.aligner import detect_vocal_onset
    rate=16000
    audio=np.zeros(rate*12,dtype=np.float32)
    audio[rate:rate*2]=.3
    audio[rate*8:rate*10]=.3
    path=tmp_path/"opening-shout.wav";sf.write(path,audio,rate)
    assert abs(detect_vocal_onset(path)-1)<.11


def test_quality_ignores_long_arrangement_annotation():
    from src.aligner import alignment_quality_issue
    line=AlignedLine(text="（Instrumental）",start=0,end=30,words=[WordTimestamp(word="（Instrumental）",start=0,end=30)])
    assert alignment_quality_issue([line]) is None
