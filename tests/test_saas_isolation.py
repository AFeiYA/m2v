"""Account isolation and real worker lifecycle regression tests (no private media)."""
import ast
import asyncio
import sys
import threading
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src import api_server, auth, database, local_editor, storage, worker
from src.database import Base, get_db
from src.models import Task, TaskStatus, User
from src.storyboard_schema import AlignmentProject
from src.task_lifecycle import fail_task_and_refund


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    engine = create_async_engine(url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(worker.settings, "DATABASE_URL", url)
    monkeypatch.setattr(auth.settings, "SECRET_KEY", "isolated-regression-key")
    monkeypatch.setattr(auth, "verify_firebase_id_token", lambda token: None)
    monkeypatch.setattr(api_server, "async_session", sessions)
    local_storage = storage.LocalStorage(tmp_path / "storage")
    monkeypatch.setattr(storage, "_storage_instance", local_storage)
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(local_editor.app.state, "scan_dir", output, raising=False)

    async def initialize():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            for uid in ("alice", "bob"):
                db.add(User(id=uid, email=f"{uid}@example.com", username=uid, credits=5))
            await db.commit()
    asyncio.run(initialize())

    async def test_db():
        async with sessions() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    # Exercise the actual Gradio mount function without launching Gradio/GPU.
    async def initialized():
        pass
    monkeypatch.setattr(database, "init_db", initialized)
    source = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(source.read_text())
    mount = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "mount_fastapi_routes")
    namespace = {"fastapi_app": local_editor.app}
    exec(compile(ast.Module(body=[mount], type_ignores=[]), str(source), "exec"), namespace)
    app = FastAPI()
    namespace["mount_fastapi_routes"](types.SimpleNamespace(app=app, server_app=app))
    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as client:
        yield types.SimpleNamespace(client=client, sessions=sessions, storage=local_storage, output=output)
    asyncio.run(engine.dispose())


def headers(uid="alice", refresh=False):
    factory = auth.create_refresh_token if refresh else auth.create_access_token
    return {"Authorization": f"Bearer {factory(uid)}"}


def test_cloud_legacy_routes_cannot_read_or_write_any_project(sandbox):
    folder = sandbox.output / "bob"
    folder.mkdir()
    path = folder / "bob_alignment.json"
    project = AlignmentProject(title="bob", duration=2, lines=[])
    project.save_json(path)
    original = path.read_bytes()
    for credentials in ({}, headers("alice"), headers("bob")):
        assert sandbox.client.get("/api/files", headers=credentials).status_code == 403
        assert sandbox.client.get("/api/alignment", params={"path": str(path)}, headers=credentials).status_code == 403
        assert sandbox.client.put("/api/alignment", params={"path": str(path)}, headers=credentials, json={"title": "changed"}).status_code == 403
        assert sandbox.client.get("/api/asset_file", params={"path": str(path)}, headers=credentials).status_code == 403
    assert path.read_bytes() == original
    assert sandbox.client.get("/api/editor/songs", headers=headers()).status_code == 200
    # Local-only operation still works; its router is not a shared SaaS API.
    with TestClient(local_editor.app) as client:
        assert client.get("/api/alignment", params={"path": str(path)}).status_code == 200


def test_download_requires_access_token_and_task_ownership(sandbox):
    path = sandbox.storage.get_local_path("alice.mp3")
    path.write_bytes(b"audio")
    async def seed():
        async with sandbox.sessions() as db:
            db.add(Task(id="download", user_id="alice", input_mp3_key="alice.mp3", input_lyrics_key="lyrics.txt"))
            await db.commit()
    asyncio.run(seed())
    endpoint = "/api/tasks/download/download/mp3"
    assert sandbox.client.get(endpoint, headers=headers()).status_code == 200
    assert sandbox.client.get(endpoint, params={"token": auth.create_access_token("alice")}).status_code == 200
    assert sandbox.client.get(endpoint).status_code == 401
    assert sandbox.client.get(endpoint, headers=headers(refresh=True)).status_code == 401
    assert sandbox.client.get(endpoint, params={"token": auth.create_refresh_token("alice")}).status_code == 401
    assert sandbox.client.get(endpoint, headers=headers("bob")).status_code == 404


def test_cloud_plugin_routes_authentication(sandbox, monkeypatch):
    # 1. 元数据探测接口在云端公开可用
    assert sandbox.client.get("/api/suno/publish_status", params={"url": "invalid"}).status_code in (400, 422)

    # 2. 插件下载接口未携带或携带无效 Token 返回 401
    assert sandbox.client.get("/api/suno/download_mp3", params={"url": "https://suno.com/song/test"}).status_code == 401
    assert sandbox.client.get("/api/suno/download_mp3", params={"url": "https://suno.com/song/test", "token": "invalid"}).status_code == 401
    assert sandbox.client.get("/api/suno/download_mp3", params={"url": "https://suno.com/song/test"}, headers=headers(refresh=True)).status_code == 401

    # 3. 携带合法 access_token 可通过认证层
    res_bearer = sandbox.client.get("/api/suno/download_mp3", params={"url": ""}, headers=headers("alice"))
    # 空 url 会通过认证后进入业务逻辑抛 400
    assert res_bearer.status_code == 400
    assert "请输入 Suno 歌曲链接" in res_bearer.json().get("detail", "")

    res_param = sandbox.client.get("/api/suno/download_mp3", params={"url": "", "token": auth.create_access_token("alice")})
    assert res_param.status_code == 400
    assert "请输入 Suno 歌曲链接" in res_param.json().get("detail", "")


def install_pipeline(sandbox, monkeypatch, fail):
    module = types.ModuleType("src.main")
    observed = []
    def process_one(**kwargs):
        observed.append(kwargs["config"])
        if fail:
            raise RuntimeError("pipeline regression failure")
        out = kwargs["output_dir"]
        stem = kwargs["mp3_path"].stem
        (out / f"{stem}_alignment.json").write_text("{}")
        (out / f"{stem}.ass").write_text("subtitle")
        (out / f"{stem}.mp4").write_bytes(b"video")
        return out / f"{stem}.mp4"
    module.process_one = process_one
    monkeypatch.setitem(sys.modules, "src.main", module)
    monkeypatch.setattr(worker, "_publish_progress", lambda *args: None)
    def no_queue(**kwargs):
        raise RuntimeError("queue unavailable")
    monkeypatch.setattr(worker.process_song_task, "delay", no_queue)
    dispatch = api_server._dispatch_task
    def dispatch_and_wait(*args, **kwargs):
        result = dispatch(*args, **kwargs)
        for thread in threading.enumerate():
            if thread.name == f"WorkerThread-{args[0][:8]}":
                thread.join(timeout=10)
                assert not thread.is_alive()
        return result
    monkeypatch.setattr(api_server, "_dispatch_task", dispatch_and_wait)
    return observed


def submit(sandbox, monkeypatch, source):
    if source == "upload":
        return sandbox.client.post("/api/upload", headers=headers(), files={
            "mp3": ("test.mp3", b"audio", "audio/mpeg"),
            "lyrics": ("test.txt", b"lyrics", "text/plain"),
        })
    from src import suno_fetch
    monkeypatch.setattr(suno_fetch, "fetch_song", lambda url: types.SimpleNamespace(
        title="test", lyrics="lyrics", raw_prompt="", audio_url="https://example.invalid/audio", video_url=""))
    def download(song, output_dir, **kwargs):
        assert kwargs["allow_local_fallback"] is False
        audio = output_dir / "source.mp3"
        lyrics = output_dir / "source.txt"
        audio.write_bytes(b"audio")
        lyrics.write_text(song.lyrics)
        return audio, lyrics, output_dir / "source.json", song
    monkeypatch.setattr(suno_fetch, "download_song", download)
    return sandbox.client.post("/api/tasks/from-suno", headers=headers(), json={"suno_url": "https://suno.com/s/test"})


@pytest.mark.parametrize("source", ["upload", "suno"])
@pytest.mark.parametrize("fail", [False, True])
def test_thread_worker_sees_committed_task_and_refunds_failure_once(sandbox, monkeypatch, source, fail):
    observed = install_pipeline(sandbox, monkeypatch, fail)
    response = submit(sandbox, monkeypatch, source)
    assert response.status_code == 200
    tid = response.json()["task_id"]
    task = sandbox.client.get(f"/api/tasks/{tid}", headers=headers()).json()
    assert task["status"] == ("failed" if fail else "completed")
    credits = sandbox.client.get("/api/auth/me", headers=headers()).json()["credits"]
    assert credits == (5 if fail else 4)
    assert len(observed) == 1  # Real worker invoked the pipeline: no missing-self failure.
    assert observed[0].skip_separation is False
    assert observed[0].aligner.language == "auto"
    if fail:
        assert task["error_message"] == "pipeline regression failure"
    else:
        assert task["output_mp4_key"] and task["alignment_json_key"]


def test_failure_to_start_thread_marks_failed_and_refunds(sandbox, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("thread start failed")
    monkeypatch.setattr(api_server, "_dispatch_task", unavailable)
    response = submit(sandbox, monkeypatch, "upload")
    assert response.status_code == 503
    assert sandbox.client.get("/api/auth/me", headers=headers()).json()["credits"] == 5
    tasks = sandbox.client.get("/api/tasks", headers=headers()).json()["tasks"]
    assert tasks[0]["status"] == "failed"


@pytest.mark.parametrize("initial_status", [TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.COMPLETED])
def test_failure_claim_refunds_actual_cost_only_once(sandbox, initial_status):
    async def exercise():
        async with sandbox.sessions() as db:
            user = await db.get(User, "alice")
            user.credits = 2
            db.add(Task(id="refund", user_id="alice", status=initial_status, cost_credits=3, input_mp3_key="audio", input_lyrics_key="lyrics"))
            await db.commit()
        for attempt in range(2):
            async with sandbox.sessions() as db:
                claimed = await fail_task_and_refund(db, "refund", "failed")
                await db.commit()
                assert claimed == (initial_status != TaskStatus.COMPLETED and attempt == 0)
    asyncio.run(exercise())
    expected = 2 if initial_status == TaskStatus.COMPLETED else 5
    assert sandbox.client.get("/api/auth/me", headers=headers()).json()["credits"] == expected


def test_editor_saas_routes_multi_track_and_isolation(sandbox):
    align_key = "results/alice_task/alice_task_alignment.json"
    vocals_key = "results/alice_task/alice_task_vocals.mp3"
    inst_key = "results/alice_task/alice_task_instrumental.mp3"
    audio_key = "uploads/alice/alice_task/source.mp3"

    p_align = sandbox.storage.get_local_path(align_key)
    p_align.parent.mkdir(parents=True, exist_ok=True)
    p_align.write_text('{"lines": [{"text": "hello", "start": 0.5, "end": 1.2, "words": [{"text": "hello", "start": 0.5, "end": 1.2}]}]}')

    p_vocals = sandbox.storage.get_local_path(vocals_key)
    p_vocals.write_bytes(b"vocals")

    p_inst = sandbox.storage.get_local_path(inst_key)
    p_inst.write_bytes(b"inst")

    p_audio = sandbox.storage.get_local_path(audio_key)
    p_audio.parent.mkdir(parents=True, exist_ok=True)
    p_audio.write_bytes(b"audio")

    async def seed():
        async with sandbox.sessions() as db:
            db.add(Task(
                id="alice_task",
                user_id="alice",
                title="My Cloud Song",
                song_title="My Cloud Song",
                status=TaskStatus.COMPLETED,
                alignment_json_key=align_key,
                input_mp3_key=audio_key,
                input_lyrics_key="uploads/alice/alice_task/source.txt",
            ))
            await db.commit()
    asyncio.run(seed())

    # 1. GET /api/editor/songs (列出歌曲工程)
    r = sandbox.client.get("/api/editor/songs", headers=headers("alice"))
    assert r.status_code == 200
    songs = r.json()
    assert len(songs) == 1
    assert songs[0]["name"] == "My Cloud Song"
    assert songs[0]["task_id"] == "alice_task"

    # 2. GET /api/editor/tasks/{task_id}/align
    r = sandbox.client.get("/api/editor/tasks/alice_task/align", headers=headers("alice"))
    assert r.status_code == 200
    assert len(r.json()["lines"]) == 1

    # 3. PUT /api/editor/tasks/{task_id}/align
    new_data = {"lines": [{"text": "updated", "start": 0.6, "end": 1.5, "words": [{"text": "updated", "start": 0.6, "end": 1.5}]}]}
    r = sandbox.client.put("/api/editor/tasks/alice_task/align", json=new_data, headers=headers("alice"))
    assert r.status_code == 200

    # 4. 音轨流获取 (支持 Bearer header 与 ?token=xxx)
    alice_token = auth.create_access_token("alice")
    r_voc = sandbox.client.get("/api/editor/tasks/alice_task/vocals", params={"token": alice_token})
    assert r_voc.status_code == 200
    assert r_voc.content == b"vocals"

    r_inst = sandbox.client.get("/api/editor/tasks/alice_task/inst", headers=headers("alice"))
    assert r_inst.status_code == 200
    assert r_inst.content == b"inst"

    # 5. 租户隔离: Bob 无法访问 Alice 的工程
    assert sandbox.client.get("/api/editor/tasks/alice_task/align", headers=headers("bob")).status_code == 404
    assert sandbox.client.get("/api/editor/tasks/alice_task/vocals", headers=headers("bob")).status_code == 404

