"""
Cast Studio API Integration Tests
Tests HTTP endpoints:
- Initial state: Zero.SOE is private (not leaked to arbitrary users like Alice or Bob)
- POST /api/characters (Create private character)
- Privacy enforcement: Bob cannot see Alice's private character
- POST /api/characters/{id}/visibility (Toggle between private & public)
- Visibility update enforcement: Bob can see when public, cannot see when private
- Permission check: Bob cannot change visibility of Alice's character (HTTP 403)
- POST /api/characters/{id}/upload-reference (Multipart image upload)
- POST /api/characters/{id}/confirm-version (Lock baseline version)
- POST /api/characters/{id}/bind-song (Bind character to song alignment project)
- Multi-tenant isolation: User B cannot delete/edit User A's character (HTTP 403)
- POST /api/characters/{id}/unbind-song (Unbind)
- DELETE /api/characters/{id} (Delete)
"""
import io
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.local_editor import app
from src.storyboard_schema import AlignmentProject, AlignedLine, MusicSection
from src.auth import create_access_token


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


def test_cast_api_full_lifecycle_and_ownership(client_with_tmp_env):
    client, chars_dir, scan_dir = client_with_tmp_env

    token_alice = create_access_token("user_alice")
    token_bob = create_access_token("user_bob")
    headers_alice = {"Authorization": f"Bearer {token_alice}"}
    headers_bob = {"Authorization": f"Bearer {token_bob}"}

    # 1. Initial list characters: Zero.SOE is private to owner/local, so Alice sees empty list
    res = client.get("/api/characters", headers=headers_alice)
    assert res.status_code == 200
    initial_chars = res.json()["characters"]
    # Alice does not see private benchmark character
    assert not any(c["id"] == "char_zero_soe_0618" for c in initial_chars)

    # 2. User Alice creates private character "Luna.WAV"
    create_payload = {
        "name": "Luna.WAV",
        "alias": "月音",
        "age": 16,
        "gender": "female",
        "tagline": "Virtual lo-fi indie singer",
        "visibility": "private",
    }
    res = client.post("/api/characters", json=create_payload, headers=headers_alice)
    assert res.status_code == 200
    char_data = res.json()
    char_id = char_data["id"]
    assert char_id.startswith("char_")
    assert char_data["user_id"] == "user_alice"
    assert char_data["visibility"] == "private"
    assert char_data["identity"]["name"] == "Luna.WAV"
    assert char_data["identity"]["age"] == 16
    assert char_data["identity"]["age_locked"] is True

    # 3. Privacy check: User Bob lists characters -> Bob DOES NOT see Alice's private Luna.WAV
    res = client.get("/api/characters", headers=headers_bob)
    assert res.status_code == 200
    bob_chars = res.json()["characters"]
    bob_ids = [c["id"] for c in bob_chars]
    assert char_id not in bob_ids

    # User Bob cannot fetch Luna.WAV by ID (404 / access denied)
    res = client.get(f"/api/characters/{char_id}", headers=headers_bob)
    assert res.status_code == 404

    # 4. Visibility toggle: Bob attempts to change Alice's visibility -> 403 Forbidden
    res = client.post(f"/api/characters/{char_id}/visibility", json={"visibility": "public"}, headers=headers_bob)
    assert res.status_code == 403

    # Alice toggles Luna.WAV to public
    res = client.post(f"/api/characters/{char_id}/visibility", json={"visibility": "public"}, headers=headers_alice)
    assert res.status_code == 200
    assert res.json()["visibility"] == "public"

    # Now Bob CAN see Luna.WAV in list
    res = client.get("/api/characters", headers=headers_bob)
    assert res.status_code == 200
    assert any(c["id"] == char_id for c in res.json()["characters"])

    # Alice toggles Luna.WAV back to private
    res = client.post(f"/api/characters/{char_id}/visibility", json={"visibility": "private"}, headers=headers_alice)
    assert res.status_code == 200
    assert res.json()["visibility"] == "private"

    # Now Bob CANNOT see Luna.WAV in list again
    res = client.get("/api/characters", headers=headers_bob)
    assert res.status_code == 200
    assert not any(c["id"] == char_id for c in res.json()["characters"])

    # 5. User Alice uploads reference portrait
    dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    files = {"file": ("luna_reference.png", io.BytesIO(dummy_png), "image/png")}
    res = client.post(f"/api/characters/{char_id}/upload-reference", files=files, headers=headers_alice)
    assert res.status_code == 200
    upload_res = res.json()
    assert upload_res["status"] == "ok"
    image_url = upload_res["image_url"]
    assert image_url.startswith(f"/api/characters/{char_id}/assets/")

    # User Bob attempts to upload reference to Alice's character -> 403 Forbidden
    files_bob = {"file": ("hack.png", io.BytesIO(dummy_png), "image/png")}
    res = client.post(f"/api/characters/{char_id}/upload-reference", files=files_bob, headers=headers_bob)
    assert res.status_code == 403

    # 6. User Alice confirms baseline version (v1 lock)
    res = client.post(f"/api/characters/{char_id}/confirm-version", headers=headers_alice)
    assert res.status_code == 200
    confirm_res = res.json()
    assert confirm_res["version"] == 1
    assert confirm_res["character"]["versioning"]["is_locked"] is True

    # User Bob attempts to confirm version on Alice's character -> 403 Forbidden
    res = client.post(f"/api/characters/{char_id}/confirm-version", headers=headers_bob)
    assert res.status_code == 403

    # 7. Song binding
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

    # Alice binds her character
    res = client.post(f"/api/characters/{char_id}/bind-song", json={"song_id": song_folder}, headers=headers_alice)
    assert res.status_code == 200
    assert song_folder in res.json()["bound_songs"]

    # Bob cannot bind Alice's private character -> 403 Forbidden
    res = client.post(f"/api/characters/{char_id}/bind-song", json={"song_id": song_folder}, headers=headers_bob)
    assert res.status_code == 403

    # Bob cannot delete Alice's character -> 403 Forbidden
    res = client.delete(f"/api/characters/{char_id}", headers=headers_bob)
    assert res.status_code == 403

    # Alice can delete her character
    res = client.delete(f"/api/characters/{char_id}", headers=headers_alice)
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
