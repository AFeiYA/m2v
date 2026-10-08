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
