import json
from pathlib import Path

from src.ass2lrc import (
    alignment_to_lrc,
    ass_text_to_lrc,
    convert_alignment_to_lrc,
    convert_ass_to_lrc,
    seconds_to_lrc_time,
)


def test_seconds_to_lrc_time() -> None:
    assert seconds_to_lrc_time(0.0) == "00:00.00"
    assert seconds_to_lrc_time(5.01) == "00:05.01"
    assert seconds_to_lrc_time(65.43) == "01:05.43"
    assert seconds_to_lrc_time(3661.25) == "61:01.25"


def test_alignment_to_lrc_standard() -> None:
    alignment = {
        "title": "Summer Song",
        "artist": "Fovea Artist",
        "lines": [
            {
                "start": 5.01,
                "end": 10.20,
                "text": "Hello world",
                "words": [
                    {"word": "Hello", "start": 5.01, "end": 7.00},
                    {"word": "world", "start": 7.10, "end": 10.20},
                ],
            },
            {
                "start": 12.50,
                "end": 18.00,
                "text": "Singing in the rain",
            },
        ],
    }

    lrc = alignment_to_lrc(alignment)
    lines = lrc.strip().splitlines()

    assert lines[0] == "[ti:Summer Song]"
    assert lines[1] == "[ar:Fovea Artist]"
    assert lines[2] == "[by:Fovea MV]"
    assert lines[3] == "[00:05.01]Hello world"
    assert lines[4] == "[00:12.50]Singing in the rain"


def test_alignment_to_lrc_enhanced() -> None:
    alignment = {
        "lines": [
            {
                "start": 1.50,
                "end": 4.00,
                "text": "One Two",
                "words": [
                    {"word": "One", "start": 1.50, "end": 2.50},
                    {"word": "Two", "start": 2.60, "end": 4.00},
                ],
            }
        ]
    }
    lrc = alignment_to_lrc(alignment, enhanced=True)
    assert "[00:01.50]<00:01.50>One<00:02.60>Two" in lrc


def test_convert_alignment_to_lrc_file(tmp_path: Path) -> None:
    json_path = tmp_path / "song_alignment.json"
    json_path.write_text(
        json.dumps({
            "title": "Test Title",
            "lines": [
                {"start": 10.05, "end": 15.00, "text": "First line of song"}
            ]
        }),
        encoding="utf-8",
    )
    output_lrc = convert_alignment_to_lrc(json_path)
    assert output_lrc.exists()
    assert output_lrc.name == "song_alignment.lrc"
    assert "[00:10.05]First line of song" in output_lrc.read_text(encoding="utf-8")


def test_ass_text_to_lrc_converts_karaoke_lines() -> None:
    ass_text = """[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:05.01,0:00:14.61,Karaoke,,0,0,0,,{\\k40}我{\\k40}没{\\k40}有{\\k40}大{\\k40}脑
Dialogue: 0,0:01:01.63,0:01:08.28,Karaoke,,0,0,0,,第一行\\N第二行
"""

    assert ass_text_to_lrc(ass_text) == [
        "[00:05.01]我没有大脑",
        "[01:01.63]第一行 第二行",
    ]


def test_convert_ass_to_lrc_writes_output_file(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.ass"
    input_path.write_text(
        """[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:14.61,0:00:17.01,Karaoke,,0,0,0,,{\\k40}V{\\k40}e{\\k40}r{\\k40}s{\\k40}e
""",
        encoding="utf-8",
    )

    output_path = convert_ass_to_lrc(input_path)

    assert output_path.read_text(encoding="utf-8") == "[00:14.61]Verse\n"


def test_alignment_to_lrc_traditional_script() -> None:
    align = {
        "title": "海风吹拂",
        "artist": "歌手",
        "lines": [{"start": 2.5, "text": "海风轻轻吹过海岸"}],
    }
    lrc = alignment_to_lrc(align, lang="zh-Hant")
    assert "[ti:海風吹拂]" in lrc
    assert "[ar:歌手]" in lrc
    assert "[00:02.50]海風輕輕吹過海岸" in lrc


def test_alignment_to_lrc_dual_line_pinyin() -> None:
    align = {
        "title": "拼音测试",
        "lines": [{"start": 2.5, "text": "海风轻轻吹过海岸"}],
    }
    lrc = alignment_to_lrc(align, pinyin=True)
    lines = lrc.strip().splitlines()
    # Pinyin line precedes the Chinese lyric line
    assert "[00:02.50]hǎi fēng qīng qīng chuī guò hǎi àn" in lines
    assert "[00:02.50]海风轻轻吹过海岸" in lines
