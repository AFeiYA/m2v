"""
SaaS Web API 与编辑器集成端到端集成测试

模拟完整流程:
1. 用户注册与登录 (JWT)
2. 音频+歌词上传与任务创建
3. 模拟异步任务执行 (通过 Celery Eager 模式同步执行)
4. 查看任务状态与产物
5. 编辑器 API 对齐 JSON 的获取、更新 (校验不变量 + .bak 备份)
6. 产物下载
"""

import os
import tempfile
import json
import shutil
from pathlib import Path
from unittest import mock

import pytest
import nest_asyncio
nest_asyncio.apply()

from fastapi.testclient import TestClient

# ── 1. 设置环境变量覆盖默认配置 ─────────────────────────────────────
# 必须在导入任何 src 模块之前设置！
test_dir = tempfile.TemporaryDirectory()
test_db_path = Path(test_dir.name) / "test_m2v.db"
test_upload_dir = Path(test_dir.name) / "uploads"
test_output_dir = Path(test_dir.name) / "output"

test_upload_dir.mkdir(parents=True, exist_ok=True)
test_output_dir.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{test_db_path}"
os.environ["CELERY_ALWAYS_EAGER"] = "True"
os.environ["UPLOAD_DIR"] = str(test_upload_dir)
os.environ["OUTPUT_DIR"] = str(test_output_dir)
os.environ["STORAGE_BACKEND"] = "local"
os.environ["SECRET_KEY"] = "test-secret-key-for-integration-testing"

# ── 2. 导入应用 ───────────────────────────────────────────────────
from src.api_server import app
from src.database import create_tables, engine, Base
from src.models import User, Task

# ── 3. Mock Pipeline 执行 ─────────────────────────────────────────
def mock_process_one(mp3_path, lyrics_path, output_dir, background, config, on_progress=None):
    stem = mp3_path.stem
    if on_progress:
        on_progress("preprocessing", 10, "预处理中")
        on_progress("separating", 30, "人声分离完成")
        on_progress("aligning", 60, "词级对齐完成")
        on_progress("subtitle", 80, "ASS 字幕已生成")
        on_progress("compositing", 95, "视频合成中")

    # 创建测试产物文件
    # A. 对齐 JSON
    alignment_data = {
        "lines": [
            {
                "text": "影子在墙上",
                "start": 1.0,
                "end": 3.0,
                "words": [
                    {"word": "影", "start": 1.0, "end": 1.5},
                    {"word": "子", "start": 1.5, "end": 2.0},
                    {"word": "在", "start": 2.0, "end": 2.5},
                    {"word": "墙", "start": 2.5, "end": 3.0}
                ]
            }
        ]
    }
    align_json = output_dir / f"{stem}_alignment.json"
    with open(align_json, "w", encoding="utf-8") as f:
        json.dump(alignment_data, f, ensure_ascii=False, indent=2)

    # B. ASS
    ass_file = output_dir / f"{stem}.ass"
    with open(ass_file, "w", encoding="utf-8") as f:
        f.write("[Script Info]\nTitle: Test Subtitle\n")

    # C. MP4
    mp4_file = output_dir / f"{stem}.mp4"
    with open(mp4_file, "wb") as f:
        f.write(b"mock video data")

    return mp4_file


# ── 4. Pytest Fixture ─────────────────────────────────────────────
@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """在测试模块开始前初始化数据库，结束后清理"""
    import asyncio
    # 同步运行数据库建表
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(create_tables())
    loop.close()

    yield

    # 清理临时文件目录
    test_dir.cleanup()


@pytest.fixture
def client():
    return TestClient(app)


# ── 5. 测试用例 ───────────────────────────────────────────────────

def test_full_saas_flow(client):
    username = "testuser"
    password = "securepassword"
    email = "testuser@example.com"

    # 5.1 用户注册
    reg_resp = client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password}
    )
    assert reg_resp.status_code == 200, reg_resp.text
    assert "access_token" in reg_resp.json()

    # 重复注册检查
    dup_resp = client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password}
    )
    assert dup_resp.status_code == 409

    # 5.2 用户登录
    login_resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": password}
    )
    assert login_resp.status_code == 200, login_resp.text
    tokens = login_resp.json()
    assert "access_token" in tokens
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # 获取当前用户信息
    me_resp = client.get("/api/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == email

    # 5.3 上传文件并创建任务
    # 模拟歌词和音频二进制数据
    mp3_data = b"MOCK_MP3_DATA_CONSTANT_LENGTH_PADDING"
    lyrics_data = "第一句歌词\n第二句歌词".encode("utf-8")

    files = {
        "mp3": ("test_song.mp3", mp3_data, "audio/mpeg"),
        "lyrics": ("test_lyrics.txt", lyrics_data, "text/plain")
    }

    # 用 mock 拦截 pipeline 执行，否则在没有 GPU/模型文件的环境下会出错
    with mock.patch("src.main.process_one", side_effect=mock_process_one) as mock_run:
        upload_resp = client.post(
            "/api/upload",
            headers=headers,
            files=files,
            params={
                "language": "zh",
                "skip_separation": True,
                "ass_only": False,
                "beat_effects": False
            }
        )
        assert upload_resp.status_code == 200, upload_resp.text
        upload_data = upload_resp.json()
        assert "task_id" in upload_data
        task_id = upload_data["task_id"]
        assert mock_run.called

    # 5.4 查看任务状态 (应该已经 completed，因为 celery_always_eager=True)
    task_resp = client.get(f"/api/tasks/{task_id}", headers=headers)
    assert task_resp.status_code == 200
    task_data = task_resp.json()
    assert task_data["status"] == "completed"
    assert task_data["progress"] == 100
    assert "output_mp4_key" in task_data
    assert task_data["output_mp4_key"] is not None

    # 5.5 编辑器 API：列出可编辑列表
    editor_songs_resp = client.get("/api/editor/songs", headers=headers)
    assert editor_songs_resp.status_code == 200
    songs_list = editor_songs_resp.json()
    assert len(songs_list) >= 1
    assert any(s["task_id"] == task_id for s in songs_list)

    # 5.6 编辑器 API：获取对齐数据
    align_resp = client.get(f"/api/editor/tasks/{task_id}/align", headers=headers)
    assert align_resp.status_code == 200
    align_data = align_resp.json()
    assert "lines" in align_data
    assert len(align_data["lines"]) == 1
    assert align_data["lines"][0]["text"] == "影子在墙上"

    # 5.7 编辑器 API：修改并保存对齐数据 (测试不变量校验与 .bak 生成)
    modified_align_data = {
        "lines": [
            {
                "text": "影子在墙上",
                "start": 1.0,
                "end": 3.0,
                "words": [
                    {"word": "影", "start": 1.0, "end": 1.4},  # 从 1.5 缩短为 1.4
                    {"word": "子", "start": 1.4, "end": 2.0},  # 相邻字左边界级联对齐到 1.4
                    {"word": "在", "start": 2.0, "end": 2.5},
                    {"word": "墙", "start": 2.5, "end": 3.0}
                ]
            }
        ]
    }
    # 保存成功
    save_resp = client.put(
        f"/api/editor/tasks/{task_id}/align",
        headers=headers,
        json=modified_align_data
    )
    assert save_resp.status_code == 200

    # 验证 .bak 文件生成
    bak_path = Path(test_upload_dir) / f"results/{task_id}/test_song_alignment.json.bak"
    assert bak_path.exists(), f"备份文件应存在于: {bak_path}"

    # 测试校验不变量失败：end < start (1.0 < 1.4)
    invalid_align_data = {
        "lines": [
            {
                "text": "影子在墙上",
                "start": 1.0,
                "end": 3.0,
                "words": [
                    {"word": "影", "start": 1.0, "end": 1.4},
                    {"word": "子", "start": 1.4, "end": 1.0},  # end < start
                    {"word": "在", "start": 2.0, "end": 2.5},
                    {"word": "墙", "start": 2.5, "end": 3.0}
                ]
            }
        ]
    }
    bad_save_resp = client.put(
        f"/api/editor/tasks/{task_id}/align",
        headers=headers,
        json=invalid_align_data
    )
    assert bad_save_resp.status_code == 422

    # 5.8 文件下载
    # 下载视频
    download_mp4_resp = client.get(
        f"/api/tasks/{task_id}/download/mp4",
        headers=headers
    )
    assert download_mp4_resp.status_code == 200
    assert download_mp4_resp.content == b"mock video data"

    # 下载 ASS 字幕
    download_ass_resp = client.get(
        f"/api/tasks/{task_id}/download/ass",
        headers=headers
    )
    assert download_ass_resp.status_code == 200
    assert b"Test Subtitle" in download_ass_resp.content
