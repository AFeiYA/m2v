"""YouTube 本地合规发布与巡检模块 单元测试"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.local_editor import app
from src.youtube_uploader import (
    YouTubeUploader,
    generate_youtube_metadata,
    is_local_request,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# 1. 环境门禁与安全判定 (Local-Only Guard)
# ---------------------------------------------------------------------------

class TestLocalOnlyGuard:
    def test_local_environment_detected(self):
        """测试本地单机/测试环境下返回 True"""
        mock_req = MagicMock()
        mock_req.client.host = "127.0.0.1"
        assert is_local_request(mock_req) is True

        mock_req.client.host = "localhost"
        assert is_local_request(mock_req) is True

        assert is_local_request(None) is True

    def test_cloud_environment_blocked(self, monkeypatch):
        """测试远程云端部署 (staging / production) 下强制返回 False"""
        monkeypatch.setenv("DEPLOY_ENV", "staging")
        mock_req = MagicMock()
        mock_req.client.host = "127.0.0.1"
        assert is_local_request(mock_req) is False

        monkeypatch.setenv("DEPLOY_ENV", "production")
        assert is_local_request(mock_req) is False


# ---------------------------------------------------------------------------
# 2. 卡拉OK高曝光与免责声明元数据生成 (Metadata Generator)
# ---------------------------------------------------------------------------

class TestMetadataGenerator:
    def test_metadata_structure(self):
        meta = generate_youtube_metadata(
            title="Everglow",
            artist="Coldplay",
            style="Piano Ballad",
        )
        assert "Coldplay - Everglow" in meta["title"]
        assert len(meta["title"]) <= 100
        assert "Karaoke" in meta["tags"]
        assert "Coldplay" in meta["tags"]
        assert "M2V Motion Studio" in meta["description"]
        assert "Copyright & Content ID Notice" in meta["description"]
        assert "Monetization" in meta["description"]

    def test_overlong_title_truncation(self):
        very_long = "A" * 120
        meta = generate_youtube_metadata(title=very_long, artist="Artist")
        assert len(meta["title"]) <= 100
        assert meta["title"].endswith("...")


# ---------------------------------------------------------------------------
# 3. 核心上传器逻辑 (Dry-Run、合规巡检与可见性切换)
# ---------------------------------------------------------------------------

class TestYouTubeUploaderCore:
    def test_account_status_unauthenticated(self):
        with tempfile.TemporaryDirectory() as td:
            cred_path = Path(td) / "credentials.json"
            uploader = YouTubeUploader(credentials_path=cred_path)
            status = uploader.get_account_status()
            assert status["is_logged_in"] is False
            assert "未连接" in status["message"]

    def test_dry_run_publishing(self):
        with tempfile.TemporaryDirectory() as td:
            video_file = Path(td) / "test.mp4"
            video_file.write_bytes(b"\x00" * 1024)  # 1KB dummy file

            uploader = YouTubeUploader(credentials_path=Path(td) / "cred.json")
            result = uploader.publish_video(
                video_source=str(video_file),
                title="Test Video",
                dry_run=True,
                privacy_status="unlisted",
            )
            assert result["success"] is True
            assert result["dry_run"] is True
            assert "演练通过" in result["message"]

    @patch("requests.get")
    def test_check_compliance_safe_claim(self, mock_get):
        """测试 Content ID 正常版权认领 (safe claim)"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [{
                "snippet": {"title": "Coldplay - Everglow"},
                "status": {"uploadStatus": "processed", "privacyStatus": "unlisted"},
                "contentDetails": {"licensedContent": True},
            }]
        }
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as td:
            uploader = YouTubeUploader(credentials_path=Path(td) / "cred.json")
            uploader.credentials = {"access_token": "mock_token"}
            res = uploader.check_video_compliance("mock_vid_123")
            assert res["success"] is True
            assert res["safety"] == "safe_claim"
            assert res["can_publish_public"] is True
            assert "版权扫描已完成" in res["message"]

    @patch("requests.get")
    def test_check_compliance_region_restricted(self, mock_get):
        """测试部分地区受限 (如俄罗斯/特定国家受限，其余主流国家放行)"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [{
                "snippet": {"title": "Coldplay - Everglow"},
                "status": {"uploadStatus": "processed", "privacyStatus": "unlisted"},
                "contentDetails": {
                    "licensedContent": True,
                    "regionRestriction": {"blocked": ["RU", "BY"]},
                },
            }]
        }
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as td:
            uploader = YouTubeUploader(credentials_path=Path(td) / "cred.json")
            uploader.credentials = {"access_token": "mock_token"}
            res = uploader.check_video_compliance("mock_vid_123")
            assert res["success"] is True
            assert res["safety"] == "region_restricted"
            assert res["can_publish_public"] is True
            assert "RU, BY" in res["message"]

    @patch("requests.get")
    def test_check_compliance_blocked(self, mock_get):
        """测试全球封禁 (Blocked worldwide)"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [{
                "snippet": {"title": "Blocked Song"},
                "status": {"uploadStatus": "rejected", "rejectionReason": "copyright"},
                "contentDetails": {},
            }]
        }
        mock_get.return_value = mock_resp

        with tempfile.TemporaryDirectory() as td:
            uploader = YouTubeUploader(credentials_path=Path(td) / "cred.json")
            uploader.credentials = {"access_token": "mock_token"}
            res = uploader.check_video_compliance("mock_vid_123")
            assert res["success"] is True
            assert res["safety"] == "blocked"
            assert res["can_publish_public"] is False
            assert "全球封禁" in res["message"]

    @patch("requests.put")
    def test_update_video_privacy(self, mock_put):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_put.return_value = mock_resp

        with tempfile.TemporaryDirectory() as td:
            uploader = YouTubeUploader(credentials_path=Path(td) / "cred.json")
            uploader.credentials = {"access_token": "mock_token"}
            res = uploader.update_video_privacy("mock_vid_123", "public")
            assert res["success"] is True
            assert res["privacy_status"] == "public"


# ---------------------------------------------------------------------------
# 4. FastAPI 路由集成测试
# ---------------------------------------------------------------------------

class TestYouTubeRouterEndpoints:
    def test_get_status_includes_is_local(self):
        resp = client.get("/api/youtube/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "is_local" in data
        assert data["is_local"] is True

    def test_suggest_metadata_endpoint(self):
        resp = client.post("/api/youtube/metadata/suggest", json={
            "title": "Everglow",
            "artist": "Coldplay",
            "style": "Acoustic",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "Coldplay - Everglow" in data["title"]
        assert "tags" in data
        assert len(data["tags"]) > 0

    def test_publish_dry_run_endpoint(self):
        with tempfile.TemporaryDirectory() as td:
            video_file = Path(td) / "dummy.mp4"
            video_file.write_bytes(b"\x00" * 512)

            resp = client.post("/api/youtube/publish", json={
                "video_source": str(video_file),
                "title": "Dry Run Video",
                "dry_run": True,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "task_id" in data
            task_id = data["task_id"]

            # 轮询任务完成
            task_resp = client.get(f"/api/youtube/tasks/{task_id}")
            assert task_resp.status_code == 200

    def test_cloud_environment_blocks_real_publish(self, monkeypatch):
        """测试在云端环境下直接拒绝真实发布请求"""
        monkeypatch.setenv("DEPLOY_ENV", "staging")
        with tempfile.TemporaryDirectory() as td:
            video_file = Path(td) / "dummy.mp4"
            video_file.write_bytes(b"\x00" * 512)

            resp = client.post("/api/youtube/publish", json={
                "video_source": str(video_file),
                "title": "Blocked Video",
                "dry_run": False,
            })
            assert resp.status_code == 403
            assert "已禁用直接上传至 YouTube" in resp.json()["detail"]
