import json
from pathlib import Path
import xml.etree.ElementTree as ET

from src.ass2ttml import (
    alignment_to_ttml,
    ass_text_to_ttml,
    convert_alignment_to_ttml,
    detect_lyric_lang,
    escape_xml,
    make_content_disposition,
    normalize_ttml_lang,
    sanitize_download_filename,
    seconds_to_ttml_time,
)


def test_seconds_to_ttml_time() -> None:
    assert seconds_to_ttml_time(0.0) == "00:00:00.000"
    assert seconds_to_ttml_time(5.012) == "00:00:05.012"
    assert seconds_to_ttml_time(65.43) == "00:01:05.430"
    assert seconds_to_ttml_time(3661.25) == "01:01:01.250"


def test_escape_xml() -> None:
    assert escape_xml("Rock & Roll <Live> '2026' \"Special\"") == "Rock &amp; Roll &lt;Live&gt; &apos;2026&apos; &quot;Special&quot;"


def test_alignment_to_ttml_valid_xml() -> None:
    alignment = {
        "title": "海风吹拂",
        "artist": "测试歌手",
        "lines": [
            {
                "start": 6.20,
                "end": 10.50,
                "text": "海风轻轻",
                "words": [
                    {"word": "海", "start": 6.20, "end": 7.10},
                    {"word": "风", "start": 7.10, "end": 8.00},
                    {"word": "轻", "start": 8.00, "end": 9.20},
                    {"word": "轻", "start": 9.20, "end": 10.50},
                ],
            },
            {
                "start": 12.00,
                "end": 16.00,
                "text": "飘向远方",
            },
        ],
    }

    ttml = alignment_to_ttml(alignment)
    assert ttml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert '<tt xmlns="http://www.w3.org/ns/ttml"' in ttml
    assert 'xml:lang="zh-Hans"' in ttml
    assert '<ttm:title>海风吹拂</ttm:title>' in ttml
    assert '<ttm:agent type="person" xml:id="v1">测试歌手</ttm:agent>' in ttml

    # Verify XML parsability
    root = ET.fromstring(ttml.split("?>", 1)[1].strip())
    ns = {"tt": "http://www.w3.org/ns/ttml", "ttm": "http://www.w3.org/ns/ttml#metadata"}
    title_elem = root.find(".//ttm:title", ns)
    assert title_elem is not None
    assert title_elem.text == "海风吹拂"

    body = root.find("tt:body", ns)
    assert body is not None
    assert body.attrib.get("dur") == "00:00:16.000"

    p_elems = root.findall(".//tt:p", ns)
    assert len(p_elems) == 2
    assert p_elems[0].attrib.get("begin") == "00:00:06.200"
    assert p_elems[0].attrib.get("end") == "00:00:10.500"

    # Line 1 has word spans
    spans = p_elems[0].findall("tt:span", ns)
    assert len(spans) == 4
    assert spans[0].text == "海"
    assert spans[0].attrib.get("begin") == "00:00:06.200"
    assert spans[3].text == "轻"
    assert spans[3].attrib.get("end") == "00:00:10.500"

    # Line 2 has no word spans, plain text
    assert p_elems[1].text == "飘向远方"


def test_convert_alignment_to_ttml_file(tmp_path: Path) -> None:
    data = {
        "title": "File Song",
        "artist": "Artist A",
        "lines": [{"start": 2.0, "end": 4.5, "text": "Hello world"}],
    }
    json_path = tmp_path / "align.json"
    json_path.write_text(json.dumps(data), encoding="utf-8")

    out_file = convert_alignment_to_ttml(json_path)
    assert out_file.exists()
    assert out_file.suffix == ".ttml"
    content = out_file.read_text(encoding="utf-8")
    assert "<ttm:title>File Song</ttm:title>" in content
    assert 'xml:lang="en"' in content
    assert 'begin="00:00:02.000"' in content


def test_ass_text_to_ttml() -> None:
    ass_sample = """[Script Info]
Title: Sample
ScriptType: v4.00+

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.50,0:00:04.20,Default,,0,0,0,,{\\k20}Line{\\k30} one
Dialogue: 0,0:00:05.00,0:00:08.50,Default,,0,0,0,,Line two\\Nsecond part
"""
    ttml = ass_text_to_ttml(ass_sample, title="ASS Song", artist="ASS Singer")
    assert "<ttm:title>ASS Song</ttm:title>" in ttml
    assert 'xml:lang="en"' in ttml
    assert 'begin="00:00:01.500"' in ttml
    assert "Line one" in ttml
    assert "Line two second part" in ttml


def test_detect_lyric_lang_simplified() -> None:
    text = "海风轻轻吹过海岸，我们在沙滩漫步，随风飘向远方"
    assert detect_lyric_lang(text) == "zh-Hans"


def test_detect_lyric_lang_traditional() -> None:
    text = "海風輕輕吹過海岸，我們在沙灘漫步，隨風飄向遠方"
    assert detect_lyric_lang(text) == "zh-Hant"


def test_detect_lyric_lang_english() -> None:
    text = "Yesterday all my troubles seemed so far away, now it looks as though they are here to stay"
    assert detect_lyric_lang(text) == "en"


def test_detect_lyric_lang_mixed() -> None:
    # Predominantly Latin
    mixed_en = "I can see clearly now the rain is gone. 海风"
    assert detect_lyric_lang(mixed_en) == "en"

    # Predominantly Simplified Chinese
    mixed_zh_simp = "海风轻轻吹过海岸，夜色茫茫，我们在沙滩上跳舞歌唱。Hello!"
    assert detect_lyric_lang(mixed_zh_simp) == "zh-Hans"

    # Predominantly Traditional Chinese
    mixed_zh_trad = "海風輕輕吹過海岸，夜色茫茫，我們在沙灘上跳舞歌唱。Hello!"
    assert detect_lyric_lang(mixed_zh_trad) == "zh-Hant"


def test_detect_lyric_lang_fallbacks_and_structures() -> None:
    # Empty or whitespace
    assert detect_lyric_lang("") == "zh-Hans"
    assert detect_lyric_lang("   \n\t") == "zh-Hans"

    # Non-alphabetic / instrumental
    assert detect_lyric_lang("123 456 !!! ???") == "zh-Hans"

    # Structured dict input
    align_dict = {
        "lines": [
            {"text": "海風輕拂"},
            {"words": [{"word": "輕"}, {"word": "輕"}]},
        ]
    }
    assert detect_lyric_lang(align_dict) == "zh-Hant"


def test_normalize_ttml_lang() -> None:
    assert normalize_ttml_lang("zh-CN") == "zh-Hans"
    assert normalize_ttml_lang("zh_cn") == "zh-Hans"
    assert normalize_ttml_lang("zh") == "zh-Hans"
    assert normalize_ttml_lang("zh-Hans") == "zh-Hans"
    assert normalize_ttml_lang("zh-TW") == "zh-Hant"
    assert normalize_ttml_lang("zh-HK") == "zh-Hant"
    assert normalize_ttml_lang("zh-Hant") == "zh-Hant"
    assert normalize_ttml_lang("en") == "en"
    assert normalize_ttml_lang("en-US") == "en-US"
    assert normalize_ttml_lang("en-GB") == "en-GB"
    assert normalize_ttml_lang(None) == ""
    assert normalize_ttml_lang("") == ""


def test_alignment_to_ttml_language_overrides() -> None:
    # Explicit lang parameter overrides detection
    align_zh = {"lines": [{"text": "海风吹拂"}]}
    ttml = alignment_to_ttml(align_zh, lang="en")
    assert 'xml:lang="en"' in ttml

    # Explicit legacy zh-CN is normalized to Apple spec zh-Hans
    ttml_norm = alignment_to_ttml(align_zh, lang="zh-CN")
    assert 'xml:lang="zh-Hans"' in ttml_norm

    # Auto detect for English
    align_en = {"lines": [{"text": "Love is in the air tonight"}]}
    ttml_auto_en = alignment_to_ttml(align_en)
    assert 'xml:lang="en"' in ttml_auto_en

    # Auto detect for Traditional Chinese
    align_trad = {"lines": [{"text": "海風輕輕飄向遠方"}]}
    ttml_auto_trad = alignment_to_ttml(align_trad)
    assert 'xml:lang="zh-Hant"' in ttml_auto_trad


def test_make_content_disposition() -> None:
    header = make_content_disposition("海风吹拂", "ttml")
    # Verify latin-1 encodability (Starlette/HTTP compliance)
    header.encode("latin-1")
    assert 'filename="lyrics.ttml"' in header
    assert "filename*=UTF-8''%E6%B5%B7%E9%A3%8E%E5%90%B9%E6%8B%82.ttml" in header

    ascii_header = make_content_disposition("Summer_Breeze", "ttml")
    ascii_header.encode("latin-1")
    assert 'filename="Summer_Breeze.ttml"' in ascii_header
    assert "filename*=UTF-8''Summer_Breeze.ttml" in ascii_header

    sanitized = sanitize_download_filename('Test / Song: "2026"')
    assert "/" not in sanitized
    assert '"' not in sanitized
    assert ":" not in sanitized


def test_main_cli(tmp_path: Path) -> None:
    import sys
    from unittest.mock import patch
    from src.ass2ttml import main

    in_json = tmp_path / "song.json"
    in_json.write_text(
        json.dumps({
            "title": "My English Song",
            "lines": [{"start": 1.0, "end": 4.0, "text": "Dancing in the moonlight"}],
        }),
        encoding="utf-8",
    )
    out_ttml = tmp_path / "song.ttml"

    with patch.object(sys, "argv", ["ass2ttml", str(in_json), "-o", str(out_ttml)]):
        assert main() == 0
    content = out_ttml.read_text(encoding="utf-8")
    assert 'xml:lang="en"' in content

    # Test override
    with patch.object(sys, "argv", ["ass2ttml", str(in_json), "-o", str(out_ttml), "--lang", "zh-Hant"]):
        assert main() == 0
    content_override = out_ttml.read_text(encoding="utf-8")
    assert 'xml:lang="zh-Hant"' in content_override

