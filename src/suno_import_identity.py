"""Song identity and immutable lyric snapshots for repeat Suno imports."""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import or_, select

from src.models import Task, TaskStatus


def lyrics_signature(text: str) -> str:
    # Keep case, punctuation and stanza/word boundaries; only normalize transport whitespace.
    normalized = "\n".join(line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def direct_song_id(url: str) -> str | None:
    parts = urlparse(url).path.strip("/").split("/")
    return parts[1].lower() if len(parts) >= 2 and parts[0] == "song" else None


async def reusable_import(db, user_id, song, submitted_url, signature, options, storage):
    """Match new IDs and lazily identify legacy tasks without trusting titles as identity."""
    query = select(Task).where(Task.user_id == user_id, Task.suno_url.isnot(None), or_(
        Task.config_snapshot["suno_song_id"].as_string() == song.id,
        Task.suno_url == submitted_url,
        Task.suno_url.contains(f"/song/{song.id}"),
        Task.config_snapshot["suno_song_id"].as_string().is_(None),
    )).order_by(Task.created_at.desc())
    candidates = (await db.execute(query)).scalars().all()
    for task in candidates:
        snapshot = dict(task.config_snapshot or {})
        identity = snapshot.get("suno_song_id") or direct_song_id(task.suno_url)
        if identity is None:
            if task.suno_url == submitted_url:
                identity = song.id
            else:
                # An old short link cannot be derived from the UUID. Resolve it only
                # for legacy imports and verify the actual ID.
                from src.suno_fetch import fetch_song
                try:
                    old_song = await asyncio.to_thread(fetch_song, task.suno_url)
                    identity = old_song.id
                except Exception:
                    continue
        snapshot["suno_song_id"] = identity
        task.config_snapshot = snapshot
        if identity != song.id:
            continue
        previous = snapshot.get("import_lyrics_signature")
        if previous is None:
            try:
                with tempfile.TemporaryDirectory(prefix="m2v-import-snapshot-") as directory:
                    path = Path(directory) / "lyrics.txt"
                    await storage.load(task.input_lyrics_key, path)
                    previous = lyrics_signature(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
        snapshot.update(suno_song_id=song.id, import_lyrics_signature=previous)
        task.config_snapshot = snapshot
        same_options = all(snapshot.get(k, default) == value for k, value, default in (
            ("language", options["language"], "auto"),
            ("skip_separation", options["skip_separation"], False),
            ("ass_only", options["ass_only"], False),
            ("beat_effects", options["beat_effects"], False),
        ))
        if previous != signature or not same_options:
            continue
        if task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING):
            return task
        if task.status == TaskStatus.COMPLETED and task.alignment_json_key and await storage.exists(task.alignment_json_key):
            return task
    return None
