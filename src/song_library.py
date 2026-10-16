"""Owner-scoped song library: songs contain task versions and exported videos.

This first phase derives identity from existing metadata, never from titles and
never by fetching a short URL or reading media. Task/credit history is unchanged.
"""
from datetime import timezone
from hashlib import sha256
import json
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from src.auth import get_current_user
from src.database import get_db
from src.models import SongPreference, Task, TaskStatus, VideoExport

router = APIRouter(prefix="/api/songs", tags=["Song Library"])


def identity(task):
    source = (task.config_snapshot or {}).get("suno_song_id")
    if not source and task.suno_url:
        parsed = urlparse(task.suno_url)
        parts = parsed.path.strip('/').split('/')
        if parsed.hostname in ('suno.com', 'www.suno.com') and len(parts) == 2 and parts[0] == 'song':
            source = parts[1]
    # Legacy unresolved short links remain separate until normal import resolves
    # them. A library read must not call Suno or guess identity from a song title.
    provider, source = ('suno', str(source).lower()) if source else ('upload', task.id)
    return sha256(json.dumps([task.user_id, provider, source], separators=(',', ':')).encode()).hexdigest()


def date(task):
    value = task.updated_at or task.completed_at or task.created_at
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def version(task, count=0):
    return {"id": task.id, "title": task.song_title or task.title or "Untitled",
            "status": task.status.value, "progress": task.progress,
            "editable": task.status == TaskStatus.COMPLETED and bool(task.alignment_json_key),
            "updated_at": date(task).isoformat(), "export_count": count,
            "has_ass": bool(task.output_ass_key), "has_video": bool(task.output_mp4_key),
            "error": task.error_message if task.status == TaskStatus.FAILED else None}


async def library(db, uid):
    tasks = (await db.execute(select(Task).where(Task.user_id == uid)
                             .execution_options(populate_existing=True))).scalars().all()
    counts = dict((await db.execute(select(VideoExport.task_id, func.count()).where(
        VideoExport.user_id == uid, VideoExport.deleted_at.is_(None),
    ).group_by(VideoExport.task_id))).all())
    preferences = {p.id: p for p in (await db.execute(select(SongPreference).where(
        SongPreference.user_id == uid))).scalars()}
    groups = {}
    for task in tasks:
        groups.setdefault(identity(task), []).append(task)
    songs = []
    for song_id, versions in groups.items():
        # Import order and last edit time are different concepts. Editing an old
        # version must not make it look like the newest import succeeded.
        versions.sort(key=lambda t: (t.created_at.replace(tzinfo=timezone.utc)
                                    if t.created_at.tzinfo is None else t.created_at, t.id), reverse=True)
        preference = preferences.get(song_id)
        editable = [t for t in versions if t.status == TaskStatus.COMPLETED and t.alignment_json_key]
        current = next((t for t in editable if preference and t.id == preference.preferred_task_id), None)
        current = current or (editable[0] if editable else None)
        latest = versions[0]
        songs.append({"id": song_id, "title": (current or latest).song_title or (current or latest).title or "Untitled",
                      "updated_at": max(date(t) for t in versions).isoformat(), "current_task_id": current.id if current else None,
                      "latest_task_id": latest.id, "status": latest.status.value,
                      "progress": latest.progress, "version_count": len(versions),
                      "export_count": sum(counts.get(t.id, 0) for t in versions),
                      "starred": bool(preference and preference.starred),
                      "archived": bool(preference and preference.archived),
                      "versions": [version(t, counts.get(t.id, 0)) for t in versions]})
    return songs


@router.get("")
async def list_songs(q: str = Query('', max_length=200),
                     view: Literal['active', 'starred', 'archived', 'all'] = 'active',
                     sort: Literal['recent', 'title'] = 'recent',
                     page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=50),
                     user=Depends(get_current_user), db=Depends(get_db)):
    from src.alignment_execution import reconcile
    await reconcile(db, user.id)
    songs = await library(db, user.id)
    total_songs = len(songs)
    active_count = sum(v["status"] in ("pending", "processing") for s in songs for v in s["versions"])
    if view == 'active':
        songs = [s for s in songs if not s['archived']]
    elif view == 'starred':
        songs = [s for s in songs if s['starred'] and not s['archived']]
    elif view == 'archived':
        songs = [s for s in songs if s['archived']]
    needle = q.strip().casefold()
    if needle:
        songs = [s for s in songs if any(needle in v['title'].casefold() for v in s['versions'])]
    songs.sort(key=lambda s: (s['title'].casefold(), s['id']) if sort == 'title'
               else (s['updated_at'], s['id']), reverse=sort == 'recent')
    total = len(songs)
    rows = songs[(page-1)*page_size:page*page_size]
    return {"songs": rows, "total": total, "total_songs": total_songs, "active_count": active_count, "page": page, "page_size": page_size}


class LibraryChange(BaseModel):
    starred: bool | None = None
    archived: bool | None = None
    preferred_task_id: str | None = None


@router.patch("/{song_id}")
async def change_song(song_id: str, change: LibraryChange,
                      user=Depends(get_current_user), db=Depends(get_db)):
    song = next((s for s in await library(db, user.id) if s['id'] == song_id), None)
    if song is None:
        raise HTTPException(404, 'Song not found')
    values = change.model_dump(exclude_unset=True)
    if any(values.get(k) is None for k in ('starred', 'archived') if k in values):
        raise HTTPException(422, 'Library flags must be true or false')
    preferred = values.get('preferred_task_id')
    if preferred is not None and not any(v['id'] == preferred and v['editable'] for v in song['versions']):
        raise HTTPException(409, 'Choose a completed version of this song')
    if values:
        if db.bind.dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        query = insert(SongPreference).values(id=song_id, user_id=user.id, **values)
        await db.execute(query.on_conflict_do_update(index_elements=['id'], set_=values))
        await db.commit()
    return {"message": "Song library updated"}
