"""Authenticated cloud adapter for the existing Motion Studio engine."""
from __future__ import annotations

from src.version_lifecycle import live_task

import asyncio
import hashlib
import json
import re
import shutil
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from src.auth import get_current_user_flexible
from src.database import get_db
from src.models import Task, User
from src.motion_api import create_motion_router
from src.session_manager import resolve_session_id
from src.settings import get_settings
from src.storage import LocalStorage, get_storage
from src.song_assets import source_keys, save_source
from src.song_identity import resolve_identity
from src.song_cover import resolve_cover, cover_path

PREFIX = "/api/cloud-motion"
router = APIRouter(prefix=PREFIX, tags=["Cloud Motion Studio"])
_workspaces = {}
_registry_lock = threading.Lock()


def user_namespace(uid: str) -> str:
    return hashlib.sha256(uid.encode()).hexdigest()


def task_prefix(uid: str, task_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", task_id):
        raise HTTPException(404, "歌曲不存在")
    return f"motion/{user_namespace(uid)}/{task_id}/"


class Workspace:
    def __init__(self, uid, storage):
        self.uid, self.storage = uid, storage
        base = storage.base_dir if isinstance(storage, LocalStorage) else Path(get_settings().UPLOAD_DIR)
        self.root = base / ".motion-cache" / user_namespace(uid)
        self.root.mkdir(parents=True, exist_ok=True)
        self.tasks = {}
        self.loaded = set()
        self.gate = threading.Lock()
        self.io_gate = threading.Lock()
        self.deleted = set()
        self.app = FastAPI()
        # This engine instance, its jobs and its filesystem belong to one user.
        self.app.dependency_overrides[resolve_session_id] = lambda: user_namespace(uid)
        self.app.include_router(create_motion_router(
            lambda: self.root, self.validate, self.find_audio, prefix=PREFIX,
            resolve_project=self.project_path,
            list_projects=lambda: [{"id": t.id, "name": t.song_title or t.title or "Untitled"}
                                   for t in self.tasks.values()],
            audio_url=lambda task_id: f"/api/editor/tasks/{task_id}/audio",
            on_write=self.persist, on_delete=self.remove,
            input_root=self.root, public_exports=False,
            before_render=self.before_render, on_render_finish=self.on_render_finish,
            prepare_render=self.prepare_render, render_record=self.render_record, cancel_render=self.cancel_render,
            on_render_heartbeat=self.on_render_heartbeat,
            on_record_webcodecs=self.on_record_webcodecs,
        ))

    def validate(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise HTTPException(404, "歌曲资源不存在")
        return path

    def project_path(self, task_id):
        if task_id not in self.tasks:
            raise HTTPException(404, "歌曲不存在或无权访问")
        task_prefix(self.uid, task_id)
        return self.root / task_id / "source_alignment.json"

    def find_audio(self, stem, song_output_dir=None):
        for path in Path(song_output_dir).glob("audio.*"):
            if path.is_file():
                return path
        return None

    def object_key(self, path):
        relative = self.validate(path).relative_to(self.root.resolve())
        return task_prefix(self.uid, relative.parts[0]) + "/".join(relative.parts[1:])

    def persist(self, path):
        # Called in the engine's request/render threads; storage has no DB session.
        with self.io_gate:
            if self.validate(path).relative_to(self.root.resolve()).parts[0] not in self.deleted:
                asyncio.run(self.storage.save(self.object_key(path), Path(path)))
                if Path(path).name in ('source_motion_identity.json','source_motion_cover.jpg'):
                    from src.song_library import design_changed
                    asyncio.run(design_changed(self.uid,self.validate(path).relative_to(self.root.resolve()).parts[0],Path(path)))
                if Path(path).name.endswith('_status.json'):
                    data = json.loads(Path(path).read_text())
                    video = Path(path).with_name(data['id'] + '.mp4')
                    if data.get('status') == 'done' and video.is_file():
                        if not self.on_render_heartbeat(data['id']):
                            raise RuntimeError('Render lease expired before publication')
                        task_id = self.validate(path).relative_to(self.root.resolve()).parts[0]
                        async def publish():
                            from src.export_jobs import sessions
                            from src.motion_billing import publish as publish_credits
                            video_key=self.object_key(video)
                            if not await self.storage.exists(video_key) or await self.storage.get_size(video_key) != video.stat().st_size:
                                raise RuntimeError('Uploaded video verification failed')
                            async with sessions() as db:
                                await publish_credits(db,self.uid,data['id'],task_id,video_key,
                                    'rhythm' if data.get('scene') == 'rhythm' else 'poster',
                                    {'resolution':[data.get('width'),data.get('height')],
                                     'duration':data.get('total',0)/30,'size_bytes':video.stat().st_size})
                                await db.commit()
                        asyncio.run(publish())

    def prepare_render(self, request, job_id, *, busy=False):
        # Keep Rhythm and old zero-price clients backward compatible.
        if request.scene == 'rhythm' or (not request.request_id and not get_settings().MOTION_EXPORT_CREDITS):
            if busy: raise HTTPException(409,'已有视频正在导出，请等待完成或取消')
            self.before_render(request.project_id,job_id)
            return {'id':job_id,'replay':False}
        from src.export_jobs import sessions
        from src.motion_billing import admit
        async def reserve():
            async with sessions() as db:
                result=await admit(db,self.uid,request.project_id,job_id,request,busy=busy)
                await db.commit()
                return result
        return asyncio.run(reserve())

    def render_record(self, job_id):
        from src.export_jobs import sessions
        from src.motion_billing import status
        async def read():
            async with sessions() as db:
                result=await status(db,self.uid,job_id)
                await db.commit()
                return result
        return asyncio.run(read())

    def cancel_render(self, job_id):
        from src.export_jobs import sessions
        from src.motion_billing import finish
        async def cancel():
            async with sessions() as db:
                result=await finish(db,self.uid,job_id,cancelled=True)
                await db.commit()
                return result
        return asyncio.run(cancel())

    def before_render(self, project_id, job_id):
        from src.export_jobs import sessions
        from src.queue_limiter import reserve_motion
        async def reserve():
            async with sessions() as db:
                await reserve_motion(db, self.uid, job_id)
                await db.commit()
        asyncio.run(reserve())

    def on_render_heartbeat(self, job_id):
        from src.export_jobs import sessions
        from src.queue_limiter import heartbeat_motion
        from src.motion_billing import heartbeat
        async def renew():
            async with sessions() as db:
                result=await heartbeat(db,self.uid,job_id)
                if result is None:
                    result=await heartbeat_motion(db,self.uid,job_id)
                await db.commit()
                return result
        return asyncio.run(renew())

    def on_render_finish(self, job_id, success):
        from src.export_jobs import sessions
        from src.motion_billing import finish
        async def release():
            async with sessions() as db:
                await finish(db,self.uid,job_id,success)
                await db.commit()
        asyncio.run(release())

    def on_record_webcodecs(self, req, data, status_file):
        with self.io_gate:
            if self.validate(status_file).relative_to(self.root.resolve()).parts[0] not in self.deleted:
                asyncio.run(self.storage.save(self.object_key(status_file), Path(status_file)))
        cost = get_settings().MOTION_WEBCODECS_CREDITS
        task_id = self.validate(status_file).relative_to(self.root.resolve()).parts[0]
        from src.export_jobs import sessions
        from src import credits
        from src.export_library import record_export
        async def settle():
            async with sessions() as db:
                if cost > 0:
                    await credits.reserve(db, self.uid, req.job_id, 'motion_webcodecs', cost)
                    await credits.finish(db, self.uid, req.job_id, 'motion_webcodecs', True)
                try:
                    await record_export(req.job_id, self.uid, task_id, self.object_key(status_file),
                                        'webcodecs', {
                                            'resolution': [1080, 1920] if req.aspect == '9:16' else [1920, 1080],
                                            'duration': req.duration,
                                            'size_bytes': req.file_size,
                                            'title': data.get('title')
                                        }, db=db)
                except Exception:
                    pass
                await db.commit()
        asyncio.run(settle())

    def remove(self, path):
        asyncio.run(self.storage.delete(self.object_key(path)))
        if Path(path).name == 'source_motion_cover.jpg':
            from src.song_library import design_changed
            task_id = self.validate(path).relative_to(self.root.resolve()).parts[0]
            asyncio.run(design_changed(self.uid, task_id, Path(path)))

    async def hydrate(self, task_id, audio=False):
        path = self.project_path(task_id)
        task = self.tasks[task_id]
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await self.storage.load(task.alignment_json_key, path)
        except FileNotFoundError as exc:
            raise HTTPException(404, "对齐数据尚未就绪") from exc
        payload = json.loads(path.read_text())
        payload["title"] = task.song_title or task.title or payload.get("title") or "Untitled"
        payload['presentation_title'] = payload['title']
        payload['audio_cache'] = {'uid': self.uid, 'version': hashlib.sha256(task.input_mp3_key.encode()).hexdigest()}
        path.write_text(json.dumps(payload, ensure_ascii=False))
        metadata_key, cover_key = source_keys(task.input_mp3_key)
        metadata_path, artwork_path = path.parent / 'source_suno.json', path.parent / 'source_cover.jpg'
        try:
            old_source = json.loads(metadata_path.read_text())
        except (OSError, ValueError):
            old_source = {}
        if await self.storage.exists(metadata_key):
            await self.storage.load(metadata_key, metadata_path)
            source = json.loads(metadata_path.read_text())
            from src.song_sections import bind_source_sections
            if bind_source_sections(payload, source.get('sections') or []):
                path.write_text(json.dumps(payload, ensure_ascii=False))
            version = lambda data: data.get('artwork_sha256') or data.get('image_url') or ''
            if not artwork_path.exists() or version(source) != version(old_source):
                if await self.storage.exists(cover_key):
                    await self.storage.load(cover_key, artwork_path)
        prefix = task_prefix(self.uid, task_id)
        if task_id not in self.loaded:
            # Restore small design/status files after a container restart.
            for key in await self.storage.list_keys(prefix):
                relative = key.removeprefix(prefix)
                if relative.endswith(".mp4"):
                    continue
                destination = self.validate(path.parent / relative)
                await self.storage.load(key, destination)
            self.loaded.add(task_id)
        else:
            for name in ("source_motion_plan.json", "source_motion_identity.json", "source_motion_settings.json", "source_rhythm_settings.json"):
                if await self.storage.exists(prefix + name):
                    await self.storage.load(prefix + name, path.parent / name)
                else:
                    (path.parent / name).unlink(missing_ok=True)
        if audio and task.input_mp3_key:
            suffix = Path(task.input_mp3_key).suffix.lower()
            if suffix not in (".mp3", ".wav", ".m4a", ".flac", ".ogg"):
                suffix = ".mp3"
            destination = path.parent / ("audio" + suffix)
            if not destination.exists():
                await self.storage.load(task.input_mp3_key, destination)

    async def restore_download(self, route):
        match = re.fullmatch(r"render/([a-f0-9]{32})/(download|stream)", route)
        if not match:
            return
        job_id = match[1]
        for task_id in self.tasks:
            path = self.root / task_id / "motion_exports" / f"{job_id}.mp4"
            if not path.is_file() and path.with_name(f"{job_id}_status.json").is_file():
                key = task_prefix(self.uid, task_id) + f"motion_exports/{job_id}.mp4"
                if await self.storage.exists(key):
                    await self.storage.load(key, path)


class EngineResponse(Response):
    def __init__(self, workspace, body):
        super().__init__()
        self.workspace, self.request_body = workspace, body

    async def __call__(self, scope, receive, send):
        first = True

        async def replay():
            nonlocal first
            if first:
                first = False
                return {"type": "http.request", "body": self.request_body, "more_body": False}
            return await receive()

        try:
            await self.workspace.app(scope, replay, send)
        finally:
            self.workspace.gate.release()


def workspace_for(uid, storage):
    key = (id(storage), uid)
    with _registry_lock:
        workspace = _workspaces.get(key)
        if workspace is None:
            workspace = _workspaces[key] = Workspace(uid, storage)
    return workspace


@router.post('/source/refresh')
async def refresh_source(request: Request, user: User = Depends(get_current_user_flexible),
                         db: AsyncSession = Depends(get_db)):
    from urllib.parse import urlparse
    from src.suno_fetch import fetch_song
    from pydantic import BaseModel

    class SourceRequest(BaseModel):
        project_id: str

    try:
        data = SourceRequest.model_validate(await request.json())
    except ValueError as exc:
        raise HTTPException(422, '请选择有效歌曲') from exc
    task = (await db.execute(select(Task).where(Task.id == data.project_id, Task.user_id == user.id, live_task()))).scalar_one_or_none()
    if task is None:
        raise HTTPException(404, '歌曲不存在或无权访问')
    if not task.alignment_json_key:
        raise HTTPException(409, '请等待歌曲导入完成后再刷新信息')
    if urlparse(task.suno_url or '').hostname not in ('suno.com', 'www.suno.com'):
        raise HTTPException(422, '该歌曲没有 Suno 来源链接，请手动填写歌曲信息或上传封面')
    try:
        song = await asyncio.to_thread(fetch_song, task.suno_url)
    except Exception as exc:
        raise HTTPException(502, 'Suno 歌曲信息读取失败，请稍后重试') from exc
    expected = (task.config_snapshot if isinstance(task.config_snapshot, dict) else {}).get('suno_song_id')
    if expected and song.id != expected:
        raise HTTPException(409, '来源歌曲与导入时不一致，未修改现有资料')
    storage = get_storage()
    workspace = workspace_for(user.id, storage)
    while not workspace.gate.acquire(blocking=False):
        await asyncio.sleep(.01)
    try:
        workspace.tasks[task.id] = task
        result = await save_source(storage, task.input_mp3_key, song)
        await workspace.hydrate(task.id)
        path = workspace.project_path(task.id)
        if not result['warning'] and result['metadata']['image_url']:
            # A previous "Restore Suno cover" cache must not mask refreshed art.
            cached = cover_path(path, False)
            cached.unlink(missing_ok=True)
            await storage.delete(workspace.object_key(cached))
        payload = json.loads(path.read_text())
        return {'identity': resolve_identity(path, payload, workspace.root),
                'cover': resolve_cover(path, payload, workspace.root),
                'sections': payload.get('sections', []), 'warning': result['warning']}
    finally:
        workspace.gate.release()


@router.api_route("/{route:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def dispatch(route: str, request: Request,
                   user: User = Depends(get_current_user_flexible), db: AsyncSession = Depends(get_db)):
    storage = get_storage()
    workspace = workspace_for(user.id, storage)
    while not workspace.gate.acquire(blocking=False):
        await asyncio.sleep(.01)
    try:
        rows = await db.execute(select(Task).where(Task.user_id == user.id, live_task(),
                                                 Task.alignment_json_key.isnot(None))
                                .order_by(Task.created_at.desc()))
        workspace.tasks = {task.id: task for task in rows.scalars().all()}
        # Read a bounded body, then replay it to the existing typed engine routes.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 20 * 1024 * 1024:
                raise HTTPException(413, "请求内容过大")
        project_id = request.query_params.get("project_id")
        content_type = request.headers.get("content-type", "")
        request._body = bytes(body)
        if body and "application/json" in content_type:
            try:
                data = json.loads(body)
            except ValueError as exc:
                raise HTTPException(422, "请求需要有效 JSON") from exc
            if isinstance(data, dict):
                project_id = data.get("project_id", project_id)
        elif body and "multipart/form-data" in content_type:
            form = await request.form()
            project_id = form.get("project_id")
            await form.close()
        if project_id:
            await workspace.hydrate(project_id, audio=route == "render")
        elif request.method != "GET":
            # Applying an asynchronous director result must see current alignment.
            for task_id in workspace.tasks:
                if (workspace.root / task_id / "source_alignment.json").exists():
                    await workspace.hydrate(task_id)
        elif route == "gallery" or route.startswith("render/"):
            # A direct export/download URL must work before opening the song.
            for task_id in workspace.tasks:
                if task_id not in workspace.loaded:
                    await workspace.hydrate(task_id)
        await workspace.restore_download(route)
        return EngineResponse(workspace, bytes(body))
    except BaseException:
        workspace.gate.release()
        raise


async def delete_artifacts(uid, task_id, storage):
    workspace = _workspaces.get((id(storage), uid))
    locks = [workspace.gate, workspace.io_gate] if workspace else []
    acquired = []
    try:
        for lock in locks:
            while not lock.acquire(blocking=False):
                await asyncio.sleep(.01)
            acquired.append(lock)
        if workspace:
            workspace.deleted.add(task_id)
            workspace.tasks.pop(task_id, None)
            workspace.loaded.discard(task_id)
        for key in await storage.list_keys(task_prefix(uid, task_id)):
            await storage.delete(key)
        if workspace:
            shutil.rmtree(workspace.root / task_id, ignore_errors=True)
    finally:
        for lock in reversed(acquired):
            lock.release()
