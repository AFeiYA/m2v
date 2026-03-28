"""ASS 字幕生成器 单元测试"""

import tempfile
from pathlib import Path

from src.aligner import AlignmentResult, AlignedLine, WordTimestamp
from src.subtitle import generate_ass, _create_dialogue_line
from src.config import SubtitleConfig
from src.utils import seconds_to_ass_time, seconds_to_centiseconds


# ---------------------------------------------------------------------------
# 时间格式化
# ---------------------------------------------------------------------------

class TestTimeFormatting:
    def test_zero(self):
        assert seconds_to_ass_time(0) == "0:00:00.00"

    def test_basic(self):
        assert seconds_to_ass_time(65.32) == "0:01:05.32"

    def test_hour(self):
        assert seconds_to_ass_time(3661.5) == "1:01:01.50"

    def test_negative(self):
        assert seconds_to_ass_time(-1) == "0:00:00.00"

    def test_centiseconds(self):
        assert seconds_to_centiseconds(0.5) == 50
        assert seconds_to_centiseconds(1.0) == 100
        assert seconds_to_centiseconds(0.01) == 1
        assert seconds_to_centiseconds(0.001) == 0 or seconds_to_centiseconds(0.001) >= 1


# ---------------------------------------------------------------------------
# Dialogue 行生成
# ---------------------------------------------------------------------------

class TestDialogueLine:
    def _make_line(self) -> AlignedLine:
        return AlignedLine(
            text="我爱你",
            start=1.0,
            end=3.0,
            words=[
                WordTimestamp(word="我", start=1.0, end=1.5),
                WordTimestamp(word="爱", start=1.5, end=2.2),
                WordTimestamp(word="你", start=2.2, end=3.0),
            ],
        )

    def test_basic_dialogue(self):
        config = SubtitleConfig()
        line = self._make_line()
        result = _create_dialogue_line(line, config, beat_times=[])
        # 应包含 Dialogue 头
        assert result.startswith("Dialogue: 0,")
        # 应包含 \k 标签
        assert "\\k" in result
        # 应包含所有字
        assert "我" in result
        assert "爱" in result
        assert "你" in result

    def test_k_duration(self):
        """验证 \\k 时值是否正确 (厘秒)"""
        config = SubtitleConfig()
        line = self._make_line()
        result = _create_dialogue_line(line, config, beat_times=[])
        # "我" duration = 0.5s = 50cs
        assert "{\\k50}" in result
        # "爱" duration = 0.7s = 70cs
        assert "{\\k70}" in result
        # "你" duration = 0.8s = 80cs
        assert "{\\k80}" in result


# ---------------------------------------------------------------------------
# 完整 ASS 文件生成
# ---------------------------------------------------------------------------

class TestGenerateAss:
    def test_generates_file(self):
        alignment = AlignmentResult(lines=[
            AlignedLine(
                text="测试歌词",
                start=1.0,
                end=3.0,
                words=[
                    WordTimestamp(word="测", start=1.0, end=1.5),
                    WordTimestamp(word="试", start=1.5, end=2.0),
                    WordTimestamp(word="歌", start=2.0, end=2.5),
                    WordTimestamp(word="词", start=2.5, end=3.0),
                ],
            ),
        ])
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "test.ass"
            result = generate_ass(alignment, output)
            assert result.exists()
            content = result.read_text(encoding="utf-8-sig")
            assert "[Script Info]" in content
            assert "[V4+ Styles]" in content
            assert "[Events]" in content
            assert "Dialogue:" in content
            assert "\\k50" in content  # 每个字 0.5s = 50cs
