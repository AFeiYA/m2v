from pathlib import Path
import time
import pytest
from fastapi.testclient import TestClient

from src.lyric_engine import get_lyric_video_options, export_lyric_video
from src.local_editor import app


def test_lyric_video_options():
    options = get_lyric_video_options()
    assert "aspect_ratios" in options
    assert "templates" in options
    assert "themes" in options
    assert "background_modes" in options
    ratio_ids = [r["id"] for r in options["aspect_ratios"]]
    assert "9:16" in ratio_ids
    assert "16:9" in ratio_ids


@pytest.mark.local_only
def test_export_lyric_video_fast(tmp_path):
    json_p = Path("output/BianHaoB-612DeGaoBie/BianHaoB-612DeGaoBie_alignment.json")
    audio_p = Path("input/BianHaoB-612DeGaoBie/BianHaoB-612DeGaoBie.mp3")
    if not json_p.exists() or not audio_p.exists():
        pytest.skip("测试音频或工程文件不存在，跳过合成测试")

    out_mp4 = tmp_path / "unit_test_lyric.mp4"
    try:
        res = export_lyric_video(
            alignment_source=json_p,
            audio_path=audio_p,
            output_path=out_mp4,
            aspect_ratio="9:16",
            template="apple",
            theme="apple_white",
            background_mode="blurred_ambient",
            duration_limit=2.0,
        )
        assert res["status"] == "ok"
        assert Path(res["video_path"]).exists()
        assert Path(res["ass_path"]).exists()
    finally:
        if out_mp4.exists():
            out_mp4.unlink(missing_ok=True)
        ass_p = out_mp4.with_suffix(".ass")
        if ass_p.exists():
            ass_p.unlink(missing_ok=True)


def test_api_lyric_video_templates():
    with TestClient(app) as client:
        res = client.get("/api/lyric_video/templates")
        assert res.status_code == 200
        assert len(res.json()["aspect_ratios"]) >= 2


@pytest.mark.local_only
def test_api_lyric_video_endpoints(monkeypatch):
    monkeypatch.setattr(app.state, "scan_dir", Path("output").resolve(), raising=False)
    client = TestClient(app)
    # 1. 模板查询
    res = client.get("/api/lyric_video/templates")
    assert res.status_code == 200
    data = res.json()
    assert len(data["aspect_ratios"]) >= 2

    # 2. 导出任务提交
    json_p = "output/BianHaoB-612DeGaoBie/BianHaoB-612DeGaoBie_alignment.json"
    if not Path(json_p).exists():
        pytest.skip("测试工程文件不存在，跳过 API 导出测试")

    export_res = client.post("/api/lyric_video/export", json={
        "json_path": json_p,
        "aspect_ratio": "9:16",
        "template": "center_bounce",
        "theme": "amber_gold",
        "background_mode": "blurred_ambient",
        "duration_limit": 1.0,
    })
    assert export_res.status_code == 200
    task_id = export_res.json()["task_id"]

    # 3. 轮询状态
    completed = False
    for _ in range(25):
        time.sleep(0.4)
        s_res = client.get(f"/api/lyric_video/task_status?task_id={task_id}")
        assert s_res.status_code == 200
        state = s_res.json()
        if state["status"] == "completed":
            completed = True
            assert "video_url" in state["result"]
            break
        elif state["status"] == "failed":
            pytest.fail(f"任务执行失败: {state.get('error')}")

    assert completed is True
