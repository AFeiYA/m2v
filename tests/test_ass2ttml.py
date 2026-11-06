import json
from pathlib import Path
import xml.etree.ElementTree as ET

from src.ass2ttml import (
    alignment_to_ttml,
    ass_text_to_ttml,
    convert_alignment_to_ttml,
    escape_xml,
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
    assert 'begin="00:00:01.500"' in ttml
    assert "Line one" in ttml
    assert "Line two second part" in ttml
