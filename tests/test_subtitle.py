"""ASS 字幕生成器 单元测试"""

import tempfile
from pathlib import Path

from src.aligner import AlignmentResult, AlignedLine, WordTimestamp
from src.storyboard_schema import SyllableTimestamp
from src.subtitle import generate_ass, _create_dialogue_line, format_word_karaoke
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
        config = SubtitleConfig(use_karaoke_gradient=False)
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
            assert "\\k50" in content or "\\kf50" in content  # 每个字 0.5s = 50cs

    def test_english_word_spacings_preserved(self):
        """验证英文歌词生成 ASS 时单词间空格完整保留，不粘连"""
        alignment = AlignmentResult(lines=[
            AlignedLine(
                text="The riverside unrolls like ribbon",
                start=1.0,
                end=4.0,
                words=[
                    WordTimestamp(word="The", start=1.0, end=1.5),
                    WordTimestamp(word="riverside", start=1.5, end=2.2),
                    WordTimestamp(word="unrolls", start=2.2, end=2.8),
                    WordTimestamp(word="like", start=2.8, end=3.1),
                    WordTimestamp(word="ribbon", start=3.1, end=4.0),
                ],
            ),
        ])
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "test_en.ass"
            result = generate_ass(alignment, output)
            content = result.read_text(encoding="utf-8-sig")

            # 验证活动行卡拉OK标签中英文单词后含有空格
            assert "The " in content
            assert "riverside " in content
            assert "unrolls " in content
            assert "like " in content
            assert "ribbon" in content

            # 验证未唱/静态文本中不是无空格粘连
            assert "Theriverside" not in content
            assert "unrollslike" not in content
            assert alignment.lines[0].text == "The riverside unrolls like ribbon"

    def test_chinese_word_spacings_not_polluted(self):
        """验证连续中文歌词不会被错误地插入英文空格"""
        alignment = AlignmentResult(lines=[
            AlignedLine(
                text="月亮在云层里",
                start=1.0,
                end=3.0,
                words=[
                    WordTimestamp(word="月", start=1.0, end=1.3),
                    WordTimestamp(word="亮", start=1.3, end=1.6),
                    WordTimestamp(word="在", start=1.6, end=2.0),
                    WordTimestamp(word="云", start=2.0, end=2.3),
                    WordTimestamp(word="层", start=2.3, end=2.6),
                    WordTimestamp(word="里", start=2.6, end=3.0),
                ],
            ),
        ])
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "test_zh.ass"
            result = generate_ass(alignment, output)
            content = result.read_text(encoding="utf-8-sig")

            assert "月 " not in content
            assert "亮 " not in content
            assert "{\\kf30}月{\\kf30}亮" in content or "{\\k30}月{\\k30}亮" in content
            assert alignment.lines[0].text == "月亮在云层里"

    def test_mixed_chinese_english_spacings(self):
        """验证中英混排歌词中，中英边界和英文间空格正常保留"""
        alignment = AlignmentResult(lines=[
            AlignedLine(
                text="在 Suno 上写歌 Hello World",
                start=1.0,
                end=5.0,
                words=[
                    WordTimestamp(word="在", start=1.0, end=1.4),
                    WordTimestamp(word="Suno", start=1.4, end=2.0),
                    WordTimestamp(word="上", start=2.0, end=2.4),
                    WordTimestamp(word="写", start=2.4, end=2.8),
                    WordTimestamp(word="歌", start=2.8, end=3.2),
                    WordTimestamp(word="Hello", start=3.2, end=4.0),
                    WordTimestamp(word="World", start=4.0, end=5.0),
                ],
            ),
        ])
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "test_mixed.ass"
            result = generate_ass(alignment, output)
            content = result.read_text(encoding="utf-8-sig")

            assert "Suno " in content
            assert "Hello " in content
            assert "World" in content
            assert alignment.lines[0].text == "在 Suno 上写歌 Hello World"

    def test_tv_and_center_bounce_modes_spacing(self):
        """验证 TV 与 center_bounce 模式下英文空格亦完整保留"""
        alignment = AlignmentResult(lines=[
            AlignedLine(
                text="The riverside unrolls like ribbon",
                start=1.0,
                end=4.0,
                words=[
                    WordTimestamp(word="The", start=1.0, end=1.5),
                    WordTimestamp(word="riverside", start=1.5, end=2.2),
                    WordTimestamp(word="unrolls", start=2.2, end=2.8),
                    WordTimestamp(word="like", start=2.8, end=3.1),
                    WordTimestamp(word="ribbon", start=3.1, end=4.0),
                ],
            ),
        ])
        with tempfile.TemporaryDirectory() as td:
            for mode in ["tv", "center_bounce"]:
                cfg = SubtitleConfig(render_mode=mode)
                output = Path(td) / f"test_{mode}.ass"
                res_align = alignment.model_copy(deep=True)
                generate_ass(res_align, output, config=cfg)
                content = output.read_text(encoding="utf-8-sig")
                assert "The " in content
                assert "riverside " in content
                assert "Theriverside" not in content

    def test_syllable_level_karaoke_tags(self):
        """验证词内音节拆分时能正确输出多个 \\kf / \\k 标签并保留词间空格与标点"""
        w = WordTimestamp(
            word="never",
            start=1.0,
            end=1.8,
            syllables=[
                SyllableTimestamp(text="ne", start=1.0, end=1.3),
                SyllableTimestamp(text="ver", start=1.3, end=1.8),
            ],
        )
        # 1. 独立格式化测试
        part, next_t = format_word_karaoke(w, current_t=0.8, k_tag="kf", token="never, ")
        assert "{\\k20}" in part          # 0.8 -> 1.0 的 20cs 静音 gap
        assert "{\\kf30}ne" in part       # 1.0 -> 1.3 的 30cs 音节 1
        assert "{\\kf50}ver, " in part    # 1.3 -> 1.8 的 50cs 音节 2，且吸收逗号和空格
        assert next_t == 1.8

        # 2. 单行事件测试
        line = AlignedLine(
            text="never give up",
            start=1.0,
            end=3.0,
            words=[
                w,
                WordTimestamp(word="give", start=1.9, end=2.4),
                WordTimestamp(word="up", start=2.5, end=3.0),
            ],
        )
        cfg = SubtitleConfig(use_karaoke_gradient=True)
        dialogue = _create_dialogue_line(line, cfg)
        assert "{\\kf30}ne{\\kf50}ver " in dialogue
        assert "{\\kf50}give " in dialogue
        assert "{\\kf50}up" in dialogue

        # 3. 完整 ASS 文件输出测试 (Apple Music, TV, Center Bounce)
        alignment = AlignmentResult(lines=[line])
        with tempfile.TemporaryDirectory() as td:
            for mode in ["apple_music", "tv", "center_bounce"]:
                out_path = Path(td) / f"syllable_{mode}.ass"
                res_align = alignment.model_copy(deep=True)
                generate_ass(res_align, out_path, config=SubtitleConfig(render_mode=mode))
                content = out_path.read_text(encoding="utf-8-sig")
                assert "{\\kf30}ne" in content
                assert "{\\kf50}ver" in content

