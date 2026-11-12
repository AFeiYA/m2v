"""
MIDI Lyrics Converter & Alignment Extractor
Extracts word- and syllable-level aligned lyrics, sections, and melody notes
directly from Standard MIDI Files (.mid / .kar) into suno2MV's native AlignmentResult.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any, BinaryIO

from src.storyboard_schema import (
    AlignedLine,
    AlignmentProject as AlignmentResult,
    MusicSection,
    SyllableTimestamp,
    WordTimestamp,
)
from src.utils import log


def parse_varlen(stream: BinaryIO) -> int:
    """Reads a variable-length quantity from a binary MIDI stream."""
    value = 0
    while True:
        raw = stream.read(1)
        if not raw:
            break
        b = raw[0]
        value = (value << 7) | (b & 0x7F)
        if not (b & 0x80):
            break
    return value


def is_midi_file(path: str | Path) -> bool:
    """Checks whether the file has a .mid/.midi/.kar extension or starts with 'MThd'."""
    p = Path(path)
    if not p.is_file():
        return False
    if p.suffix.lower() in (".mid", ".midi", ".kar"):
        return True
    try:
        with open(p, "rb") as f:
            return f.read(4) == b"MThd"
    except Exception:
        return False


class MidiLyricsConverter:
    """
    Parses Standard MIDI Files (Type 0 and Type 1) containing embedded lyrics/text
    and structure markers, outputting a fully conformant AlignmentResult object.
    """

    def __init__(self, midi_path: str | Path):
        self.midi_path = Path(midi_path).resolve()
        if not self.midi_path.exists():
            raise FileNotFoundError(f"MIDI file not found: {self.midi_path}")

        self.format: int = 1
        self.division: int = 480
        self.tempo_changes: list[tuple[int, int]] = []  # (tick, us_per_quarter)
        self.markers: list[tuple[int, str]] = []  # (tick, text)
        self.tracks_raw: list[bytes] = []
        self.track_names: list[str] = []
        self._load_smf()

    def _load_smf(self) -> None:
        """Parses header and extracts raw tracks."""
        with open(self.midi_path, "rb") as f:
            header = f.read(14)
            if len(header) < 14 or header[:4] != b"MThd":
                raise ValueError(f"Invalid MIDI header in {self.midi_path}")

            _, fmt, num_tracks, division = struct.unpack(">IHHH", header[4:14])
            self.format = fmt
            self.division = division if division > 0 else 480

            self.tracks_raw = []
            for _ in range(num_tracks):
                trk_header = f.read(8)
                if len(trk_header) < 8 or trk_header[:4] != b"MTrk":
                    break
                trk_len = struct.unpack(">I", trk_header[4:8])[0]
                trk_data = f.read(trk_len)
                self.tracks_raw.append(trk_data)

        # Parse global tempo map, markers, and track names
        for trk_data in self.tracks_raw:
            stream = io.BytesIO(trk_data)
            tick = 0
            running_status = None
            while stream.tell() < len(trk_data):
                dt = parse_varlen(stream)
                tick += dt
                b_raw = stream.read(1)
                if not b_raw:
                    break
                b = b_raw[0]
                if b & 0x80:
                    status = b
                else:
                    status = running_status
                    stream.seek(-1, io.SEEK_CUR)
                running_status = status

                if status == 0xFF:  # Meta event
                    mtype_raw = stream.read(1)
                    if not mtype_raw:
                        break
                    mtype = mtype_raw[0]
                    mlen = parse_varlen(stream)
                    mval = stream.read(mlen)
                    if mtype == 0x51 and len(mval) == 3:  # Set Tempo
                        us_per_beat = struct.unpack(">I", b"\x00" + mval)[0]
                        self.tempo_changes.append((tick, us_per_beat))
                    elif mtype == 0x06:  # Marker
                        m_text = mval.decode("utf-8", errors="ignore").strip()
                        if m_text:
                            self.markers.append((tick, m_text))
                    elif mtype == 0x03:  # Track Name
                        self.track_names.append(mval.decode("utf-8", errors="ignore").strip())
                elif status is not None and (status & 0xF0) in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                    stream.read(2)
                elif status is not None and (status & 0xF0) in (0xC0, 0xD0):
                    stream.read(1)
                elif status in (0xF0, 0xF7):  # SysEx
                    slen = parse_varlen(stream)
                    stream.read(slen)

        self.tempo_changes.sort(key=lambda x: x[0])
        if not self.tempo_changes:
            self.tempo_changes = [(0, 500000)]  # Default 120 BPM (500,000 us)
        self.markers.sort(key=lambda x: x[0])

    def tick_to_seconds(self, tick: int) -> float:
        """Converts an absolute MIDI tick value to precise floating-point seconds."""
        total_sec = 0.0
        for i, (t_tick, t_tempo) in enumerate(self.tempo_changes):
            next_tick = self.tempo_changes[i + 1][0] if i + 1 < len(self.tempo_changes) else float("inf")
            if tick <= t_tick:
                break
            seg_ticks = min(tick, next_tick) - t_tick
            sec_per_tick = (t_tempo / 1_000_000.0) / self.division
            total_sec += seg_ticks * sec_per_tick
            if tick <= next_tick:
                break
        return total_sec

    def _select_lyrics_track(self) -> int:
        """Finds track index containing the vocal melody and lyrics."""
        best_idx = 0
        max_lyrics = 0

        for idx, trk_data in enumerate(self.tracks_raw):
            stream = io.BytesIO(trk_data)
            lyrics_count = 0
            running_status = None
            while stream.tell() < len(trk_data):
                parse_varlen(stream)
                b_raw = stream.read(1)
                if not b_raw:
                    break
                b = b_raw[0]
                status = b if (b & 0x80) else running_status
                if not (b & 0x80):
                    stream.seek(-1, io.SEEK_CUR)
                running_status = status

                if status == 0xFF:
                    mtype_raw = stream.read(1)
                    if not mtype_raw:
                        break
                    mtype = mtype_raw[0]
                    mlen = parse_varlen(stream)
                    stream.seek(mlen, io.SEEK_CUR)
                    if mtype in (0x01, 0x05):  # Text or Lyrics
                        lyrics_count += 1
                elif status is not None and (status & 0xF0) in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                    stream.read(2)
                elif status is not None and (status & 0xF0) in (0xC0, 0xD0):
                    stream.read(1)
                elif status in (0xF0, 0xF7):
                    slen = parse_varlen(stream)
                    stream.seek(slen, io.SEEK_CUR)

            if lyrics_count > max_lyrics:
                max_lyrics = lyrics_count
                best_idx = idx

        return best_idx

    def extract_notes_and_lyrics(
        self, track_idx: int | None = None
    ) -> tuple[list[tuple[int, int, int, int]], list[tuple[int, str]]]:
        """
        Parses notes (start_tick, end_tick, pitch, vel) and raw lyrics (tick, text)
        from the specified or auto-detected vocal track.
        """
        if track_idx is None:
            track_idx = self._select_lyrics_track()

        trk_data = self.tracks_raw[track_idx]
        stream = io.BytesIO(trk_data)
        tick = 0
        running_status = None

        notes: list[tuple[int, int, int, int]] = []
        active_notes: dict[int, tuple[int, int]] = {}  # pitch -> (start_tick, vel)
        lyrics: list[tuple[int, str]] = []

        while stream.tell() < len(trk_data):
            dt = parse_varlen(stream)
            tick += dt
            b_raw = stream.read(1)
            if not b_raw:
                break
            b = b_raw[0]
            status = b if (b & 0x80) else running_status
            if not (b & 0x80):
                stream.seek(-1, io.SEEK_CUR)
            running_status = status

            if status == 0xFF:
                mtype_raw = stream.read(1)
                if not mtype_raw:
                    break
                mtype = mtype_raw[0]
                mlen = parse_varlen(stream)
                mval = stream.read(mlen)
                if mtype in (0x01, 0x05):  # Text or Lyrics
                    text = mval.decode("utf-8", errors="ignore")
                    # Ignore pure metadata/comment headers
                    if not text.startswith(("@", "#", "%")):
                        lyrics.append((tick, text))
            elif status is not None and (status & 0xF0) == 0x90:
                data = stream.read(2)
                if len(data) == 2:
                    pitch, vel = data
                    if vel > 0:
                        active_notes[pitch] = (tick, vel)
                    else:
                        if pitch in active_notes:
                            st, v = active_notes.pop(pitch)
                            notes.append((st, tick, pitch, v))
            elif status is not None and (status & 0xF0) == 0x80:
                data = stream.read(2)
                if len(data) == 2:
                    pitch, _ = data
                    if pitch in active_notes:
                        st, v = active_notes.pop(pitch)
                        notes.append((st, tick, pitch, v))
            elif status is not None and (status & 0xF0) in (0xA0, 0xB0, 0xE0):
                stream.read(2)
            elif status is not None and (status & 0xF0) in (0xC0, 0xD0):
                stream.read(1)
            elif status in (0xF0, 0xF7):
                slen = parse_varlen(stream)
                stream.read(slen)

        notes.sort(key=lambda x: x[0])
        lyrics.sort(key=lambda x: x[0])
        return notes, lyrics

    def to_alignment(
        self,
        audio_path: str | Path | None = None,
        title: str | None = None,
        track_idx: int | None = None,
    ) -> AlignmentResult:
        """
        Converts the MIDI file into a complete, validated AlignmentResult object
        with word-level and syllable-level timestamps, and music sections.
        """
        notes, raw_lyrics = self.extract_notes_and_lyrics(track_idx)
        if not raw_lyrics:
            raise ValueError(f"No lyrics or vocal text events found in {self.midi_path}")

        # Compute total song duration from all events
        max_tick = 0
        for trk_data in self.tracks_raw:
            stream = io.BytesIO(trk_data)
            tick = 0
            running_status = None
            while stream.tell() < len(trk_data):
                tick += parse_varlen(stream)
                b_raw = stream.read(1)
                if not b_raw:
                    break
                b = b_raw[0]
                status = b if (b & 0x80) else running_status
                if not (b & 0x80):
                    stream.seek(-1, io.SEEK_CUR)
                running_status = status
                if status == 0xFF:
                    stream.read(1)
                    mlen = parse_varlen(stream)
                    stream.seek(mlen, io.SEEK_CUR)
                elif status is not None and (status & 0xF0) in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                    stream.read(2)
                elif status is not None and (status & 0xF0) in (0xC0, 0xD0):
                    stream.read(1)
                elif status in (0xF0, 0xF7):
                    slen = parse_varlen(stream)
                    stream.seek(slen, io.SEEK_CUR)
            max_tick = max(max_tick, tick)

        total_duration = max(self.tick_to_seconds(max_tick), 1.0)

        # Build MusicSection objects from markers
        sections: list[MusicSection] = []
        for i, (m_tick, m_name) in enumerate(self.markers):
            st_sec = self.tick_to_seconds(m_tick)
            if i + 1 < len(self.markers):
                ed_sec = self.tick_to_seconds(self.markers[i + 1][0])
            else:
                ed_sec = total_duration
            sections.append(
                MusicSection(
                    name=m_name,
                    start=round(st_sec, 3),
                    end=round(ed_sec, 3),
                )
            )

        # Match lyrics with note durations
        syllables: list[dict[str, Any]] = []
        for l_tick, text in raw_lyrics:
            st_sec = self.tick_to_seconds(l_tick)
            # Find closest note
            matched_note = [n for n in notes if abs(n[0] - l_tick) <= 120]
            if matched_note:
                ed_sec = self.tick_to_seconds(matched_note[0][1])
            else:
                # Default half-beat duration
                ed_sec = self.tick_to_seconds(l_tick + int(self.division * 0.5))

            if ed_sec <= st_sec:
                ed_sec = st_sec + 0.15

            syllables.append(
                {
                    "start_tick": l_tick,
                    "start": round(st_sec, 3),
                    "end": round(ed_sec, 3),
                    "raw_text": text,
                }
            )

        # Syllable to Word Reassembly
        words: list[dict[str, Any]] = []
        curr_syls: list[dict[str, Any]] = []

        for syl in syllables:
            curr_syls.append(syl)
            raw = syl["raw_text"]
            stripped = raw.rstrip("\r\n")

            # In MIDI/Karaoke conventions:
            # Suffix '-' or '\' joins with the next syllable.
            is_continuation = stripped.endswith(("-", "\\"))
            has_newline = "\n" in raw or "\r" in raw or "/" in raw

            if not is_continuation or has_newline:
                # Assemble word
                syl_objs: list[SyllableTimestamp] = []
                word_parts: list[str] = []
                for s in curr_syls:
                    clean_s = s["raw_text"].rstrip("\r\n ").replace("/", "")
                    syl_objs.append(
                        SyllableTimestamp(
                            text=clean_s,
                            start=s["start"],
                            end=s["end"],
                        )
                    )
                    word_parts.append(clean_s)

                # Reassemble display word text
                assembled_text = ""
                for idx, part in enumerate(word_parts):
                    if part.endswith("-"):
                        # If hyphen is between compound words like "one-" + "horse", retain hyphen
                        base = part[:-1]
                        next_part = word_parts[idx + 1].rstrip(" ,.!?;:\r\n") if idx + 1 < len(word_parts) else ""
                        if base.lower() in ("one", "two", "three", "half", "well", "all") and len(next_part) >= 3:
                            assembled_text += part
                        else:
                            assembled_text += base
                    else:
                        assembled_text += part

                assembled_text = assembled_text.strip()
                if assembled_text:
                    words.append(
                        {
                            "word": assembled_text,
                            "start": curr_syls[0]["start"],
                            "end": curr_syls[-1]["end"],
                            "syllables": syl_objs if len(syl_objs) > 1 else None,
                            "has_newline": has_newline,
                        }
                    )
                curr_syls = []

        # Flush remainder
        if curr_syls:
            assembled_text = "".join(s["raw_text"] for s in curr_syls).strip()
            if assembled_text:
                words.append(
                    {
                        "word": assembled_text,
                        "start": curr_syls[0]["start"],
                        "end": curr_syls[-1]["end"],
                        "syllables": None,
                        "has_newline": False,
                    }
                )

        # Word to Line Reassembly
        raw_lines: list[list[dict[str, Any]]] = []
        curr_line: list[dict[str, Any]] = []

        for i, w in enumerate(words):
            curr_line.append(w)
            # Line break conditions:
            # 1. Explicit newline flag
            # 2. Section boundary jump
            # 3. Rest/gap >= 1.5 seconds between words
            trigger_split = w["has_newline"]
            if not trigger_split and i + 1 < len(words):
                gap = words[i + 1]["start"] - w["end"]
                if gap >= 1.5:
                    trigger_split = True
                # Check if crossing a section marker
                for sec in sections:
                    if w["end"] <= sec.start <= words[i + 1]["start"]:
                        trigger_split = True
                        break

            if trigger_split:
                raw_lines.append(curr_line)
                curr_line = []

        if curr_line:
            raw_lines.append(curr_line)

        # Build AlignedLine models
        aligned_lines: list[AlignedLine] = []
        for g in raw_lines:
            if not g:
                continue
            line_words = [
                WordTimestamp(
                    word=w["word"],
                    start=w["start"],
                    end=w["end"],
                    syllables=w["syllables"],
                )
                for w in g
            ]
            line_text = " ".join(w["word"] for w in g).strip()
            l_start = line_words[0].start
            l_end = line_words[-1].end

            # Locate section
            matching_sec = [s.name for s in sections if s.start <= l_start + 0.05 < s.end]
            sec_name = matching_sec[-1] if matching_sec else ""

            aligned_lines.append(
                AlignedLine(
                    text=line_text,
                    start=l_start,
                    end=l_end,
                    words=line_words,
                    section=sec_name,
                )
            )

        # Song Title
        resolved_title = title
        if not resolved_title:
            if self.track_names:
                resolved_title = self.track_names[0]
            else:
                resolved_title = self.midi_path.stem.replace("_", " ").title()

        return AlignmentResult(
            title=resolved_title,
            duration=round(total_duration, 3),
            audio_path=str(audio_path) if audio_path else "",
            instrumental_path="",
            vocals_path="",
            sections=sections,
            lines=aligned_lines,
        )


def convert_midi_to_alignment(
    midi_path: str | Path,
    audio_path: str | Path | None = None,
    title: str | None = None,
    track_idx: int | None = None,
) -> AlignmentResult:
    """
    Convenience wrapper to parse a MIDI file and output a validated AlignmentResult.
    """
    converter = MidiLyricsConverter(midi_path)
    return converter.to_alignment(audio_path=audio_path, title=title, track_idx=track_idx)


def render_midi_to_audio(
    midi_path: str | Path,
    output_audio: str | Path | None = None,
    soundfont_path: str | Path | None = None,
    sample_rate: int = 44100,
) -> Path | None:
    """
    Renders a multi-track MIDI file into an uncompressed WAV or MP3 audio file
    using FluidSynth if available on the system.
    """
    midi_p = Path(midi_path).resolve()
    if not midi_p.exists():
        return None

    if output_audio is None:
        out_p = midi_p.with_suffix(".wav")
    else:
        out_p = Path(output_audio).resolve()

    fluidsynth_bin = shutil.which("fluidsynth")
    if not fluidsynth_bin:
        log.warning("FluidSynth is not installed or not in PATH; skipping MIDI audio rendering.")
        return None

    sf_p = None
    if soundfont_path and Path(soundfont_path).exists():
        sf_p = Path(soundfont_path).resolve()
    else:
        # Search common soundfont locations
        candidate_sf = [
            "/Users/luca/OpenMontage/assets/audio/soundfonts/GeneralUser-GS.sf2",
            "/opt/homebrew/share/soundfonts/default.sf2",
            "/usr/share/sounds/sf2/default.sf2",
        ]
        for c in candidate_sf:
            if Path(c).exists():
                sf_p = Path(c)
                break

    if not sf_p:
        log.warning("No General MIDI SoundFont (.sf2) found for FluidSynth rendering.")
        return None

    cmd = [
        fluidsynth_bin,
        "-F", str(out_p),
        "-r", str(sample_rate),
        "-i", str(sf_p),
        str(midi_p),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        log.info("MIDI audio rendered successfully: %s", out_p)
        return out_p
    except Exception as e:
        log.warning("FluidSynth rendering failed: %s", e)
        return None
