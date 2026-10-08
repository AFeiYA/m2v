"""
测试会话沙箱 (Session Sandbox) 与多租户安全隔离机制 (Scheme B)
包含: HMAC-SHA256 令牌签发验签、公网/云端模式 default 会话封禁、
Profile 级并发锁、任务跨租户防越权探测与 ID 泄漏防护、成片库会话隔离等。
"""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.local_editor import app
from src.session_manager import (
    GLOBAL_PUBLISH_SEMAPHORE,
    acquire_publish_lock,
    clean_expired_sessions,
    clear_session_data,
    get_publish_receipts,
    get_session_dir,
    get_uploader_for_session,
    is_default_session_allowed,
    issue_session_token,
    release_publish_lock,
    resolve_session_id,
    save_publish_receipt,
    validate_session_id,
    verify_session_token,
)
from src.syndication_manager import syndicate_lock, syndicate_tasks
from src.bilibili_uploader import publish_tasks as bili_tasks, tasks_lock as bili_lock
from src.wechat_uploader import wx_publish_tasks, wx_tasks_lock


@pytest.fixture(autouse=True)
def isolated_session_storage(tmp_path, monkeypatch):
    """Session deletion/expiry tests must never operate on real user sandboxes."""
    import src.session_manager as manager
    monkeypatch.setattr(manager, "_WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(manager, "_SESSIONS_ROOT", tmp_path / "sessions")
    monkeypatch.setattr(manager, "_SECRET_FILE", tmp_path / "session_secret")
    monkeypatch.setattr(manager, "_SESSION_SECRET", b"test-only-session-secret")
    monkeypatch.setattr(manager, "_uploader_pool", {})
    monkeypatch.setattr(manager, "_active_platform_locks", {})
    for name in ("SPACE_ID", "M2V_MULTIUSER_MODE", "M2V_CLOUD_MODE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client():
    return TestClient(app)


def test_validate_session_id():
    """验证 session_id 格式校验规则"""
    assert validate_session_id("default") is True
    assert validate_session_id("user_12345678") is True
    assert validate_session_id("m2v_test-session_99") is True

    # 长度非法
    assert validate_session_id("short") is False
    assert validate_session_id("a" * 65) is False

    # 路径穿透字符非法
    assert validate_session_id("../evil") is False
    assert validate_session_id("user/123") is False
    assert validate_session_id("user\\123") is False
    assert validate_session_id("user$123") is False
    assert validate_session_id("") is False


def test_token_mint_and_verify():
    """验证服务端 HMAC 令牌签发与验签"""
    token = issue_session_token()
    assert "." in token
    raw_id = verify_session_token(token)
    assert raw_id is not None
    assert raw_id.startswith(("m2v_s_", "s_"))

    # 篡改签名必须被拒绝
    tampered = token[:-4] + ("0000" if token[-4:] != "0000" else "1111")
    assert verify_session_token(tampered) is None

    # 篡改主体必须被拒绝
    tampered_body = "s_evil1234567890." + token.split(".")[1]
    assert verify_session_token(tampered_body) is None

    # 格式错误拒绝
    assert verify_session_token("invalid_token") is None
    assert verify_session_token("") is None


def test_resolve_session_id_security():
    """验证 resolve_session_id 在不同网络/模式下的防护规则"""
    token = issue_session_token()
    raw_id = verify_session_token(token)

    # 1. 本地默认回退
    assert resolve_session_id() == "default"

    # 2. 携带有效 token
    assert resolve_session_id(x_session_id=token) == raw_id

    # 3. 携带伪造 token 抛 401
    with pytest.raises(HTTPException) as exc:
        resolve_session_id(x_session_id="forged_token.abc123")
    assert exc.value.status_code == 401

    # 4. 多租户模式下严禁使用或回退 default
    old_env = os.environ.get("M2V_MULTIUSER_MODE")
    try:
        os.environ["M2V_MULTIUSER_MODE"] = "1"
        assert is_default_session_allowed() is False

        # 未提供 token -> 401
        with pytest.raises(HTTPException) as exc:
            resolve_session_id()
        assert exc.value.status_code == 401

        # 显式传递 default -> 403
        with pytest.raises(HTTPException) as exc:
            resolve_session_id(x_session_id="default")
        assert exc.value.status_code == 403

        # 携带有效签名 token 依然正常通过
        assert resolve_session_id(x_session_id=token) == raw_id
    finally:
        if old_env is None:
            os.environ.pop("M2V_MULTIUSER_MODE", None)
        else:
            os.environ["M2V_MULTIUSER_MODE"] = old_env


def test_session_dir_isolation():
    """验证每个 session 获得完全隔离的沙箱目录"""
    default_dir = get_session_dir("default")
    assert default_dir.name == "work"

    token_a = issue_session_token()
    sid_a = verify_session_token(token_a)
    token_b = issue_session_token()
    sid_b = verify_session_token(token_b)

    dir_a = get_session_dir(sid_a)
    dir_b = get_session_dir(sid_b)

    assert dir_a.exists()
    assert dir_b.exists()
    assert dir_a != dir_b
    assert dir_a.name == sid_a
    assert dir_b.name == sid_b

    # 清理测试目录
    clear_session_data(sid_a)
    clear_session_data(sid_b)
    assert not dir_a.exists()
    assert not dir_b.exists()


def test_uploader_isolation_between_sessions():
    """验证不同 session 的 Uploader 实例指向不同的 cookies 文件与 profile 路径"""
    token_1 = issue_session_token()
    sid_1 = verify_session_token(token_1)
    token_2 = issue_session_token()
    sid_2 = verify_session_token(token_2)

    wx_1 = get_uploader_for_session("wechat", sid_1)
    wx_2 = get_uploader_for_session("wechat", sid_2)

    assert wx_1 is not wx_2
    assert wx_1.cookies_path != wx_2.cookies_path
    assert wx_1.profile_dir != wx_2.profile_dir
    assert sid_1 in str(wx_1.cookies_path)
    assert sid_2 in str(wx_2.cookies_path)

    clear_session_data(sid_1)
    clear_session_data(sid_2)


def test_profile_level_publish_lock():
    """验证并发发布互斥锁细粒度在 (session_id, platform)"""
    token_1 = issue_session_token()
    sid_1 = verify_session_token(token_1)
    token_2 = issue_session_token()
    sid_2 = verify_session_token(token_2)

    # sid_1 锁定 bilibili
    assert acquire_publish_lock(sid_1, "bilibili") is True
    # 同 session 同平台再次获取失败
    assert acquire_publish_lock(sid_1, "bilibili") is False

    # 同 session 不同平台可以并发
    assert acquire_publish_lock(sid_1, "xiaohongshu") is True

    # 不同 session 相同平台互不阻塞
    assert acquire_publish_lock(sid_2, "bilibili") is True

    # 释放锁
    release_publish_lock(sid_1, "bilibili")
    assert acquire_publish_lock(sid_1, "bilibili") is True

    release_publish_lock(sid_1, "bilibili")
    release_publish_lock(sid_1, "xiaohongshu")
    release_publish_lock(sid_2, "bilibili")

    clear_session_data(sid_1)
    clear_session_data(sid_2)


def test_global_publish_semaphore():
    """验证全局浏览器发布并发限制信号量"""
    assert GLOBAL_PUBLISH_SEMAPHORE._value <= 3


def test_receipts_persistence():
    """验证发布回执在独立沙箱内的持久化与读取"""
    token = issue_session_token()
    sid = verify_session_token(token)
    receipt = {
        "task_id": "t123456",
        "title": "测试歌曲MV",
        "video_source": "test.mp4",
        "platforms": ["wechat", "xiaohongshu"],
        "status": "completed",
    }

    save_publish_receipt(sid, receipt)
    saved = get_publish_receipts(sid)
    assert len(saved) >= 1
    assert saved[0]["task_id"] == "t123456"
    assert saved[0]["title"] == "测试歌曲MV"
    assert "timestamp" in saved[0]

    clear_session_data(sid)


def test_api_session_init_and_status(client):
    """验证 HTTP /api/session/init 服务端签发与状态访问"""
    # 1. 签发
    res_init = client.post("/api/session/init")
    assert res_init.status_code == 200
    token = res_init.json()["session_token"]
    assert "." in token

    # 2. 携带有效 token 请求
    res_status = client.get("/api/syndicate/status", headers={"X-Session-ID": token})
    assert res_status.status_code == 200

    # 3. 携带伪造 token 请求
    res_fail = client.get("/api/syndicate/status", headers={"X-Session-ID": "fake_token_123"})
    assert res_fail.status_code == 401

    raw_id = verify_session_token(token)
    clear_session_data(raw_id)


def test_api_session_clear(client):
    """验证用户主动销毁云端凭据接口 (POST /api/syndicate/session/clear)"""
    token = issue_session_token()
    sid = verify_session_token(token)

    sdir = get_session_dir(sid)
    assert sdir.exists()

    res = client.post("/api/syndicate/session/clear", headers={"X-Session-ID": token})
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert not sdir.exists()


def test_cross_session_task_snooping_prevention(client):
    """验证跨会话任务探测拦截与 session_id 泄露防护"""
    token_victim = issue_session_token()
    sid_victim = verify_session_token(token_victim)

    token_attacker = issue_session_token()
    sid_attacker = verify_session_token(token_attacker)

    task_id = "secret_task_999"
    with syndicate_lock:
        syndicate_tasks[task_id] = {
            "id": task_id,
            "session_id": sid_victim,
            "status": "completed",
            "platforms": ["bilibili"],
            "progress": 1.0,
        }

    # 攻击者探测被害人 task_id -> 404
    res_att = client.get(f"/api/syndicate/tasks/{task_id}", headers={"X-Session-ID": token_attacker})
    assert res_att.status_code == 404

    # 被害人本人访问 -> 200, 且响应中剥除 session_id 防止泄漏
    res_vic = client.get(f"/api/syndicate/tasks/{task_id}", headers={"X-Session-ID": token_victim})
    assert res_vic.status_code == 200
    data = res_vic.json()
    assert data["id"] == task_id
    assert "session_id" not in data

    # 平台独立任务路由同样防越权
    with bili_lock:
        bili_tasks[task_id] = {
            "id": task_id,
            "session_id": sid_victim,
            "status": "completed",
            "progress": 1.0,
        }
    res_bili_att = client.get(f"/api/bilibili/tasks/{task_id}", headers={"X-Session-ID": token_attacker})
    assert res_bili_att.status_code == 404

    res_bili_vic = client.get(f"/api/bilibili/tasks/{task_id}", headers={"X-Session-ID": token_victim})
    assert res_bili_vic.status_code == 200
    assert "session_id" not in res_bili_vic.json()

    # 清理
    with syndicate_lock:
        syndicate_tasks.pop(task_id, None)
    with bili_lock:
        bili_tasks.pop(task_id, None)
    clear_session_data(sid_victim)
    clear_session_data(sid_attacker)


def test_api_publish_duplicate_conflict(client):
    """验证防重复提交机制在 HTTP 层面拦截并发请求并返回 409 Conflict"""
    token = issue_session_token()
    sid = verify_session_token(token)

    # 先占住互斥锁
    acquire_publish_lock(sid, "bilibili")

    try:
        res = client.post(
            "/api/syndicate/publish",
            headers={"X-Session-ID": token},
            json={
                "video_source": "test.mp4",
                "title": "测试防重",
                "platforms": ["bilibili"],
            },
        )
        assert res.status_code == 409
        assert "已有任务正在发布中" in res.json()["detail"]
    finally:
        release_publish_lock(sid, "bilibili")
        clear_session_data(sid)


def test_clean_expired_sessions():
    """验证过期沙箱目录后台自动清理"""
    token = issue_session_token()
    sid = verify_session_token(token)
    sdir = get_session_dir(sid)
    meta_file = sdir / "metadata.json"
    # 将活跃时间设为 10 天前
    meta_file.write_text(json.dumps({"last_active": time.time() - 86400 * 10}), encoding="utf-8")

    # 清理阈值设为 7 天 (604800s)
    clean_expired_sessions(max_age_seconds=604800)
    assert not sdir.exists()


def test_motion_session_scoping(client, tmp_path, monkeypatch):
    """验证动效成片库、任务查询、下载与推流的会话沙箱隔离防护"""
    scan_dir = tmp_path / "output"
    song_dir = scan_dir / "my_song"
    exports_dir = song_dir / "motion_exports"
    exports_dir.mkdir(parents=True)
    monkeypatch.setattr(app.state, "scan_dir", scan_dir, raising=False)

    token_a = issue_session_token()
    sid_a = verify_session_token(token_a)
    token_b = issue_session_token()
    sid_b = verify_session_token(token_b)

    # 构造属于 Session A 的导出成片
    job_a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    (exports_dir / f"{job_a}_status.json").write_text(json.dumps({
        "id": job_a,
        "session_id": sid_a,
        "status": "done",
        "created_at": time.time(),
        "total": 300,
    }), encoding="utf-8")
    (exports_dir / f"{job_a}.mp4").write_bytes(b"mock_mp4_a")

    # 构造属于 Session B 的导出成片
    job_b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    (exports_dir / f"{job_b}_status.json").write_text(json.dumps({
        "id": job_b,
        "session_id": sid_b,
        "status": "done",
        "created_at": time.time(),
        "total": 300,
    }), encoding="utf-8")
    (exports_dir / f"{job_b}.mp4").write_bytes(b"mock_mp4_b")

    # 1. Session A 查看展厅，仅展示 job_a
    res_a = client.get("/api/motion/gallery", headers={"X-Session-ID": token_a})
    assert res_a.status_code == 200
    ids_a = [item["id"] for item in res_a.json()]
    assert job_a in ids_a
    assert job_b not in ids_a

    # 2. Session B 查看展厅，仅展示 job_b
    res_b = client.get("/api/motion/gallery", headers={"X-Session-ID": token_b})
    assert res_b.status_code == 200
    ids_b = [item["id"] for item in res_b.json()]
    assert job_b in ids_b
    assert job_a not in ids_b

    # 3. Session B 越权探测 Session A 的任务状态 -> 404
    res_probe = client.get(f"/api/motion/render/{job_a}", headers={"X-Session-ID": token_b})
    assert res_probe.status_code == 404

    # 4. Session B 越权下载 Session A 的成片 -> 404
    res_down = client.get(f"/api/motion/render/{job_a}/download", headers={"X-Session-ID": token_b})
    assert res_down.status_code == 404

    # 5. Session B 越权流式播放 Session A 的成片 -> 404
    res_stream = client.get(f"/api/motion/render/{job_a}/stream", headers={"X-Session-ID": token_b})
    assert res_stream.status_code == 404

    # 6. Session A 正常下载自己的成片 -> 200
    res_down_a = client.get(f"/api/motion/render/{job_a}/download", headers={"X-Session-ID": token_a})
    assert res_down_a.status_code == 200
    assert res_down_a.content == b"mock_mp4_a"

    # 7. 本地 default 会话可查看全量 (单机管理员视图)
    res_def = client.get("/api/motion/gallery")
    assert res_def.status_code == 200
    ids_def = [item["id"] for item in res_def.json()]
    assert job_a in ids_def and job_b in ids_def

    clear_session_data(sid_a)
    clear_session_data(sid_b)

