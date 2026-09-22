"""
单元测试：本地编辑器 API 路由 (FastAPI)
测试 /api/director/auto_direct 和 /api/storyboard_frame 接口。
"""
import json
from pathlib import Path
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient
from src.local_editor import app
from src.storyboard_schema import AlignedLine, AlignmentProject, MusicSection


def test_api_auto_direct_and_storyboard_frame(tmp_path):
    # 构建虚拟工程结构
    song_dir = tmp_path / "song_01"
    song_dir.mkdir(parents=True)
    json_path = song_dir / "song_01_alignment.json"

    proj = AlignmentProject(
        title="song_01",
        duration=15.0,
        lines=[
            AlignedLine(text="微风吹过安静的海面", start=1.0, end=4.0, section="Verse"),
            AlignedLine(text="我们在破晓中前行", start=5.0, end=9.0, section="Chorus"),
        ],
        sections=[
            MusicSection(name="Intro", start=0.0, end=1.0),
            MusicSection(name="Verse", start=1.0, end=5.0),
            MusicSection(name="Chorus", start=5.0, end=15.0),
        ],
    )
    proj.save_json(json_path)

    # 设置 app 扫描目录
    app.state.scan_dir = tmp_path
    client = TestClient(app)

    # 测试 /api/director/auto_direct
    res = client.post(
        "/api/director/auto_direct",
        json={"json_path": str(json_path)},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["shots_count"] >= 3
    assert data["treatment"] is not None
    assert data["visual_bible"] is not None

    # 验证生成的图片文件
    sb_dir = song_dir / "storyboard"
    assert sb_dir.exists()
    assert (sb_dir / "shot_001.png").exists()

    # 测试 /api/storyboard_frame 获取图片流
    res_img = client.get(
        f"/api/storyboard_frame?json_path={json_path}&frame_name=shot_001.png"
    )
    assert res_img.status_code == 200
    assert res_img.headers["content-type"] == "image/png"
    assert len(res_img.content) > 1000
