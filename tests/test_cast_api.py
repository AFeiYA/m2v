"""
Cast Studio API Integration Tests
Tests HTTP endpoints:
- POST /api/characters (Create)
- GET /api/characters (List)
- GET /api/characters/{char_id} (Retrieve)
- POST /api/characters/{char_id}/upload-reference (Multipart image upload)
- GET /api/characters/{char_id}/assets/{filename} (Asset serving)
- POST /api/characters/{char_id}/confirm-version (Lock baseline version)
- POST /api/characters/{char_id}/bind-song (Bind character to song alignment project)
- POST /api/characters/{char_id}/unbind-song (Unbind)
- DELETE /api/characters/{char_id} (Delete)
"""
import io
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.local_editor import app
from src.storyboard_schema import AlignmentProject, AlignedLine, MusicSection


@pytest.fixture
def client_with_tmp_env(tmp_path):
    chars_dir = tmp_path / "characters"
    chars_dir.mkdir(parents=True)
    scan_dir = tmp_path / "songs"
    scan_dir.mkdir(parents=True)

    app.state.characters_dir = chars_dir
    app.state.scan_dir = scan_dir

    client = TestClient(app)
    return client, chars_dir, scan_dir


def test_cast_api_full_lifecycle(client_with_tmp_env):
    client, chars_dir, scan_dir = client_with_tmp_env

    # 1. Initial list characters
    res = client.get("/api/characters")
    assert res.status_code == 200
    assert res.json() == {"characters": []}

    # 2. Create character Zero.SOE
    create_payload = {
        "name": "Zero.SOE",
        "alias": "零度",
        "age": 16,
        "gender": "female",
        "tagline": "Virtual singer from the neon district",
    }
    res = client.post("/api/characters", json=create_payload)
    assert res.status_code == 200
    char_data = res.json()
    char_id = char_data["id"]
    assert char_id.startswith("char_")
    assert char_data["identity"]["name"] == "Zero.SOE"
    assert char_data["identity"]["age"] == 16
    assert char_data["identity"]["age_locked"] is True
    assert char_data["versioning"]["version"] == 1
    assert char_data["versioning"]["is_locked"] is False

    # 3. Get character details
    res = client.get(f"/api/characters/{char_id}")
    assert res.status_code == 200
    assert res.json()["id"] == char_id

    # 4. Upload reference portrait image
    dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    files = {"file": ("zero_reference.png", io.BytesIO(dummy_png), "image/png")}
    res = client.post(f"/api/characters/{char_id}/upload-reference", files=files)
    assert res.status_code == 200
    upload_res = res.json()
    assert upload_res["status"] == "ok"
    image_url = upload_res["image_url"]
    assert image_url.startswith(f"/api/characters/{char_id}/assets/")
    assert upload_res["character"]["assets"]["primary_image_url"] == image_url

    # 5. Serve uploaded asset
    res = client.get(image_url)
    assert res.status_code == 200
    assert res.content == dummy_png

    # 6. Confirm version baseline (lock v1)
    res = client.post(f"/api/characters/{char_id}/confirm-version")
    assert res.status_code == 200
    confirm_res = res.json()
    assert confirm_res["status"] == "ok"
    assert confirm_res["version"] == 1
    assert confirm_res["character"]["versioning"]["is_locked"] is True
    assert confirm_res["character"]["versioning"]["confirmed_at"] is not None

    # 7. Create a dummy song project in scan_dir and bind character
    song_folder = "cyberpunk_echoes"
    song_dir = scan_dir / song_folder
    song_dir.mkdir(parents=True)
    proj = AlignmentProject(
        title=song_folder,
        duration=30.0,
        lines=[AlignedLine(text="Hello cyber world", start=1.0, end=4.0)],
        sections=[MusicSection(name="Verse", start=0.0, end=10.0)],
    )
    alignment_file = song_dir / f"{song_folder}_alignment.json"
    proj.save_json(alignment_file)

    res = client.post(f"/api/characters/{char_id}/bind-song", json={"song_id": song_folder})
    assert res.status_code == 200
    bind_res = res.json()
    assert bind_res["status"] == "ok"
    assert song_folder in bind_res["bound_songs"]

    # Verify song's alignment file was updated with character_id & character_version
    saved_song = json.loads(alignment_file.read_text(encoding="utf-8"))
    assert saved_song["character_id"] == char_id
    assert saved_song["character_version"] == 1

    # 8. Unbind song
    res = client.post(f"/api/characters/{char_id}/unbind-song", json={"song_id": song_folder})
    assert res.status_code == 200
    unbind_res = res.json()
    assert song_folder not in unbind_res["bound_songs"]
    saved_song_after = json.loads(alignment_file.read_text(encoding="utf-8"))
    assert "character_id" not in saved_song_after

    # 9. Delete character
    res = client.delete(f"/api/characters/{char_id}")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    # 10. Verify 404 after deletion
    res = client.get(f"/api/characters/{char_id}")
    assert res.status_code == 404
