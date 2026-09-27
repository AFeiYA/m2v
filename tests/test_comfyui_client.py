"""
ComfyUIClient 单元测试
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from src.storyboard_schema import ShotPlan, Take
from src.video_providers.comfyui_client import ComfyUIClient


@pytest.fixture
def mock_client(tmp_path):
    comfy_dir = tmp_path / "ComfyUI"
    comfy_dir.mkdir()
    models_dir = comfy_dir / "models"
    models_dir.mkdir()
    (models_dir / "checkpoints").mkdir()
    (models_dir / "checkpoints" / "ltx-video-2b-v0.9.1.safetensors").write_text("dummy")

    client = ComfyUIClient(
        base_url="http://127.0.0.1:8188",
        comfy_dir=str(comfy_dir),
        python_bin="python3",
    )
    return client


def test_build_workflow_payload_ltx(mock_client):
    payload = mock_client.build_workflow_payload(
        model_type="ltx_video",
        positive_prompt="A beautiful river under golden hour light",
        negative_prompt="text, watermark",
        width=768,
        height=512,
        length=25,
        steps=20,
        cfg=3.0,
        seed=12345,
        frame_rate=16,
    )
    assert "1" in payload
    assert payload["1"]["class_type"] == "CheckpointLoaderSimple"
    assert payload["2"]["inputs"]["text"] == "A beautiful river under golden hour light"
    assert payload["3"]["inputs"]["text"] == "text, watermark"
    assert payload["4"]["inputs"]["width"] == 768
    assert payload["4"]["inputs"]["length"] == 25
    assert payload["5"]["inputs"]["seed"] == 12345
    assert payload["5"]["inputs"]["steps"] == 20
    assert payload["7"]["inputs"]["frame_rate"] == 16


def test_build_workflow_payload_flux(mock_client):
    payload = mock_client.build_workflow_payload(
        model_type="flux_schnell",
        positive_prompt="Close up portrait of an elder artisan",
        negative_prompt="deformed",
        width=1280,
        height=720,
        steps=4,
        cfg=1.0,
        seed=999,
    )
    assert payload["1"]["class_type"] == "UnetLoaderGGUF"
    assert payload["4"]["inputs"]["text"] == "Close up portrait of an elder artisan"
    assert payload["6"]["inputs"]["width"] == 1280
    assert payload["7"]["inputs"]["steps"] == 4
    assert payload["9"]["class_type"] == "SaveImage"


def test_extract_output_media_video(mock_client, tmp_path):
    output_dir = mock_client.comfy_dir / "output"
    output_dir.mkdir(parents=True)
    video_file = output_dir / "test_00001.mp4"
    video_file.write_text("fake video bytes")

    outputs = {
        "7": {
            "gifs": [
                {
                    "filename": "test_00001.mp4",
                    "subfolder": "",
                    "type": "output",
                    "format": "video/h264-mp4",
                }
            ]
        }
    }

    target_dir = tmp_path / "clips"
    media_type, dest_path = mock_client.extract_output_media(
        outputs, target_dir=target_dir, file_stem="shot_001_take_001"
    )

    assert media_type == "video"
    assert Path(dest_path).exists()
    assert Path(dest_path).name == "shot_001_take_001.mp4"
