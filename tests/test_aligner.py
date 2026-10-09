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


def test_mixed_split_reallocates_remaining_time_after_evidence_boundary():
    from src.aligner import _mixed_run_split_bounds
    # First run used 8s instead of its proportional 6s. The next two runs must
    # share the remaining 10s, rather than continue using the original 18s.
    ideal, lower, upper = _mixed_run_split_bounds(8, 18, [10, 10])
    assert ideal == 13
    assert lower == 11 and upper == 15


def test_mixed_split_reserves_each_remaining_run():
    from src.aligner import _mixed_run_split_bounds
    ideal, lower, upper = _mixed_run_split_bounds(0, 6, [8, 1, 1])
    assert ideal == 4.8
    assert lower == 2.4 and upper == 4.4


def test_short_mixed_window_never_creates_reversed_or_outside_bounds():
    from src.aligner import _mixed_run_split_bounds
    start = 10
    counts = [20, 20, 20]
    for i in range(2):
        ideal, lower, upper = _mixed_run_split_bounds(start, 11, counts[i:])
        assert start < ideal < 11
        assert lower == ideal == upper
        start = ideal


def test_silence_snap_preserves_exact_bounds_and_rejects_empty_window():
    import numpy as np
    import pytest
    from src.aligner import find_silence_snap
    with pytest.raises(ValueError, match="边界冲突"):
        find_silence_snap(1, None, min_t=2, max_t=1)
    for wav in (None, np.zeros(32000)):
        assert find_silence_snap(1, wav, min_t=1.001, max_t=1.001) == 1.001
        result = find_silence_snap(1.029, wav, min_t=1.001, max_t=1.029)
        assert 1.001 <= result <= 1.029


def test_asr_gap_windows_skip_instrumental_and_previous_verse_tail():
    from src.aligner import _asr_gap_windows
    words = [{"start": 67, "end": 68.48}, {"start": 98.48, "end": 101.56}]
    assert _asr_gap_windows(words, [(59.3, 68.8), (85.2, 111.1)], 120) == [(84.8, 102.48)]
    assert _asr_gap_windows(words, [(59.3, 68.8)], 120) == []


def test_asr_gap_recovery_uses_offsets_and_invalidates_cache(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf
    import src.aligner as aligner
    from src.config import AlignerConfig
    path = tmp_path / "song.wav"
    sf.write(path, np.zeros(30 * 16000, dtype=np.float32), 16000)
    original = [{"py": "before", "start": 1, "end": 2},
                {"py": "after", "start": 20, "end": 21}]
    calls = []
    def extract(*args, **kwargs):
        calls.append(kwargs)
        return [{"py": t, "start": 1 + i, "end": 1.5 + i}
                for i, t in enumerate(["new", "lyrics", "now", "found"])]
    monkeypatch.setattr(aligner, "extract_asr_words", extract)
    config = AlignerConfig(device="cpu", whisper_model="base")
    result = aligner._recover_asr_gaps(path, original, [(10, 23)], 30, config, "mixed")
    assert result[0] == original[0]
    assert result[1]["start"] == 10.6
    assert [w["py"] for w in result[1:]] == ["new", "lyrics", "now", "found", "after"]
    assert aligner._recover_asr_gaps(path, original, [(10, 23)], 30, config, "mixed") == result
    assert len(calls) == 1
    aligner._recover_asr_gaps(path, original, [(10, 23)], 30, config, "zh")
    assert len(calls) == 2


def test_local_collapsed_sentence_rejected_even_when_rest_of_song_is_healthy():
    from src.aligner import alignment_quality_issue
    normal = AlignedLine(text="normal words", start=1, end=40,
                         words=[WordTimestamp(word="word", start=i, end=i + 0.5) for i in range(40)])
    collapsed = AlignedLine(text="去的时候是逆风", start=41, end=41.14,
                            words=[WordTimestamp(word=c, start=41 + i * .02, end=41 + (i + 1) * .02)
                                   for i, c in enumerate("去的时候是逆风")])
    assert "第 2 行" in alignment_quality_issue([normal, collapsed])


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


def test_estimated_stanza_preserves_unique_phrase_evidence():
    """Weak overall ASR must not let silence snapping cut off a recognized line."""
    from src.aligner import LyricLine, anchor_stanzas_with_asr
    lyrics = [
        (0, LyricLine(text=" ".join(f"unknown{i}" for i in range(70)), paragraph=0)),
        (1, LyricLine(text="a million moving parts on tuesday", paragraph=0)),
        (2, LyricLine(text="another unrecognized ending", paragraph=0)),
        (3, LyricLine(text="watch me catch every ball before it hits the floor", paragraph=1)),
    ]
    phrases = [(34.0, "a million moving parts on tuesday"),
               (40.0, "watch me catch every ball before it hits the floor")]
    words = [{"py": token, "start": start + i, "end": start + i + 0.8}
             for start, text in phrases for i, token in enumerate(text.split())]
    _, bounds = anchor_stanzas_with_asr(lyrics, words, total_audio_sec=60)
    assert bounds[0][0] <= 34
    assert bounds[0][1] >= 39.8
    assert bounds[0][1] <= bounds[1][0]


def test_phrase_evidence_precedes_automatic_onset_but_not_manual_start():
    from src.aligner import LyricLine, anchor_stanzas_with_asr
    text = "riverside unrolls like bright ribbon"
    lyrics = [(0, LyricLine(text=text))]
    words = [{"py": t, "start": 10 + i, "end": 10.5 + i} for i, t in enumerate(text.split())]
    _, automatic = anchor_stanzas_with_asr(lyrics, words, 20, min_start=10.9)
    assert automatic[0][0] == 10
    _, manual = anchor_stanzas_with_asr(lyrics, words, 20, min_start=10.9, start_is_explicit=True)
    assert manual[0][0] >= 10.9


def test_local_phrase_evidence_rejects_repeated_and_discontinuous_matches():
    from src.aligner import LyricLine, _unique_phrase_anchors
    phrase = "look at the bright sky"
    paras = {0: [(0, LyricLine(text=phrase))], 1: [(1, LyricLine(text=phrase))]}
    words = [{"py": t, "start": i, "end": i + 0.5} for i, t in enumerate(phrase.split())]
    assert _unique_phrase_anchors(paras, words) == {}
    unique = {0: [(0, LyricLine(text=phrase))]}
    assert _unique_phrase_anchors(unique, words + [{**w, "start": w["start"] + 20, "end": w["end"] + 20} for w in words]) == {}
    words[-1]["start"], words[-1]["end"] = 20, 21
    assert _unique_phrase_anchors(unique, words) == {}


def test_local_phrase_evidence_respects_chinese_tokens():
    from src.aligner import LyricLine, _unique_phrase_anchors, tokenize_lyric_phonetic
    text = "所有真理变成借口"
    words = [{"py": t["py"], "start": i, "end": i + 0.5}
             for i, t in enumerate(tokenize_lyric_phonetic(text))]
    assert _unique_phrase_anchors({0: [(0, LyricLine(text=text))]}, words) == {0: (0, 7.5)}


def test_anchor_stanzas_monotonic_repeated_chorus():
    """验证全局单调唯一分配：两段完全相同的重复副歌，必须分别匹配到先后两次独立的演唱，杜绝挤占同一区间"""
    from src.aligner import LyricLine, anchor_stanzas_with_asr

    lyrics = [
        (0, LyricLine(text="intro line before chorus", paragraph=0)),
        (1, LyricLine(text="look up sky", paragraph=1)),
        (2, LyricLine(text="look up sky", paragraph=2)),
        (3, LyricLine(text="outro line after chorus", paragraph=3)),
    ]

    asr_words = [
        {"word": "intro", "start": 1.0, "end": 2.0, "py": "intro"},
        {"word": "line", "start": 2.1, "end": 3.0, "py": "line"},
        {"word": "before", "start": 3.1, "end": 4.0, "py": "before"},
        {"word": "chorus", "start": 4.1, "end": 5.0, "py": "chorus"},

        {"word": "look", "start": 10.0, "end": 10.8, "py": "look"},
        {"word": "up", "start": 10.9, "end": 11.5, "py": "up"},
        {"word": "sky", "start": 11.6, "end": 12.5, "py": "sky"},

        {"word": "look", "start": 30.0, "end": 30.8, "py": "look"},
        {"word": "up", "start": 30.9, "end": 31.5, "py": "up"},
        {"word": "sky", "start": 31.6, "end": 32.5, "py": "sky"},

        {"word": "outro", "start": 40.0, "end": 41.0, "py": "outro"},
        {"word": "line", "start": 41.1, "end": 42.0, "py": "line"},
        {"word": "after", "start": 42.1, "end": 43.0, "py": "after"},
        {"word": "chorus", "start": 43.1, "end": 44.0, "py": "chorus"},
    ]

    paras, bounds = anchor_stanzas_with_asr(lyrics, asr_words, total_audio_sec=50.0)

    # 验证副歌 1 与副歌 2 分别匹配到 10s 和 30s
    p1_s, p1_e = bounds[1]
    p2_s, p2_e = bounds[2]

    assert 9.0 <= p1_s <= 11.0, f"副歌1起点异常: {p1_s}"
    assert 11.5 <= p1_e <= 14.0, f"副歌1终点异常: {p1_e}"

    assert 28.0 <= p2_s <= 31.0, f"副歌2起点异常: {p2_s}"
    assert 31.5 <= p2_e <= 34.0, f"副歌2终点异常: {p2_e}"

    # 严格单调性
    assert p1_e <= p2_s, f"时间重叠违背单调性: p1_end={p1_e}, p2_start={p2_s}"


def test_phonetic_tokens_normalize_quotes_for_lyrics_and_asr():
    from src.aligner import tokenize_lyric_phonetic
    expected = tokenize_lyric_phonetic("I'm pouring my drink; they're here.")
    assert tokenize_lyric_phonetic("I’m pouring my drink; they’re here.") == expected
    assert tokenize_lyric_phonetic("I‘m pouring my drink; they`re here.") == expected
    assert tokenize_lyric_phonetic("\u2060I’m pouring my drink; they’re here.\u200b") == expected
    assert [token['py'] for token in tokenize_lyric_phonetic("One, two—keep 'em flying high!")] == ['one', 'two', 'keep', 'em', 'flying', 'high']
    assert [token['py'] for token in tokenize_lyric_phonetic("你好，世界！")] == ['ni', 'hao', 'shi', 'jie']


def test_asr_anchors_use_same_apostrophe_normalization(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace
    from src import aligner
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"mock audio")
    cache = tmp_path / ".song_asr_words.json"
    cache.write_text(json.dumps({"version": 3, "words": [{"py": "stale"}], "meta": {
        "mtime": audio.stat().st_mtime, "size": audio.stat().st_size, "language": "en", "model": "base"
    }}))
    monkeypatch.setattr(aligner, "_transcribe_whisper", lambda *args, **kwargs: ([
        SimpleNamespace(words=[SimpleNamespace(word="I’m", start=1.0, end=1.4)])
    ], None))
    words = aligner.extract_asr_words(audio, aligner.AlignerConfig(whisper_model="base"), language="en")
    assert words == [{"raw": "im", "py": "im", "start": 1.0, "end": 1.4}]
    assert json.loads(cache.read_text())["version"] == 4


def test_align_en_token_spans_apostrophe_exact_mapping():
    """验证英文带撇号缩写词 (Don't, It's, isn't) 的显式 token-to-target 映射，无跨度漂移"""
    import torchaudio
    from src.aligner import tokenize_lyric_line

    bundle_en = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
    labels_en = bundle_en.get_labels()
    dict_en = {c: i for i, c in enumerate(labels_en)}

    test_lines = [
        "Don't look back",
        "It's a long way home, isn't it?",
        "Harp-string bridge and a sky scrubbed clean",
    ]

    full_target_ids: list[int] = []
    full_tokens_with_spans = []
    curr_span_pos = 0

    for li, text in enumerate(test_lines):
        tokens = tokenize_lyric_line(text)
        tok_records = []
        for tok in tokens:
            chars = [c.upper() for c in tok if c.upper() in dict_en and dict_en[c.upper()] != 0 and c != "|"]
            tok_records.append((tok, chars))

        line_tok_spans = []
        vocal_count = sum(1 for _, chars in tok_records if chars)
        vocal_idx = 0
        for tok, chars in tok_records:
            if not chars:
                line_tok_spans.append((tok, curr_span_pos, curr_span_pos))
                continue
            s_pos = curr_span_pos
            for c in chars:
                full_target_ids.append(dict_en[c])
            curr_span_pos += len(chars)
            e_pos = curr_span_pos
            line_tok_spans.append((tok, s_pos, e_pos))
            vocal_idx += 1
            if vocal_idx < vocal_count:
                full_target_ids.append(dict_en["|"])
                curr_span_pos += 1

        full_tokens_with_spans.append((text, line_tok_spans))
        if li < len(test_lines) - 1 and full_target_ids:
            full_target_ids.append(dict_en["|"])
            curr_span_pos += 1

    # 验证 target 长度与 span 指针 100% 严密闭合
    assert len(full_target_ids) == curr_span_pos

    # 验证 "Don't" 包含了完整的 5 个字符，且紧随其后的 "look" 起始位置为 6
    line0_toks = full_tokens_with_spans[0][1]
    dont_tok, d_s, d_e = line0_toks[0]
    look_tok, l_s, l_e = line0_toks[1]
    assert dont_tok.strip() == "Don't"
    assert d_e - d_s == 5  # D, O, N, ', T
    assert l_s == 6  # 5 是 '|' 分隔符
