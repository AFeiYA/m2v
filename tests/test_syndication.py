"""
测试全网多平台协同发布中心 (Syndication Manager) 与各平台 Uploader
覆盖 哔哩哔哩、小红书、微信视频号、抖音、YouTube 的配置状态、API 与分发调度
"""
import pytest
from fastapi.testclient import TestClient

from src.bilibili_uploader import bilibili_uploader
from src.douyin_uploader import douyin_uploader
from src.local_editor import app
from src.syndication_manager import PLATFORM_REGISTRY, get_all_platforms_status
from src.wechat_uploader import wechat_uploader
from src.xiaohongshu_uploader import xiaohongshu_uploader
from src.youtube_uploader import youtube_uploader


@pytest.fixture
def client():
    return TestClient(app)


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


def test_get_all_platforms_status():
    """验证聚合状态查询接口正确返回所有平台"""
    status = get_all_platforms_status()
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


def test_youtube_token_configuration(client):
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
