"""
Local Editor ComfyUI 专用路由单元测试
"""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from src.local_editor import app
from src.storyboard_schema import AlignmentProject, ShotPlan, Take


@pytest.fixture
def client(tmp_path):
    app.state.scan_dir = tmp_path
    return TestClient(app)


@pytest.fixture
def dummy_project_json(tmp_path):
    project_file = tmp_path / "test_alignment.json"
    project = AlignmentProject(
        audio_file="test.mp3",
        song_name="测试歌曲",
        storyboard=[
            ShotPlan(
                shot_id=1,
                id="shot_001",
                start=0.0,
                end=3.5,
                prompt_en="A cinematic mountain scene",
                takes=[
                    Take(
                        id="take_001",
                        shot_id="shot_001",
                        provider="comfyui_ltx",
                        media_type="video",
                        media_path="output/test/clips/shot_001_take_001.mp4",
                        selected=True,
                    ),
                    Take(
                        id="take_002",
                        shot_id="shot_001",
                        provider="comfyui_wan",
                        media_type="video",
                        media_path="output/test/clips/shot_001_take_002.mp4",
                        selected=False,
                    ),
                ],
                selected_take_id="take_001",
            )
        ],
    )
    project.save_json(project_file)
    return str(project_file)


def test_comfyui_status(client):
    res = client.get("/api/comfyui/status")
    assert res.status_code == 200
    data = res.json()
    assert "health" in data
    assert "models" in data
    assert data["default_model"] == "ltx_video"


def test_comfyui_select_take(client, dummy_project_json):
    # 切换到 take_002
    req_body = {
        "json_path": dummy_project_json,
        "shot_id": "shot_001",
        "take_id": "take_002",
    }
    res = client.post("/api/comfyui/select_take", json=req_body)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["selected_take_id"] == "take_002"

    # 验证文件已更新
    updated = AlignmentProject.load_json(dummy_project_json)
    shot = updated.storyboard[0]
    assert shot.selected_take_id == "take_002"
    assert shot.takes[0].selected is False
    assert shot.takes[1].selected is True
    assert shot.path == "output/test/clips/shot_001_take_002.mp4"


def test_comfyui_delete_take(client, dummy_project_json):
    req_body = {
        "json_path": dummy_project_json,
        "shot_id": "shot_001",
        "take_id": "take_001",
    }
    res = client.request("DELETE", "/api/comfyui/delete_take", json=req_body)
    assert res.status_code == 200

    updated = AlignmentProject.load_json(dummy_project_json)
    shot = updated.storyboard[0]
    assert len(shot.takes) == 1
    assert shot.takes[0].id == "take_002"


def test_comfyui_two_stage_endpoints_structure(client, dummy_project_json, monkeypatch):
    from unittest.mock import MagicMock
    from src.video_providers import comfyui_client

    mock_client = MagicMock()
    mock_client.generate_keyframe_for_shot.return_value = "output/test/keyframes/shot_001_kf.png"
    mock_client.generate_i2v_take_for_shot.return_value = Take(
        id="take_003",
        shot_id="shot_001",
        provider="comfyui_ltx_i2v",
        media_type="video",
        media_path="output/test/clips/shot_001_take_003.mp4",
        selected=True,
    )
    mock_client.generate_two_stage_take.return_value = (
        "output/test/keyframes/shot_001_kf.png",
        Take(
            id="take_004",
            shot_id="shot_001",
            provider="comfyui_ltx_i2v",
            media_type="video",
            media_path="output/test/clips/shot_001_take_004.mp4",
            selected=True,
        ),
    )
    import src.local_editor
    monkeypatch.setattr(src.local_editor, "get_comfyui_client", lambda: mock_client)

    # 1. Test generate_keyframe endpoint
    res = client.post(
        "/api/comfyui/generate_keyframe",
        json={"json_path": dummy_project_json, "shot_id": "shot_001", "resolution": "768x448", "steps": 4},
    )
    assert res.status_code == 200
    assert "task_id" in res.json()

    # 2. Test generate_i2v_take endpoint
    res = client.post(
        "/api/comfyui/generate_i2v_take",
        json={"json_path": dummy_project_json, "shot_id": "shot_001", "resolution": "768x448", "steps": 15},
    )
    assert res.status_code == 200
    assert "task_id" in res.json()

    # 3. Test generate_two_stage endpoint
    res = client.post(
        "/api/comfyui/generate_two_stage",
        json={"json_path": dummy_project_json, "shot_id": "shot_001", "resolution": "768x448"},
    )
    assert res.status_code == 200
    assert "task_id" in res.json()

