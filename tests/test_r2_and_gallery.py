import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from src.local_editor import app
from src.r2_storage import R2StorageManager


def test_r2_storage_graceful_unconfigured(monkeypatch):
    monkeypatch.delenv("R2_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("R2_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("R2_ENDPOINT_URL", raising=False)

    mgr = R2StorageManager()
    assert mgr.is_configured() is False
    assert mgr.get_client() is None
    assert mgr.upload_video("/tmp/nonexistent.mp4") is None

    info = mgr.get_status_info()
    assert info["configured"] is False
    assert info["provider"] == "Cloudflare R2"


def test_r2_storage_configured_and_upload(tmp_path, monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "test_acc_123")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test_key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test_secret")
    monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("R2_PUBLIC_DOMAIN", "https://media.fovea.si")

    dummy_file = tmp_path / "test_sample.mp4"
    dummy_file.write_bytes(b"dummy mp4 content 123456")

    mgr = R2StorageManager()
    assert mgr.is_configured() is True
    assert mgr.endpoint_url == "https://test_acc_123.r2.cloudflarestorage.com"

    mock_client = MagicMock()
    monkeypatch.setattr(mgr, "get_client", lambda: mock_client)

    result = mgr.upload_video(dummy_file, "exports/custom_name.mp4")
    assert result is not None
    assert result["key"] == "exports/custom_name.mp4"
    assert result["url"] == "https://media.fovea.si/exports/custom_name.mp4"
    assert result["bucket"] == "test-bucket"
    assert result["size"] == len(b"dummy mp4 content 123456")

    mock_client.upload_file.assert_called_once()


def test_gallery_and_r2_endpoints(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    song_dir = output_dir / "TestSong"
    exports_dir = song_dir / "motion_exports"
    exports_dir.mkdir(parents=True)

    job_id = "aabbccddeeff00112233445566778899"
    status_file = exports_dir / f"{job_id}_status.json"
    mp4_file = exports_dir / f"{job_id}.mp4"
    mp4_file.write_bytes(b"dummy video bytes")

    status_data = {
        "id": job_id,
        "status": "done",
        "frames": 240,
        "total": 240,
        "created_at": 1700000000,
        "width": 1280,
        "height": 720,
        "cdn_url": f"https://media.fovea.si/exports/{job_id}.mp4"
    }
    status_file.write_text(json.dumps(status_data))

    monkeypatch.setattr(app.state, "scan_dir", output_dir, raising=False)

    with TestClient(app) as client:
        # 1. 检查 /gallery HTML 页面
        res_page = client.get("/gallery")
        assert res_page.status_code == 200
        assert "Motion Gallery" in res_page.text

        # 2. 检查 /api/motion/r2/status 接口
        res_r2 = client.get("/api/motion/r2/status")
        assert res_r2.status_code == 200
        assert "configured" in res_r2.json()

        # 3. 检查 /api/motion/gallery 接口返回数据
        res_gallery = client.get("/api/motion/gallery")
        assert res_gallery.status_code == 200
        items = res_gallery.json()
        assert len(items) >= 1
        matched = next(x for x in items if x["id"] == job_id)
        assert matched["song_title"] == "TestSong"
        assert matched["cdn_url"] == f"https://media.fovea.si/exports/{job_id}.mp4"
        assert matched["aspect"] == "16:9"

        # 4. 检查 /api/motion/render/{job_id}/stream 重定向到 CDN
        res_stream = client.get(f"/api/motion/render/{job_id}/stream", follow_redirects=False)
        assert res_stream.status_code == 307
        assert res_stream.headers["location"] == f"https://media.fovea.si/exports/{job_id}.mp4"
