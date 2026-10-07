"""
测试会话沙箱 (Session Sandbox) 与多租户凭据隔离机制
"""
import shutil
import tempfile
from pathlib import Path
import pytest
from fastapi import HTTPException

from src.session_manager import (
    validate_session_id,
    resolve_session_id,
    get_session_dir,
    get_uploader_for_session,
    clear_session_data,
    acquire_publish_lock,
    release_publish_lock,
    save_publish_receipt,
    get_publish_receipts,
    clean_expired_sessions,
)


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


def test_resolve_session_id():
    """验证从 Header / Query 等提取 session_id"""
    # 缺省返回 default
    assert resolve_session_id() == "default"

    # Header 优先
    assert resolve_session_id(x_session_id="session_header_123") == "session_header_123"

    # Query 参数
    assert resolve_session_id(session_id="session_query_123") == "session_query_123"

    # 非法 ID 抛 400
    with pytest.raises(HTTPException) as exc:
        resolve_session_id(x_session_id="../malicious")
    assert exc.value.status_code == 400


def test_session_dir_isolation():
    """验证每个 session 获得完全隔离的沙箱目录"""
    default_dir = get_session_dir("default")
    assert default_dir.name == "work"

    user_a_id = "test_user_alpha_1"
    user_b_id = "test_user_beta_2"

    dir_a = get_session_dir(user_a_id)
    dir_b = get_session_dir(user_b_id)

    assert dir_a.exists()
    assert dir_b.exists()
    assert dir_a != dir_b
    assert dir_a.name == user_a_id
    assert dir_b.name == user_b_id

    # 清理测试目录
    clear_session_data(user_a_id)
    clear_session_data(user_b_id)
    assert not dir_a.exists()
    assert not dir_b.exists()


def test_uploader_isolation_between_sessions():
    """验证不同 session 的 Uploader 实例指向不同的 cookies 文件与 profile 路径"""
    sid_1 = "test_session_user_01"
    sid_2 = "test_session_user_02"

    wx_1 = get_uploader_for_session("wechat", sid_1)
    wx_2 = get_uploader_for_session("wechat", sid_2)

    assert wx_1 is not wx_2
    assert wx_1.cookies_path != wx_2.cookies_path
    assert wx_1.profile_dir != wx_2.profile_dir
    assert sid_1 in str(wx_1.cookies_path)
    assert sid_2 in str(wx_2.cookies_path)

    # 清理
    clear_session_data(sid_1)
    clear_session_data(sid_2)


def test_publish_idempotency_lock():
    """验证并发重复发布互斥锁"""
    sid = "test_lock_user_1"
    video = "test_song.mp4"
    platform = "wechat"

    # 首次获取锁成功
    assert acquire_publish_lock(sid, platform, video) is True

    # 再次获取（重复提交）被拦截
    assert acquire_publish_lock(sid, platform, video) is False

    # 另一个 session 应该不受影响
    assert acquire_publish_lock("another_user_2", platform, video) is True

    # 释放锁后可再次获取
    release_publish_lock(sid, platform, video)
    assert acquire_publish_lock(sid, platform, video) is True
    release_publish_lock(sid, platform, video)
    release_publish_lock("another_user_2", platform, video)


def test_receipts_persistence():
    """验证发布回执在独立沙箱内的持久化与读取"""
    sid = "test_receipts_user_1"
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


def test_api_session_status_isolation():
    """验证 HTTP 接口能够识别不同用户的会话并返回隔离的 session_id"""
    from fastapi.testclient import TestClient
    from src.local_editor import app

    client = TestClient(app)

    res_alice = client.get("/api/syndicate/status", headers={"X-Session-ID": "sess_alice_001"})
    assert res_alice.status_code == 200
    assert res_alice.json()["session_id"] == "sess_alice_001"

    res_bob = client.get("/api/syndicate/status", headers={"X-Session-ID": "sess_bob_002"})
    assert res_bob.status_code == 200
    assert res_bob.json()["session_id"] == "sess_bob_002"

    # 清理
    clear_session_data("sess_alice_001")
    clear_session_data("sess_bob_002")


def test_api_session_clear():
    """验证用户主动销毁云端凭据接口 (POST /api/syndicate/session/clear)"""
    from fastapi.testclient import TestClient
    from src.local_editor import app

    client = TestClient(app)
    sid = "sess_to_be_cleared"

    # 先访问创建沙箱
    sdir = get_session_dir(sid)
    assert sdir.exists()

    res = client.post("/api/syndicate/session/clear", headers={"X-Session-ID": sid})
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert not sdir.exists()


def test_api_publish_duplicate_conflict():
    """验证防重复提交机制在 HTTP 层面拦截并发请求并返回 409 Conflict"""
    from fastapi.testclient import TestClient
    from src.local_editor import app

    client = TestClient(app)
    sid = "sess_conflict_user"
    video = "conflict_video.mp4"

    # 人工先占住互斥锁
    acquire_publish_lock(sid, "bilibili", video)

    try:
        res = client.post(
            "/api/syndicate/publish",
            headers={"X-Session-ID": sid},
            json={
                "video_source": video,
                "title": "测试防重",
                "platforms": ["bilibili"],
            },
        )
        assert res.status_code == 409
        assert "正在发布该视频，请勿重复提交" in res.json()["detail"]
    finally:
        release_publish_lock(sid, "bilibili", video)
        clear_session_data(sid)


def test_api_session_receipts():
    """验证查询会话专属发布历史回执接口 (GET /api/syndicate/receipts)"""
    from fastapi.testclient import TestClient
    from src.local_editor import app

    client = TestClient(app)
    sid = "sess_receipts_user"

    save_publish_receipt(sid, {
        "task_id": "receipt_test_01",
        "title": "回执测试视频",
        "video_source": "test.mp4",
        "status": "completed",
    })

    res = client.get("/api/syndicate/receipts", headers={"X-Session-ID": sid})
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] == sid
    assert len(data["receipts"]) >= 1
    assert data["receipts"][0]["task_id"] == "receipt_test_01"

    clear_session_data(sid)

