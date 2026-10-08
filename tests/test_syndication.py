"""
测试全网多平台协同发布中心 (Syndication Manager) 与各平台 Uploader
覆盖 哔哩哔哩、小红书、微信视频号、抖音、YouTube 的配置状态、API 与分发调度
"""
import importlib
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src.bilibili_uploader import bilibili_uploader
from src.douyin_uploader import douyin_uploader
from src.local_editor import app
from src.syndication_manager import PLATFORM_REGISTRY, get_all_platforms_status
from src.session_manager import resolve_session_id
from src.wechat_uploader import wechat_uploader
from src.xiaohongshu_uploader import xiaohongshu_uploader
from src.youtube_uploader import youtube_uploader


TEST_SESSION = "syndication_test_session"


@pytest.fixture(autouse=True)
def platform_uploaders(monkeypatch):
    """Never read local credentials, access platform APIs, or overwrite tokens."""
    uploaders = {}
    for pid in PLATFORM_REGISTRY:
        uploader = Mock()
        uploader.get_account_status.return_value = {"is_logged_in": False, "uname": ""}
        uploader.set_tokens.return_value = {"success": True}
        uploader.logout.return_value = {"success": True}
        uploaders[pid] = uploader

    def lookup(pid, session_id):
        assert session_id == TEST_SESSION
        return uploaders[pid]

    for name in ["syndication_manager", "bilibili_uploader", "xiaohongshu_uploader",
                 "wechat_uploader", "douyin_uploader", "youtube_uploader"]:
        monkeypatch.setattr(importlib.import_module(f"src.{name}"), "get_uploader_for_session", lookup)
    return uploaders


@pytest.fixture
def client():
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[resolve_session_id] = lambda: TEST_SESSION
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_platform_registry_completeness():
    """验证所有 5 个核心平台均已正确注册"""
    expected = {"bilibili", "xiaohongshu", "wechat", "douyin", "youtube"}
    assert set(PLATFORM_REGISTRY.keys()) == expected

    for pid in expected:
        meta = PLATFORM_REGISTRY[pid]
        assert meta["id"] == pid
        assert meta["name"]
        assert meta["icon"]
        assert meta["uploader"] is not None


@pytest.mark.parametrize("bilibili_logged_in", [False, True])
def test_get_all_platforms_status(platform_uploaders, bilibili_logged_in):
    """验证聚合状态查询接口正确返回所有平台"""
    platform_uploaders["bilibili"].get_account_status.return_value = {
        "is_logged_in": bilibili_logged_in, "uname": "test-account" if bilibili_logged_in else "",
    }
    status = get_all_platforms_status(session_id=TEST_SESSION)
    assert "platforms" in status
    assert "configured_count" in status
    assert status["total_count"] == 5

    platforms = status["platforms"]
    assert "bilibili" in platforms
    assert "xiaohongshu" in platforms
    assert "wechat" in platforms
    assert "douyin" in platforms
    assert "youtube" in platforms

    # 验证 Bilibili 字段结构
    assert "is_logged_in" in platforms["bilibili"]
    assert isinstance(platforms["bilibili"]["is_logged_in"], bool)
    assert "uname" in platforms["bilibili"]
    assert platforms["bilibili"]["is_logged_in"] is bilibili_logged_in
    assert status["configured_count"] == int(bilibili_logged_in)
    assert status["session_id"] == TEST_SESSION


def test_status_alias_and_platform_failure(platform_uploaders):
    """One failed platform must not hide the remaining account states."""
    platform_uploaders["youtube"].get_account_status.return_value = {"is_login": True, "face": "avatar.png"}
    platform_uploaders["wechat"].get_account_status.side_effect = RuntimeError("status unavailable")
    status = get_all_platforms_status(session_id=TEST_SESSION)
    assert status["configured_count"] == 1
    assert status["platforms"]["youtube"]["is_logged_in"] is True
    assert status["platforms"]["youtube"]["avatar"] == "avatar.png"
    assert status["platforms"]["wechat"]["is_logged_in"] is False
    assert status["platforms"]["wechat"]["message"] == "status unavailable"
    assert status["total_count"] == 5


def test_api_syndicate_status(client):
    """验证 HTTP GET /api/syndicate/status 响应结构"""
    res = client.get("/api/syndicate/status")
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] == 5
    assert "platforms" in data


def test_api_platform_status_endpoints(client):
    """验证各个独立平台的 status 接口"""
    for endpoint in [
        "/api/bilibili/status",
        "/api/xiaohongshu/status",
        "/api/wechat/status",
        "/api/douyin/status",
        "/api/youtube/status",
    ]:
        res = client.get(endpoint)
        assert res.status_code == 200
        assert "is_logged_in" in res.json()


def test_api_syndicate_publish_validation(client):
    """验证全网多发请求参数校验（未选平台时拒绝）"""
    res = client.post(
        "/api/syndicate/publish",
        json={
            "video_source": "test.mp4",
            "title": "测试",
            "platforms": [],
        },
    )
    assert res.status_code == 400
    assert "至少选择一个" in res.json()["detail"]


def test_youtube_token_configuration(client, platform_uploaders):
    """验证 YouTube Token 设置与清除接口"""
    # 模拟设置 token
    res = client.post(
        "/api/youtube/token",
        json={"access_token": "mock_token_12345", "refresh_token": ""},
    )
    assert res.status_code == 200

    # 退出登录
    res_logout = client.post("/api/youtube/logout")
    assert res_logout.status_code == 200
    assert res_logout.json()["success"] is True
    platform_uploaders["youtube"].set_tokens.assert_called_once_with("mock_token_12345", "")
    platform_uploaders["youtube"].logout.assert_called_once_with()
