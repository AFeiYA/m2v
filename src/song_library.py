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
from src.models import SongPreference, Task, TaskStatus, VideoExport, VersionTrash
from src.version_lifecycle import live_task

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
    trashed=set((await db.execute(select(VersionTrash.task_id).where(VersionTrash.user_id==uid))).scalars())
    songs = []
    for song_id, all_versions in groups.items():
        versions=[t for t in all_versions if t.id not in trashed]
        if not versions:continue
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
                      "artist": ((current or latest).config_snapshot or {}).get('library_artist',''),
                      "updated_at": max(date(t) for t in versions).isoformat(), "current_task_id": current.id if current else None,
                      "latest_task_id": latest.id, "status": latest.status.value,
                      "progress": latest.progress, "version_count": len(versions),
                      "export_count": sum(counts.get(t.id, 0) for t in all_versions),
                      "export_task_ids": [t.id for t in all_versions],
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
        songs = [s for s in songs if needle in str(s.get('artist','')).casefold() or any(needle in v['title'].casefold() for v in s['versions'])]
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


@router.get('/trash/versions')
async def trashed_versions(user=Depends(get_current_user), db=Depends(get_db)):
    rows = (await db.execute(select(Task).join(VersionTrash, VersionTrash.task_id == Task.id)
            .where(Task.user_id == user.id, VersionTrash.user_id == user.id)
            .order_by(VersionTrash.trashed_at.desc()))).scalars().all()
    return {"versions": [version(t) for t in rows]}


@router.post('/versions/{task_id}/trash')
async def move_to_trash(task_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    from src.version_lifecycle import trash_version
    await trash_version(db, user.id, task_id)
    return {"message":"Version moved to Trash. Finished videos are kept."}


@router.post('/versions/{task_id}/restore')
async def restore_version(task_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    from sqlalchemy import delete
    task = (await db.execute(select(Task).where(Task.id==task_id, Task.user_id==user.id).with_for_update())).scalar_one_or_none()
    if task is None:
        raise HTTPException(404,'Version not found')
    from sqlalchemy import update
    await db.execute(update(Task).where(Task.id==task_id).values(updated_at=Task.updated_at))
    await db.execute(delete(VersionTrash).where(VersionTrash.task_id == task_id, VersionTrash.user_id == user.id))
    await db.commit()
    return {"message":"Version restored. Interrupted work is not automatically restarted."}


@router.get('/versions/{task_id}/presentation')
async def presentation(task_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    """Small source/identity reads only, on demand; never download audio/alignment."""
    import tempfile
    from pathlib import Path
    from datetime import datetime, timedelta
    from jose import jwt
    from fastapi.responses import JSONResponse
    from src.settings import get_settings
    from src.storage import get_storage, S3Storage
    from src.song_assets import source_keys
    from src.motion_cloud import task_prefix
    task = (await db.execute(select(Task).where(Task.id == task_id, Task.user_id == user.id, live_task()))).scalar_one_or_none()
    if task is None:
        raise HTTPException(404,'Version not found')
    storage = get_storage()
    source_key, source_cover = source_keys(task.input_mp3_key)
    prefix = task_prefix(user.id, task.id)
    source, identity_data = {}, {}
    try:
        with tempfile.TemporaryDirectory(prefix='m2v-song-facts-') as directory:
            for key, name in [(source_key,'source'), (prefix+'source_motion_identity.json','identity')]:
                if await storage.exists(key):
                    path=Path(directory)/name
                    await storage.load(key,path)
                    try:
                        facts=json.loads(path.read_text())
                        if isinstance(facts,dict):
                            if name=='source': source=facts
                            else: identity_data=facts
                    except (ValueError,UnicodeError):
                        pass
        custom = await storage.exists(prefix+'source_motion_cover.jpg')
        cover_key = prefix+'source_motion_cover.jpg' if custom else source_cover
        has_cover = custom or await storage.exists(source_cover)
        cover_url = None
        if has_cover:
            if isinstance(storage,S3Storage):
                cover_url=storage.client.generate_presigned_url('get_object',Params={'Bucket':storage.bucket,'Key':cover_key,'ResponseContentType':'image/jpeg'},ExpiresIn=900)
            else:
                settings=get_settings()
                ticket=jwt.encode({'sub':user.id,'type':'song-cover','task':task.id,'custom':custom,
                    'exp':datetime.now(timezone.utc)+timedelta(minutes=15)},settings.SECRET_KEY,algorithm=settings.JWT_ALGORITHM)
                cover_url=f'/api/songs/versions/{task.id}/cover?ticket={ticket}'
    except Exception as exc:
        raise HTTPException(503,'Artwork is temporarily unavailable. Please retry later.') from exc
    artist=identity_data.get('artist',source.get('artist',''))
    if not isinstance(artist,str) or artist.strip().lower()=='unknown': artist=''
    # Cache a display fact without changing the user's last-edit timestamp.
    from sqlalchemy import update
    fresh=(await db.execute(select(Task).where(Task.id==task_id,Task.user_id==user.id,live_task()).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if fresh is not None and (fresh.config_snapshot or {}).get('library_artist') != artist[:80]:
        await db.execute(update(Task).where(Task.id==task_id).values(
            config_snapshot={**(fresh.config_snapshot or {}),'library_artist':artist[:80]}, updated_at=Task.updated_at))
        await db.commit()
    return JSONResponse({'artist':artist[:80],'title':identity_data.get('title') or task.song_title or task.title,
                         'cover_url':cover_url,'expires_in':900},headers={'Cache-Control':'private, no-store'})


@router.get('/versions/{task_id}/cover')
async def cover_file(task_id: str, ticket: str, db=Depends(get_db)):
    from jose import jwt, JWTError
    from fastapi.responses import FileResponse
    from src.settings import get_settings
    from src.storage import get_storage, LocalStorage
    from src.song_assets import source_keys
    from src.motion_cloud import task_prefix
    settings=get_settings()
    try:
        payload=jwt.decode(ticket,settings.SECRET_KEY,algorithms=[settings.JWT_ALGORITHM])
        if payload.get('type')!='song-cover' or payload.get('task')!=task_id:
            raise JWTError('Wrong cover scope')
    except JWTError as exc:
        raise HTTPException(401,'Artwork link expired') from exc
    task=(await db.execute(select(Task).where(Task.id==task_id,Task.user_id==payload.get('sub'),live_task()))).scalar_one_or_none()
    if task is None: raise HTTPException(404,'Version not found')
    storage=get_storage()
    if not isinstance(storage,LocalStorage):raise HTTPException(404,'Local artwork unavailable')
    key=task_prefix(task.user_id,task.id)+'source_motion_cover.jpg' if payload.get('custom') else source_keys(task.input_mp3_key)[1]
    path=storage.get_local_path(key)
    if not path.is_file():raise HTTPException(404,'Artwork unavailable')
    return FileResponse(path,media_type='image/jpeg',headers={'Cache-Control':'private, no-store'})


async def design_changed(uid, task_id, path):
    """Reflect saved Motion identity/artwork changes in the lightweight library."""
    from src.api_server import async_session
    from uuid import uuid4
    async with async_session() as db:
        task=(await db.execute(select(Task).where(Task.id==task_id,Task.user_id==uid,live_task()).with_for_update())).scalar_one_or_none()
        if task is None:return
        snapshot=dict(task.config_snapshot or {})
        snapshot['presentation_revision']=uuid4().hex
        if path.name=='source_motion_identity.json':
            data=json.loads(path.read_text())
            snapshot['library_artist']=str(data.get('artist',''))[:80]
            task.song_title=str(data.get('title') or task.song_title or task.title)[:120]
        task.config_snapshot=snapshot
        await db.commit()
