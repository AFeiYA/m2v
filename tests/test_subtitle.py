"""ASS 字幕生成器 单元测试"""

import tempfile
from pathlib import Path

from src.aligner import AlignmentResult, AlignedLine, WordTimestamp
from src.subtitle import generate_ass, _generate_apple_music_events, _generate_tv_events
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
        alignment = AlignmentResult(lines=[self._make_line()])
        results = _generate_apple_music_events(alignment, config, beat_times=[])
        assert len(results) > 0
        result = results[0]
        # 应包含 Dialogue 头
        assert result.startswith("Dialogue: 0,")
        # 应包含 \k 标签
        assert "\\k" in result

    def test_k_duration(self):
        """验证 \\k 时值是否正确 (厘秒)"""
        config = SubtitleConfig()
        config.use_karaoke_gradient = False
        alignment = AlignmentResult(lines=[self._make_line()])
        results = _generate_apple_music_events(alignment, config, beat_times=[])
        assert len(results) > 0
        # 寻找包含卡拉OK歌词的行
        active_line = next(r for r in results if "我" in r)
        # "我" duration = 0.5s = 50cs
        assert "{\\k50}" in active_line
        # "爱" duration = 0.7s = 70cs
        assert "{\\k70}" in active_line
        # "你" duration = 0.8s = 80cs
        assert "{\\k80}" in active_line

    def test_tv_style_events(self):
        config = SubtitleConfig()
        config.use_karaoke_gradient = False
        alignment = AlignmentResult(lines=[self._make_line()])
        results = _generate_tv_events(alignment, config, beat_times=[])
        assert len(results) > 0
        # TV 样式会生成预览和演唱行
        # 我们寻找演唱行
        active_line = next(r for r in results if "{\\k50}" in r)
        assert active_line.startswith("Dialogue: 0,")
        assert "我" in active_line
        assert "爱" in active_line
        assert "你" in active_line


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
            assert "\\kf50" in content or "\\k50" in content  # 每个字 0.5s = 50cs
