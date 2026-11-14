"""Tests for Marble Music MIDI note extraction and /api/motion/marble endpoints."""
import struct
from pathlib import Path
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient
from src.local_editor import app
from src.midi_converter import extract_marble_notes
from src.storyboard_schema import AlignedLine, AlignmentProject


def _varlen(val: int) -> bytes:
    buf = [val & 0x7F]
    val >>= 7
    while val:
        buf.append((val & 0x7F) | 0x80)
        val >>= 7
    return bytes(reversed(buf))


def _build_test_midi(path: Path) -> None:
    # Format 1, 2 tracks, 480 ticks per quarter note (120 BPM = 500000 us/beat -> 1 beat = 0.5s)
    header = b"MThd" + struct.pack(">IHHH", 6, 1, 2, 480)

    # Track 0: tempo 120 BPM + melody C5 (72) at t=0..0.5s, E5 (76) at t=0.5..1.0s
    t0 = bytearray()
    t0 += _varlen(0) + b"\xFF\x51\x03" + struct.pack(">I", 500000)[1:]
    t0 += _varlen(0) + bytes([0x90, 72, 100])
    t0 += _varlen(480) + bytes([0x80, 72, 0])
    t0 += _varlen(0) + bytes([0x90, 76, 110])
    t0 += _varlen(480) + bytes([0x80, 76, 0])
    t0 += _varlen(0) + b"\xFF\x2F\x00"
    trk0 = b"MTrk" + struct.pack(">I", len(t0)) + bytes(t0)

    # Track 1: channel 9 percussion kick (36) at t=0..0.25s
    t1 = bytearray()
    t1 += _varlen(0) + bytes([0x99, 36, 120])
    t1 += _varlen(240) + bytes([0x89, 36, 0])
    t1 += _varlen(0) + b"\xFF\x2F\x00"
    trk1 = b"MTrk" + struct.pack(">I", len(t1)) + bytes(t1)

    path.write_bytes(header + trk0 + trk1)


def test_extract_marble_notes_multitrack(tmp_path):
    midi_path = tmp_path / "demo.mid"
    _build_test_midi(midi_path)

    notes = extract_marble_notes(midi_path)
    assert len(notes) == 3
    roles = {n["role"] for n in notes}
    assert "melody" in roles
    assert "percussion" in roles

    melody = [n for n in notes if n["role"] == "melody"]
    assert melody[0]["pitch"] == 72
    assert melody[0]["time"] == pytest.approx(0.0, abs=0.01)
    assert melody[1]["pitch"] == 76
    assert melody[1]["time"] == pytest.approx(0.5, abs=0.01)


def test_marble_settings_notes_and_upload_endpoints(tmp_path):
    song_dir = tmp_path / "marble_song"
    song_dir.mkdir(parents=True)
    json_path = song_dir / "marble_song_alignment.json"
    proj = AlignmentProject(
        title="Marble Song",
        duration=12.0,
        lines=[AlignedLine(text="Hello marble", start=1.0, end=4.0)],
    )
    proj.save_json(json_path)

    app.state.scan_dir = tmp_path
    client = TestClient(app)
    pid = str(json_path.relative_to(tmp_path))

    # 1. Default settings
    res = client.get("/api/motion/marble", params={"project_id": pid})
    assert res.status_code == 200
    assert res.json()["settings"]["theme"] == "amber"
    assert res.json()["settings"]["tracks"] == "dual"

    # 2. Save updated settings
    updated = {
        "version": "marble-stage-v1",
        "aspect": "9:16",
        "height": 720,
        "seed": 99,
        "density": "dense",
        "tracks": "single",
        "camera": "isometric",
        "theme": "christmas",
        "offset": 0.05,
        "subtitles": False,
    }
    res = client.put("/api/motion/marble", json={"project_id": pid, "settings": updated})
    assert res.status_code == 200
    assert res.json()["settings"]["theme"] == "christmas"

    # 3. Fallback when no MIDI exists
    res = client.get("/api/motion/marble/notes", params={"project_id": pid})
    assert res.status_code == 200
    assert res.json()["source"] == "audio_analysis"
    assert res.json()["notes"] == []

    # 4. Upload invalid MIDI rejected
    res = client.post(
        "/api/motion/marble/midi",
        data={"project_id": pid},
        files={"file": ("bad.mid", b"NOT_MIDI", "audio/midi")},
    )
    assert res.status_code == 422

    # 5. Upload valid MIDI and read notes
    midi_path = tmp_path / "upload.mid"
    _build_test_midi(midi_path)
    res = client.post(
        "/api/motion/marble/midi",
        data={"project_id": pid},
        files={"file": ("upload.mid", midi_path.read_bytes(), "audio/midi")},
    )
    assert res.status_code == 200
    assert res.json()["source"] == "midi"
    assert len(res.json()["notes"]) == 3

    res = client.get("/api/motion/marble/notes", params={"project_id": pid})
    assert res.status_code == 200
    assert res.json()["source"] == "midi"
    assert len(res.json()["notes"]) == 3
