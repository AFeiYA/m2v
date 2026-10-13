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
        id="test-song-id", title="test", lyrics="lyrics", raw_prompt="", audio_url="https://example.invalid/audio", video_url=""))
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


def seed_editor_song(sandbox):
    key = "results/editor/alignment.json"
    path = sandbox.storage.get_local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"duration": 2, "lines": [{"text": "hello", "start": 0, "end": 1, "words": [{"word": "hello", "start": 0, "end": 1}]}]}')
    audio = sandbox.storage.get_local_path("uploads/alice/editor/source.wav")
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"original")
    async def seed():
        async with sandbox.sessions() as db:
            db.add(Task(id="editor", user_id="alice", title="Song", status=TaskStatus.COMPLETED,
                        alignment_json_key=key, input_mp3_key="uploads/alice/editor/source.wav",
                        input_lyrics_key="lyrics.txt"))
            await db.commit()
    asyncio.run(seed())
    return path


def test_missing_tracks_are_not_original_audio(sandbox):
    seed_editor_song(sandbox)
    songs = sandbox.client.get("/api/editor/songs", headers=headers()).json()
    assert songs[0]["has_vocals"] is False
    assert songs[0]["has_instrumental"] is False
    for kind in ("vocals", "inst"):
        assert sandbox.client.get(f"/api/editor/tasks/editor/{kind}", headers=headers()).status_code == 404
    assert sandbox.client.get("/api/editor/tasks/editor/audio", headers=headers()).content == b"original"


@pytest.mark.parametrize("fail", [False, True])
def test_editor_export_options_download_and_isolation(sandbox, monkeypatch, tmp_path, fail):
    from src import editor_operations as ops
    from src.task_store import TaskStore
    monkeypatch.setattr(ops, "jobs", TaskStore(tmp_path / "jobs"))
    seed_editor_song(sandbox)
    seen = []
    def render(alignment, audio, output, options, progress):
        seen.append(options)
        assert audio.read_bytes() == b"original"
        assert alignment.exists()
        if fail:
            raise RuntimeError("render failed")
        output.write_bytes(b"video")
        return {"resolution": [1080, 1920], "size_mb": 1, "video_path": str(output)}
    monkeypatch.setattr(ops, "render_video", render)
    endpoint = "/api/editor/tasks/editor/lyric-video"
    body = {"aspect_ratio": "9:16", "start_time": 0.5, "end_time": 1.5, "background_mode": "solid_black"}
    assert sandbox.client.post(endpoint, json=body, headers=headers("bob")).status_code == 404
    assert sandbox.client.post(endpoint, json={"start_time": 2, "end_time": 1}, headers=headers()).status_code == 422
    res = sandbox.client.post(endpoint, json=body, headers=headers())
    assert res.status_code == 200
    job_id = res.json()["task_id"]
    state_url = f"/api/editor/jobs/{job_id}"
    assert sandbox.client.get(state_url, headers=headers("bob")).status_code == 404
    state = sandbox.client.get(state_url, headers=headers()).json()
    assert state["status"] == ("failed" if fail else "completed")
    assert "user_id" not in state
    assert seen[0]["start_time"] == 0.5
    assert seen[0]["aspect_ratio"] == "9:16"
    if not fail:
        assert "video_path" not in state["result"]
        url = state["result"]["video_url"]
        assert sandbox.client.get(url, headers=headers("bob")).status_code == 404
        assert sandbox.client.get(url, headers=headers()).headers["content-type"] == "video/mp4"
        assert sandbox.client.get(url, headers=headers()).content == b"video"


def test_editor_analysis_keeps_edits_saved_during_inference(sandbox, monkeypatch, tmp_path):
    from src import editor_operations as ops
    from src.task_store import TaskStore
    monkeypatch.setattr(ops, "jobs", TaskStore(tmp_path / "jobs"))
    path = seed_editor_song(sandbox)
    import json
    analysis = types.SimpleNamespace(duration=2, beats=[1], downbeats=[], drum_hits=[], energy_curve=[],
        envelopes=[], bpm=120, metadata={"cache_hit": False}, model_dump=lambda: {"bpm": 120})
    def analyze(audio, cache, force):
        assert audio.read_bytes() == b"original"
        # Simulate a user saving lyrics while the expensive analysis is running.
        payload = json.loads(path.read_text())
        payload["lines"][0]["text"] = "edited during analysis"
        path.write_text(json.dumps(payload))
        return analysis
    monkeypatch.setattr(ops, "analyze_audio", analyze)
    fake = types.ModuleType("src.audio_analyzer")
    fake.detect_cut_candidates = lambda *a: []
    monkeypatch.setitem(sys.modules, "src.audio_analyzer", fake)
    res = sandbox.client.post("/api/editor/tasks/editor/analyze", json={}, headers=headers())
    job_id = res.json()["task_id"]
    status = sandbox.client.get(f"/api/editor/jobs/{job_id}", headers=headers()).json()
    assert status["status"] == "completed"
    assert status["result"]["bpm"] == 120
    payload = sandbox.client.get("/api/editor/tasks/editor/align", headers=headers()).json()
    assert payload["lines"][0]["text"] == "edited during analysis"
    assert payload["analysis"]["bpm"] == 120
    assert sandbox.client.post("/api/editor/tasks/editor/analyze", json={}, headers=headers("bob")).status_code == 404


def test_suno_aliases_reuse_completed_import_and_preserve_edits(sandbox, monkeypatch):
    observed = install_pipeline(sandbox, monkeypatch, False)
    first = submit(sandbox, monkeypatch, "suno").json()
    key = first["task_id"]
    async def edit():
        async with sandbox.sessions() as db:
            task = await db.get(Task, key)
            path = sandbox.output / "edited.json"
            path.write_text('{"manual_edit": true}')
            await sandbox.storage.save(task.alignment_json_key, path)
            user = await db.get(User, "alice")
            user.credits = 0
            await db.commit()
    asyncio.run(edit())
    second = sandbox.client.post("/api/tasks/from-suno", headers=headers(), json={
        "suno_url": "https://suno.com/song/test-song-id?sh=other"})
    assert second.status_code == 200
    assert second.json()["task_id"] == key
    assert len(observed) == 1


def test_suno_changed_lyrics_force_and_user_isolation(sandbox, monkeypatch):
    observed = install_pipeline(sandbox, monkeypatch, False)
    first = submit(sandbox, monkeypatch, "suno").json()
    payload = {"suno_url": "https://suno.com/s/another", "lyrics_text": "updated lyrics"}
    changed = sandbox.client.post("/api/tasks/from-suno", headers=headers(), json=payload)
    assert changed.status_code == 200
    assert changed.json()["task_id"] != first["task_id"]
    repeated = sandbox.client.post("/api/tasks/from-suno", headers=headers(), json=payload)
    assert repeated.json()["task_id"] == changed.json()["task_id"]
    forced = sandbox.client.post("/api/tasks/from-suno", headers=headers(), json={**payload, "force_realign": True})
    assert forced.status_code == 200
    assert forced.json()["task_id"] != changed.json()["task_id"]
    other = sandbox.client.post("/api/tasks/from-suno", headers=headers("bob"), json=payload)
    assert other.status_code == 200
    assert other.json()["task_id"] != changed.json()["task_id"]
    assert len(observed) == 4
    async def verify():
        async with sandbox.sessions() as db:
            task = await db.get(Task, changed.json()["task_id"])
            path = sandbox.output / "snapshot.txt"
            await sandbox.storage.load(task.input_lyrics_key, path)
            assert path.read_text() == "updated lyrics"
            assert await db.get(Task, first["task_id"]) is not None
    asyncio.run(verify())


def test_suno_failed_task_can_retry(sandbox, monkeypatch):
    install_pipeline(sandbox, monkeypatch, True)
    first = submit(sandbox, monkeypatch, "suno").json()
    observed = install_pipeline(sandbox, monkeypatch, False)
    second = sandbox.client.post("/api/tasks/from-suno", headers=headers(), json={"suno_url": "https://suno.com/s/test"})
    assert second.status_code == 200
    assert second.json()["task_id"] != first["task_id"]
    assert len(observed) == 1


def test_suno_remote_lyrics_change_and_options_create_versions(sandbox, monkeypatch):
    from src import suno_fetch
    observed = install_pipeline(sandbox, monkeypatch, False)
    first = submit(sandbox, monkeypatch, "suno").json()
    monkeypatch.setattr(suno_fetch, "fetch_song", lambda url: types.SimpleNamespace(
        id="test-song-id", title="test", lyrics="new remote lyrics", raw_prompt="",
        audio_url="https://example.invalid/audio", video_url=""))
    payload = {"suno_url": "https://suno.com/song/test-song-id"}
    changed = sandbox.client.post("/api/tasks/from-suno", headers=headers(), json=payload)
    assert changed.status_code == 200
    assert changed.json()["task_id"] != first["task_id"]
    different_options = sandbox.client.post("/api/tasks/from-suno", headers=headers(), json={**payload, "language": "en"})
    assert different_options.status_code == 200
    assert different_options.json()["task_id"] != changed.json()["task_id"]
    assert len(observed) == 3


def test_suno_legacy_short_link_is_identified_without_title_guess(sandbox, monkeypatch):
    install_pipeline(sandbox, monkeypatch, False)
    first = submit(sandbox, monkeypatch, "suno").json()
    async def legacy():
        async with sandbox.sessions() as db:
            task = await db.get(Task, first["task_id"])
            task.config_snapshot = {"language": "auto", "skip_separation": False, "ass_only": False, "beat_effects": False}
            task.idempotency_key = None
            task.title = task.song_title = "user changed title"
            await db.commit()
    asyncio.run(legacy())
    second = sandbox.client.post("/api/tasks/from-suno", headers=headers(), json={"suno_url": "https://suno.com/song/test-song-id"})
    assert second.status_code == 200
    assert second.json()["task_id"] == first["task_id"]


def test_suno_concurrent_alias_imports_only_charge_once(sandbox, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from src import suno_fetch
    # Establish mocks without executing a worker.
    monkeypatch.setattr(api_server, "_dispatch_task", lambda *args: None)
    first = submit(sandbox, monkeypatch, "suno").json()
    pending = sandbox.client.post("/api/tasks/from-suno", headers=headers(), json={"suno_url": "https://suno.com/song/test-song-id"})
    assert pending.json()["task_id"] == first["task_id"]
    original_download = suno_fetch.download_song
    barrier = Barrier(2)
    def simultaneous_download(*args, **kwargs):
        barrier.wait(timeout=10)
        return original_download(*args, **kwargs)
    monkeypatch.setattr(suno_fetch, "download_song", simultaneous_download)
    def request(url):
        return sandbox.client.post("/api/tasks/from-suno", headers=headers(), json={
            "suno_url": url, "lyrics_text": "concurrent new lyrics"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(request, "https://suno.com/s/test")
        b = pool.submit(request, "https://suno.com/song/test-song-id")
        responses = [a.result(timeout=20), b.result(timeout=20)]
    assert all(r.status_code == 200 for r in responses)
    assert responses[0].json()["task_id"] == responses[1].json()["task_id"]
    assert sandbox.client.get("/api/auth/me", headers=headers()).json()["credits"] == 3


def test_private_remote_audio_is_served_without_redirect_and_temp_files_removed(sandbox, monkeypatch):
    seed_editor_song(sandbox)
    for filename, data in (("source_vocals.mp3", b"vocals"), ("source_instrumental.mp3", b"instrumental")):
        path = sandbox.storage.get_local_path(f"results/editor/{filename}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    downloaded = []
    class RemoteStorage:
        async def exists(self, key):
            return await sandbox.storage.exists(key)
        async def load(self, key, path):
            downloaded.append(path)
            return await sandbox.storage.load(key, path)
        async def get_url(self, key):
            raise AssertionError("Private editor media must not use public URLs or redirects")
    monkeypatch.setattr(storage, "_storage_instance", RemoteStorage())
    for kind, expected, mime in (("audio", b"original", "audio/wav"),
                                 ("vocals", b"vocals", "audio/mpeg"),
                                 ("inst", b"instrumental", "audio/mpeg")):
        endpoint = f"/api/editor/tasks/editor/{kind}"
        assert sandbox.client.get(endpoint, headers=headers("bob")).status_code == 404
        response = sandbox.client.get(endpoint, headers=headers(), follow_redirects=False)
        assert response.status_code == 200
        assert response.content == expected
        assert response.headers["content-type"] == mime
        assert response.headers["cache-control"] == "private, no-store"
        assert "location" not in response.headers
    assert len(downloaded) == 3
    assert all(not path.exists() for path in downloaded)


@pytest.mark.parametrize("missing", [True, False])
def test_remote_media_errors_are_reported_and_temp_files_removed(sandbox, monkeypatch, missing):
    seed_editor_song(sandbox)
    downloaded = []
    class RemoteStorage:
        async def load(self, key, path):
            downloaded.append(path)
            path.write_bytes(b"partial")
            if missing:
                raise FileNotFoundError(key)
            raise RuntimeError("storage unavailable")
    monkeypatch.setattr(storage, "_storage_instance", RemoteStorage())
    response = sandbox.client.get("/api/editor/tasks/editor/audio", headers=headers())
    assert response.status_code == (404 if missing else 502)
    assert all(not path.exists() for path in downloaded)


def test_firebase_email_verification_is_not_assumed(sandbox, monkeypatch):
    payload = {"sub": "firebase-email-user", "email": "new@example.com", "name": "New Artist",
               "type": "access", "provider": "firebase", "email_verified": False}
    monkeypatch.setattr(auth, "decode_token", lambda token: payload)
    credentials = {"Authorization": "Bearer test-firebase-token"}
    first = sandbox.client.get("/api/auth/me", headers=credentials)
    assert first.status_code == 200
    assert first.json()["is_verified"] is False
    assert first.json()["credits"] == auth.settings.FREE_MONTHLY_QUOTA
    payload["email_verified"] = True
    second = sandbox.client.get("/api/auth/me", headers=credentials)
    assert second.json()["is_verified"] is True
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["credits"] == first.json()["credits"]
