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
from PIL import Image
import pytest
from fastapi.testclient import TestClient

from src.local_editor import app
from src.storyboard_schema import AlignmentProject, AlignedLine, MusicSection
from src.auth import create_access_token


@pytest.fixture
def client_with_tmp_env(tmp_path, monkeypatch):
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from src.database import Base
    import src.database as database

    url = f"sqlite+aiosqlite:///{tmp_path}/test_cast.db"
    test_engine = create_async_engine(url, poolclass=NullPool, connect_args={"check_same_thread": False})
    test_sessions = async_sessionmaker(test_engine, expire_on_commit=False)

    async def init_tables():
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init_tables())

    monkeypatch.setattr(database, "async_session", test_sessions)

    chars_dir = tmp_path / "characters"
    chars_dir.mkdir(parents=True)
    scan_dir = tmp_path / "songs"
    scan_dir.mkdir(parents=True)

    app.state.characters_dir = chars_dir
    app.state.scan_dir = scan_dir
    app.state.is_local_mode = False  # Default to cloud mode for strict security tests

    client = TestClient(app)
    return client, chars_dir, scan_dir


def test_cast_api_full_lifecycle_and_ownership(client_with_tmp_env):
    client, chars_dir, scan_dir = client_with_tmp_env

    token_alice = create_access_token("user_alice")
    token_bob = create_access_token("user_bob")
    headers_alice = {"Authorization": f"Bearer {token_alice}"}
    headers_bob = {"Authorization": f"Bearer {token_bob}"}

    # 0. P0 Cloud Auth: Unauthenticated and invalid token returns 401 in cloud mode
    res = client.get("/api/characters")
    assert res.status_code == 401
    assert "Authentication credentials required" in res.json()["detail"]

    res = client.get("/api/characters", headers={"Authorization": "Bearer bad.token.value"})
    assert res.status_code == 401

    # In explicit local mode, unauthenticated succeeds with default_local
    app.state.is_local_mode = True
    res = client.get("/api/characters")
    assert res.status_code == 200
    app.state.is_local_mode = False  # Switch back to cloud mode

    # 1. Initial list characters: Zero.SOE is private to owner/local, so Alice sees empty list
    res = client.get("/api/characters", headers=headers_alice)
    assert res.status_code == 200
    initial_chars = res.json()["characters"]
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

    # 3. Privacy check: User Bob lists characters -> Bob DOES NOT see Alice's private Luna.WAV
    res = client.get("/api/characters", headers=headers_bob)
    assert res.status_code == 200
    bob_chars = res.json()["characters"]
    bob_ids = [c["id"] for c in bob_chars]
    assert char_id not in bob_ids

    # User Bob cannot fetch Luna.WAV by ID (404 / access denied)
    res = client.get(f"/api/characters/{char_id}", headers=headers_bob)
    assert res.status_code == 404

    # 4. Editable character: Alice modifies age and profile via PUT
    res = client.put(
        f"/api/characters/{char_id}",
        json={"identity": {"age": 18, "name": "Luna.WAV Super"}},
        headers=headers_alice,
    )
    assert res.status_code == 200
    updated_profile = res.json()
    assert updated_profile["identity"]["age"] == 18
    assert updated_profile["identity"]["name"] == "Luna.WAV Super"

    # Bob cannot modify Alice's character -> 403 Forbidden
    res = client.put(
        f"/api/characters/{char_id}",
        json={"identity": {"age": 22}},
        headers=headers_bob,
    )
    assert res.status_code == 403

    # 5. User Alice uploads valid reference portrait (Pillow validated)
    png_buf = io.BytesIO()
    Image.new("RGB", (64, 64), color="blue").save(png_buf, format="PNG")
    valid_png_bytes = png_buf.getvalue()

    files = {"file": ("luna_reference.png", io.BytesIO(valid_png_bytes), "image/png")}
    res = client.post(f"/api/characters/{char_id}/upload-reference", files=files, headers=headers_alice)
    assert res.status_code == 200
    upload_res = res.json()
    assert upload_res["status"] == "ok"
    image_url = upload_res["image_url"]
    assert image_url.startswith(f"/api/characters/{char_id}/assets/")

    # P0 Private Image Authorization:
    # Alice can view her own private portrait
    filename = Path(image_url).name
    res = client.get(f"/api/characters/{char_id}/assets/{filename}", headers=headers_alice)
    assert res.status_code == 200

    # Bob CANNOT view Alice's private portrait -> 403 Forbidden
    res = client.get(f"/api/characters/{char_id}/assets/{filename}", headers=headers_bob)
    assert res.status_code == 403

    # Unauthenticated caller CANNOT view private portrait -> 403 Forbidden
    res = client.get(f"/api/characters/{char_id}/assets/{filename}")
    assert res.status_code == 403

    # 6. Visibility toggle: Bob attempts to change Alice's visibility -> 403 Forbidden
    res = client.post(f"/api/characters/{char_id}/visibility", json={"visibility": "public"}, headers=headers_bob)
    assert res.status_code == 403

    # Alice toggles Luna.WAV to public
    res = client.post(f"/api/characters/{char_id}/visibility", json={"visibility": "public"}, headers=headers_alice)
    assert res.status_code == 200
    assert res.json()["visibility"] == "public"

    # Now Bob CAN see Luna.WAV in list and view the public portrait!
    res = client.get("/api/characters", headers=headers_bob)
    assert res.status_code == 200
    assert any(c["id"] == char_id for c in res.json()["characters"])

    res = client.get(f"/api/characters/{char_id}/assets/{filename}", headers=headers_bob)
    assert res.status_code == 200

    # 7. Song binding
    # Binding non-existent song returns 404 Not Found
    res = client.post(f"/api/characters/{char_id}/bind-song", json={"song_id": "non_existent"}, headers=headers_alice)
    assert res.status_code == 404

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

    # Check alignment json has character_id and no version field
    align_data = json.loads(alignment_file.read_text(encoding="utf-8"))
    assert align_data["character_id"] == char_id
    assert "character_version" not in align_data

    # Bob cannot bind Alice's character if made private -> test permission
    # Alice toggles back to private
    client.post(f"/api/characters/{char_id}/visibility", json={"visibility": "private"}, headers=headers_alice)
    res = client.post(f"/api/characters/{char_id}/bind-song", json={"song_id": song_folder}, headers=headers_bob)
    assert res.status_code == 403

    # Bob cannot delete Alice's character -> 403 Forbidden
    res = client.delete(f"/api/characters/{char_id}", headers=headers_bob)
    assert res.status_code == 403

    # Alice can delete her character, which cascades and unbinds from song
    res = client.delete(f"/api/characters/{char_id}", headers=headers_alice)
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    # Song alignment json should have character_id cleared
    cleared_align = json.loads(alignment_file.read_text(encoding="utf-8"))
    assert "character_id" not in cleared_align
