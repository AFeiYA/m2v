from fastapi.testclient import TestClient
from src import local_editor, suno_fetch


def test_private_song_has_actionable_error_for_both_endpoints(monkeypatch):
    def private(*args, **kwargs):
        raise suno_fetch.SongNotPublishedError("private")

    monkeypatch.setattr(suno_fetch, "fetch_song", private)
    client = TestClient(local_editor.app)
    for endpoint in ("publish_status", "download_mp3"):
        response = client.get(f"/api/suno/{endpoint}", params={"url": "https://suno.com/s/selected-song"})
        assert response.status_code == 400
        assert "Publish" in response.json()["detail"]


def test_publication_network_error_is_not_reported_as_private(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(suno_fetch, "fetch_song", unavailable)
    response = TestClient(local_editor.app).get("/api/suno/publish_status", params={"url": "selected-song"})
    assert response.status_code == 502
    assert "verify" in response.json()["detail"]


def test_private_song_adapts_to_accept_language(monkeypatch):
    def private(*args, **kwargs):
        raise suno_fetch.SongNotPublishedError("private")

    monkeypatch.setattr(suno_fetch, "fetch_song", private)
    client = TestClient(local_editor.app)
    # 1. Chinese header
    res_zh = client.get("/api/suno/publish_status", params={"url": "selected-song"}, headers={"Accept-Language": "zh-CN,zh;q=0.9"})
    assert res_zh.status_code == 400
    assert "尚未公开" in res_zh.json()["detail"]

    # 2. English header
    res_en = client.get("/api/suno/publish_status", params={"url": "selected-song"}, headers={"Accept-Language": "en-US,en;q=0.9"})
    assert res_en.status_code == 400
    assert "not published" in res_en.json()["detail"]
