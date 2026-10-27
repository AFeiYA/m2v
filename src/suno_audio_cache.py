"""Audio provenance is independent of mutable Suno lyrics and metadata."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


def source_id(value: str) -> str:
    identity = str(value).strip().lower()
    if not identity:
        raise ValueError("Missing Suno song identity")
    return identity


def source_directory(root: Path, song_id: str) -> Path:
    identity = source_id(song_id)
    key = identity if re.fullmatch(r"[a-z0-9_-]+", identity) else hashlib.sha256(identity.encode()).hexdigest()
    root = Path(root)
    return root if root.name == key and root.parent.name == "suno" else root / "suno" / key


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def temporary_path(destination: Path) -> Path:
    """Keep the media suffix so FFmpeg can infer its output format."""
    fd, name = tempfile.mkstemp(prefix=".m2v-download-", suffix=destination.suffix, dir=destination.parent)
    os.close(fd)
    return Path(name)


def write_if_changed(path: Path, text: str) -> bool:
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except (OSError, UnicodeError):
        pass
    temporary = temporary_path(path)
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def provenance_path(audio: Path) -> Path:
    return audio.with_suffix(audio.suffix + ".source.json")


def verified_audio(audio: Path, song_id: str) -> bool:
    try:
        record = json.loads(provenance_path(audio).read_text(encoding="utf-8"))
        return (isinstance(record, dict) and record.get("version") == 1
                and record.get("suno_song_id") == source_id(song_id)
                and record.get("audio_filename") == audio.name
                and record.get("size_bytes") == audio.stat().st_size
                and record.get("sha256") == file_digest(audio))
    except (OSError, ValueError, UnicodeError):
        return False


def remember_audio(audio: Path, song_id: str) -> None:
    """Call only after downloading, extracting or explicitly identifying this audio."""
    record = {"version": 1, "suno_song_id": source_id(song_id), "audio_filename": audio.name,
              "size_bytes": audio.stat().st_size, "sha256": file_digest(audio)}
    write_if_changed(provenance_path(audio), json.dumps(record, ensure_ascii=False, sort_keys=True))
