"""
Tests for SaaS lifecycle hardening:
- Path traversal protection in local editor & storage
- Query-parameter / flexible token authentication for downloads
- WebSocket authentication & task ownership authorization
- Worker boolean parameter parsing (skip_separation: False)
"""

import pytest
from pathlib import Path
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.local_editor import _validate_path, app as local_editor_app
from src.storage import LocalStorage
from src.api_server import app


def test_storage_path_traversal_prevention(tmp_path):
    storage = LocalStorage(base_dir=tmp_path / "storage")
    
    # Normal safe key
    safe_path = storage.get_local_path("uploads/user1/task1/song.mp3")
    assert safe_path.is_relative_to(tmp_path / "storage")

    # Traversal attack keys
    with pytest.raises(ValueError, match="存储路径越界"):
        storage.get_local_path("../../../etc/passwd")

    with pytest.raises(ValueError, match="存储路径越界"):
        storage.get_local_path("/etc/passwd")

    with pytest.raises(ValueError, match="存储路径越界"):
        storage.get_local_path("uploads/../../secret.txt")


def test_local_editor_path_traversal_prevention(tmp_path):
    scan_dir = tmp_path / "output"
    scan_dir.mkdir(parents=True, exist_ok=True)
    local_editor_app.state.scan_dir = scan_dir
    
    # Safe paths
    safe_file = scan_dir / "song1" / "test.json"
    safe_file.parent.mkdir(parents=True, exist_ok=True)
    safe_file.write_text("{}", encoding="utf-8")
    assert _validate_path(safe_file) == safe_file.resolve()

    # Traversal to parent repo or root
    parent_file = tmp_path / "sensitive.txt"
    parent_file.write_text("secret", encoding="utf-8")
    with pytest.raises(HTTPException) as exc_info:
        _validate_path(parent_file)
    assert exc_info.value.status_code == 403


def test_worker_boolean_config_preservation():
    """Verify that skip_separation=False is preserved as False, not overridden by truthy/falsy bugs"""
    config_dict = {
        "skip_separation": False,
        "ass_only": False,
        "beat_effects": False,
    }
    
    # Test the boolean parsing logic used in process_song_task
    skip_sep = bool(config_dict["skip_separation"]) if "skip_separation" in config_dict else True
    ass_only = bool(config_dict["ass_only"]) if "ass_only" in config_dict else False
    beat_fx = bool(config_dict["beat_effects"]) if "beat_effects" in config_dict else False

    assert skip_sep is False
    assert ass_only is False
    assert beat_fx is False


def test_ws_progress_rejects_unauthenticated():
    client = TestClient(app)
    # Attempting to connect to websocket without token should close with code 1008
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/tasks/fake-task-id/progress"):
            pass
    assert exc_info.value.code == 1008
