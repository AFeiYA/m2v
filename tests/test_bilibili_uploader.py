import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from src.bilibili_uploader import (
    BilibiliUploader,
    POPULAR_TIDS,
    bilibili_router,
)
from src.local_editor import app


def test_popular_tids():
    assert len(POPULAR_TIDS) >= 3
    music_tid = next((t for t in POPULAR_TIDS if t["id"] == 28), None)
    assert music_tid is not None
    assert "音乐" in music_tid["name"]


def test_uploader_unconfigured(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    uploader = BilibiliUploader(cookies_path=cookie_file)
    assert uploader.is_configured is False
    status = uploader.get_account_status()
    assert status["is_login"] is False
    assert status["uname"] == ""


def test_uploader_generate_qrcode(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    uploader = BilibiliUploader(cookies_path=cookie_file)

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "code": 0,
        "data": {
            "url": "https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1&qrcode_key=mock_key_123",
            "qrcode_key": "mock_key_123",
        },
    }

    with patch.object(uploader.session, "get", return_value=mock_resp):
        res = uploader.generate_qrcode()
        assert res["success"] is True
        assert res["qrcode_key"] == "mock_key_123"
        assert res["url"].startswith("https://passport.bilibili.com")


def test_uploader_poll_qrcode_flow(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    uploader = BilibiliUploader(cookies_path=cookie_file)

    # 1. 模拟等待扫码 (86101)
    mock_resp_waiting = MagicMock()
    mock_resp_waiting.json.return_value = {
        "code": 0,
        "data": {"code": 86101, "message": "未扫码"},
    }
    with patch.object(uploader.session, "get", return_value=mock_resp_waiting):
        res = uploader.poll_qrcode("test_key")
        assert res["status"] == "waiting"
        assert res["is_login"] is False

    # 2. 模拟扫码成功登录 (0)
    mock_resp_success = MagicMock()
    mock_resp_success.json.return_value = {
        "code": 0,
        "data": {
            "code": 0,
            "message": "登录成功",
            "url": "https://passport.biligame.com/crossDomain?DedeUserID=123456&bili_jct=mock_csrf&SESSDATA=mock_sess",
        },
    }
    with patch.object(uploader.session, "get", return_value=mock_resp_success):
        with patch.object(uploader, "get_account_status", return_value={"is_login": True, "is_logged_in": True, "uname": "测试UP主"}):
            res_succ = uploader.poll_qrcode("test_key")
            assert res_succ["status"] == "success"
            assert res_succ["is_login"] is True
            assert uploader.cookies["bili_jct"] == "mock_csrf"
            assert uploader.cookies["SESSDATA"] == "mock_sess"
            assert cookie_file.exists()


def test_uploader_logout(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(json.dumps({"cookies": {"SESSDATA": "123", "bili_jct": "csrf"}}))
    uploader = BilibiliUploader(cookies_path=cookie_file)
    assert uploader.is_configured is True

    res = uploader.logout()
    assert res["success"] is True
    assert uploader.is_configured is False
    assert not cookie_file.exists()


def test_uploader_submit_archive(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(json.dumps({"cookies": {"SESSDATA": "123", "bili_jct": "csrf"}}))
    uploader = BilibiliUploader(cookies_path=cookie_file)

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "code": 0,
        "data": {"bvid": "BV1MockTest999", "aid": 12345678},
    }

    with patch.object(uploader.session, "post", return_value=mock_resp):
        res = uploader.submit_archive(
            filename="mock_filename_123",
            title="测试音乐MV",
            desc="Suno 音乐日记",
            tags=["AI音乐", "原创音乐"],
            tid=28,
        )
        assert res["success"] is True
        assert res["bvid"] == "BV1MockTest999"
        assert res["aid"] == 12345678
        assert "BV1MockTest999" in res["video_url"]


def test_bilibili_fastapi_endpoints(monkeypatch):
    from src.bilibili_uploader import bilibili_uploader

    with TestClient(app) as client:
        # 1. /api/bilibili/tids
        res_tids = client.get("/api/bilibili/tids")
        assert res_tids.status_code == 200
        data_tids = res_tids.json()
        assert "tids" in data_tids
        assert len(data_tids["tids"]) >= 3

        # 2. /api/bilibili/status (未登录)
        monkeypatch.setattr(bilibili_uploader, "cookies", {})
        monkeypatch.setattr(bilibili_uploader, "get_account_status", lambda: {"is_logged_in": False, "is_login": False, "uname": ""})
        res_status = client.get("/api/bilibili/status")
        assert res_status.status_code == 200
        assert res_status.json()["is_login"] is False

        # 3. 未登录时尝试发布视频 -> 400
        res_publish_fail = client.post(
            "/api/bilibili/publish",
            json={
                "video_source": "https://media.fovea.si/exports/test.mp4",
                "title": "测试发布",
            },
        )
        assert res_publish_fail.status_code == 400

        # 4. 登录状态下发布视频 -> 创建任务成功
        monkeypatch.setattr(bilibili_uploader, "cookies", {"SESSDATA": "valid_sess", "bili_jct": "valid_csrf"})
        monkeypatch.setattr(
            bilibili_uploader,
            "publish_video",
            lambda **kwargs: {"bvid": "BV1TestMock", "aid": 888, "video_url": "https://bilibili.com/video/BV1TestMock"},
        )

        res_pub = client.post(
            "/api/bilibili/publish",
            json={
                "video_source": "https://media.fovea.si/exports/test.mp4",
                "title": "测试一键发布",
                "tid": 28,
            },
        )
        assert res_pub.status_code == 200
        task_id = res_pub.json().get("task_id")
        assert task_id is not None

        # 5. 查询任务状态
        res_task = client.get(f"/api/bilibili/tasks/{task_id}")
        assert res_task.status_code == 200
        task_data = res_task.json()
        assert task_data["id"] == task_id
        assert "status" in task_data
