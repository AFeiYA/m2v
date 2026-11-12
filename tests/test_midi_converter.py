"""
Unit tests for MIDI Lyrics Converter & Alignment Extractor (src.midi_converter).
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from src.midi_converter import (
    MidiLyricsConverter,
    convert_midi_to_alignment,
    is_midi_file,
)
from src.storyboard_schema import AlignmentProject as AlignmentResult


def _build_varlen(val: int) -> bytes:
    buf = bytearray()
    buf.append(val & 0x7F)
    val >>= 7
    while val > 0:
        buf.append(0x80 | (val & 0x7F))
        val >>= 7
    return bytes(reversed(buf))


def _create_synthetic_midi(tmp_path: Path, include_lyrics: bool = True) -> Path:
    """Creates a minimal valid Format 1 Standard MIDI file for testing."""
    midi_file = tmp_path / "test_synthetic.mid"

    # Track 0: Tempo and Markers
    # division = 480 ticks/beat
    tr0 = bytearray()
    # tick 0: set tempo 500,000 us/beat (120 BPM)
    tr0.extend(_build_varlen(0))
    tr0.extend(b"\xFF\x51\x03\x07\xA1\x20")  # 500,000
    # tick 0: Marker 'Intro'
    tr0.extend(_build_varlen(0))
    tr0.extend(b"\xFF\x06\x05Intro")
    # tick 1920 (1 bar later): Marker 'Verse 1'
    tr0.extend(_build_varlen(1920))
    tr0.extend(b"\xFF\x06\x07Verse 1")
    # end of track
    tr0.extend(_build_varlen(0))
    tr0.extend(b"\xFF\x2F\x00")

    # Track 1: Notes and Lyrics
    tr1 = bytearray()
    tr1.extend(_build_varlen(0))
    tr1.extend(b"\xFF\x03\x0BLead Vocals")

    if include_lyrics:
        # Note 1: at tick 1920, pitch 60, vel 100, Lyric "Hel-"
        tr1.extend(_build_varlen(1920))
        tr1.extend(b"\xFF\x05\x04Hel-")
        tr1.extend(_build_varlen(0))
        tr1.extend(b"\x90\x3C\x64")  # Note on C4
        # Note off at tick 1920 + 240
        tr1.extend(_build_varlen(240))
        tr1.extend(b"\x80\x3C\x40")

        # Note 2: at tick 2160, pitch 62, vel 100, Lyric "lo "
        tr1.extend(_build_varlen(0))
        tr1.extend(b"\xFF\x05\x03lo ")
        tr1.extend(_build_varlen(0))
        tr1.extend(b"\x90\x3E\x64")  # Note on D4
        tr1.extend(_build_varlen(240))
        tr1.extend(b"\x80\x3E\x40")

        # Note 3: at tick 2400, pitch 64, vel 100, Lyric "World!\n"
        tr1.extend(_build_varlen(0))
        tr1.extend(b"\xFF\x05\x07World!\n")
        tr1.extend(_build_varlen(0))
        tr1.extend(b"\x90\x40\x64")  # Note on E4
        tr1.extend(_build_varlen(480))
        tr1.extend(b"\x80\x40\x40")

    # end of track
    tr1.extend(_build_varlen(0))
    tr1.extend(b"\xFF\x2F\x00")

    header = struct.pack(">4sIHHH", b"MThd", 6, 1, 2, 480)
    trk0_hdr = struct.pack(">4sI", b"MTrk", len(tr0))
    trk1_hdr = struct.pack(">4sI", b"MTrk", len(tr1))

    midi_file.write_bytes(header + trk0_hdr + tr0 + trk1_hdr + tr1)
    return midi_file


def test_is_midi_file(tmp_path: Path):
    assert not is_midi_file(tmp_path / "non_existent.mid")

    dummy_txt = tmp_path / "test.txt"
    dummy_txt.write_text("Hello world")
    assert not is_midi_file(dummy_txt)

    synthetic = _create_synthetic_midi(tmp_path)
    assert is_midi_file(synthetic)


def test_convert_synthetic_midi_to_alignment(tmp_path: Path):
    synthetic = _create_synthetic_midi(tmp_path, include_lyrics=True)
    alignment = convert_midi_to_alignment(synthetic, title="Hello World Song")

    assert isinstance(alignment, AlignmentResult)
    assert alignment.title == "Hello World Song"
    assert alignment.duration > 0
    assert len(alignment.sections) == 2
    assert alignment.sections[0].name == "Intro"
    assert alignment.sections[1].name == "Verse 1"

    assert len(alignment.lines) == 1
    line = alignment.lines[0]
    assert line.text == "Hello World!"
    assert line.section == "Verse 1"
    assert len(line.words) == 2

    w1 = line.words[0]
    assert w1.word == "Hello"
    assert w1.syllables is not None
    assert len(w1.syllables) == 2
    assert w1.syllables[0].text == "Hel-"
    assert w1.syllables[1].text == "lo"

    w2 = line.words[1]
    assert w2.word == "World!"


def test_midi_without_lyrics_raises_error(tmp_path: Path):
    no_lyrics = _create_synthetic_midi(tmp_path, include_lyrics=False)
    with pytest.raises(ValueError, match="No lyrics or vocal text"):
        convert_midi_to_alignment(no_lyrics)


def test_jingle_bells_real_midi():
    real_midi = Path("/Users/luca/Downloads/jingle_bells_full_1857_arrangement.mid")
    if not real_midi.exists():
        pytest.skip("Test file not present on this machine")

    alignment = convert_midi_to_alignment(real_midi)
    assert alignment.duration > 150.0
    assert len(alignment.sections) == 11
    assert alignment.sections[1].name == "Verse 1"
    assert alignment.sections[2].name == "Chorus 1"

    # Verifies all 55 standard lines are extracted
    assert len(alignment.lines) == 55
    assert "Dashing through the snow" in alignment.lines[0].text
    assert "one-horse open sleigh" in alignment.lines[1].text
    assert "Jingle bells" in alignment.lines[7].text

    # Verifies serialization works
    json_path = Path("/tmp/test_jingle_bells_align.json")
    alignment.save_json(json_path)
    assert json_path.exists()
    restored = AlignmentResult.load_json(json_path)
    assert len(restored.lines) == 55
    assert restored.lines[0].text == alignment.lines[0].text
