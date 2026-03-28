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
