from pathlib import Path

from src.ass2lrc import ass_text_to_lrc, convert_ass_to_lrc


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