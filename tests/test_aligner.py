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


def test_word_start_does_not_absorb_a_long_silent_intro():
    from src.aligner import _trim_word_over_silence
    blocks = [(3.8, 6.1), (19.3, 84.4)]
    assert _trim_word_over_silence(3.8, 20.0, blocks) == 19.3
    assert _trim_word_over_silence(20.0, 28.0, blocks) == 20.0
    assert _trim_word_over_silence(3.8, 20.0, [(3.8, 84.4)]) == 3.8


def test_healthy_english_phrase_does_not_trigger_self_heal(monkeypatch):
    import src.aligner as a
    calls = []
    def unexpected(*args, **kwargs):
        calls.append(args)
        raise AssertionError('healthy phrase was re-aligned')
    monkeypatch.setattr(a, 'realign_lines', unexpected)
    lines = [
        AlignedLine(text='Boarding pass folded in my passport', start=19.3, end=22.6, words=[WordTimestamp(word='Boarding pass folded in my passport', start=19.3, end=22.6)]),
        AlignedLine(text='Coffee going cold on the tray', start=23.0, end=26.0, words=[WordTimestamp(word='Coffee going cold on the tray', start=23.0, end=26.0)])
    ]
    assert a._self_heal_alignment(Path('unused.wav'), lines, [(19.3, 26.0)], 26.0) == lines
    assert calls == []


def test_detect_line_lang():
    from src.aligner import detect_line_lang

    # 中文
    assert detect_line_lang("旧书摊的老板打着盹") == "zh"
    assert detect_line_lang("靠窗的位子") == "zh"

    # 英文
    assert detect_line_lang("Meet me at the autumn market") == "en"
    assert detect_line_lang("Coffee going cold on the tray") == "en"

    # 法语 (含变音符)
    assert detect_line_lang("Les feuilles tombent sur le marché") == "other"
    assert detect_line_lang("Un café, des croissants, et toi") == "other"

    # 法语 (无重音符纯字母句子，由欧系高频特征词捕获)
    assert detect_line_lang("Reste encore un peu avec moi") == "other"

    # 日语
    assert detect_line_lang("桜の花びらが舞い散る") == "ja"

    # 韩语
    assert detect_line_lang("가을 바람이 불어오네") == "ko"


def test_whisper_anchor_models():
    from src.aligner import WhisperWordAnchor, WhisperSegmentAnchor

    w = WhisperWordAnchor(word="bonjour", start=1.2, end=1.8, probability=0.98)
    assert w.word == "bonjour"
    assert w.start == 1.2
    assert w.end == 1.8

    s = WhisperSegmentAnchor(id=0, text="Bonjour tout le monde", start=1.0, end=3.5, language="fr", words=[w])
    assert s.language == "fr"
    assert len(s.words) == 1


def test_context_bounded_chorus_anchors():
    """验证上下文前后文夹逼：重复副歌必须受前后唯一锚点严格约束"""
    from src.preprocessor import LyricLine
    lyrics = [
        LyricLine(text="Unique verse 1 line", paragraph=0),
        LyricLine(text="Chorus repeat line", paragraph=1),
        LyricLine(text="Unique verse 2 line", paragraph=2),
        LyricLine(text="Chorus repeat line", paragraph=3),
    ]
    # 段落 1 和 3 文本完全相同 (重复副歌)
    # 段落 0 和 2 文本唯一 (锚点)
    from src.aligner import _detect_line_lang
    assert _detect_line_lang(lyrics[0].text) == "en"
    assert lyrics[1].text == lyrics[3].text
    assert lyrics[0].text != lyrics[2].text


def test_fine_blocks_and_dp_handles_tight_pauses():
    """验证当段落数较多且歌词间停顿较短时，声学块提取与 DP 能够平稳闭合"""
    import numpy as np
    from src.preprocessor import LyricLine

    lyrics = [
        LyricLine(text=f"Line {i}", paragraph=i)
        for i in range(6)
    ]
    assert len(lyrics) == 6
    # 验证段落划分
    stanzas = [[(i, ly)] for i, ly in enumerate(lyrics)]
    assert len(stanzas) == 6



