import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.douyin_uploader import DouyinUploader, RECOMMENDED_DOUYIN_TAGS


def test_recommended_douyin_tags():
    assert len(RECOMMENDED_DOUYIN_TAGS) >= 3
    assert "AI音乐" in RECOMMENDED_DOUYIN_TAGS


def test_clean_locks_broken_symlinks(tmp_path):
    pdir = tmp_path / "douyin_profile"
    pdir.mkdir(parents=True)

    # 模拟 Chromium 异常崩溃后遗留的 broken symlink (指向不存在的目标)
    dead_target = pdir / "non_existent_host_pid"
    lock_file = pdir / "SingletonLock"
    os.symlink(str(dead_target), str(lock_file))

    cookie_file = pdir / "SingletonCookie"
    cookie_file.write_text("1234")

    # 验证常规 Path.exists() 对 broken symlink 会返回 False
    assert lock_file.exists() is False
    assert os.path.lexists(str(lock_file)) is True

    uploader = DouyinUploader(profile_dir=pdir, cookies_path=tmp_path / "cookies.json")
    uploader._clean_locks()

    # 验证清理后所有单例锁已彻底被 unlink
    assert os.path.lexists(str(lock_file)) is False
    assert os.path.lexists(str(cookie_file)) is False


def test_douyin_account_status_unconfigured(tmp_path):
    uploader = DouyinUploader(profile_dir=tmp_path / "pdir", cookies_path=tmp_path / "cookies.json")
    status = uploader.get_account_status()
    assert status["is_logged_in"] is False
    assert status["is_login"] is False
    assert status["uname"] == ""


def test_douyin_account_status_with_http_user_info(tmp_path):
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text(json.dumps({
        "cookies": {"sessionid": "mock_session_123"},
        "user": {"is_logged_in": True, "uname": "抖音创作者"}
    }))

    uploader = DouyinUploader(profile_dir=tmp_path / "pdir", cookies_path=cookies_file)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status_code": 0,
        "user": {
            "nickname": "Luca",
            "avatar_thumb": {"url_list": ["https://mock.douyin.com/avatar.jpg"]}
        }
    }

    with patch("requests.Session.get", return_value=mock_resp):
        status = uploader.get_account_status()
        assert status["is_logged_in"] is True
        assert status["uname"] == "Luca"
        assert status["avatar"] == "https://mock.douyin.com/avatar.jpg"
