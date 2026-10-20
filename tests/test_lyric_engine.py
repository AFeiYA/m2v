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


def test_motion_palette_matches_ass_and_background(tmp_path):
    import json
    from src.subtitle import COLOR_PALETTES
    from src.lyric_engine import _ass_color_to_hex, build_lyric_video_ffmpeg_cmd
    palettes = json.loads(Path('frontend/motion/src/theme-palettes.json').read_text())
    for key, palette in palettes.items():
        assert _ass_color_to_hex(COLOR_PALETTES[key]['primary']).lower() == palette['accentDark']
        assert _ass_color_to_hex(COLOR_PALETTES[key]['secondary']).lower() == palette['mutedDark']
    cmd = build_lyric_video_ffmpeg_cmd(tmp_path/'audio.wav',tmp_path/'lyrics.ass',tmp_path/'video.mp4',tmp_path/'cover.png',1280,720,'solid_black',background_color=palettes['impact']['backgroundDark'])
    assert any('color=c=#0d120a:s=1280x720' in arg for arg in cmd)


def test_landscape_karaoke_fits_one_line_per_slot_without_changing_source(tmp_path):
    from src.storyboard_schema import AlignmentResult, AlignedLine, WordTimestamp
    from src.subtitle import generate_ass
    from src.config import SubtitleConfig
    words = [WordTimestamp(word='horizon',start=i*.2,end=(i+1)*.2) for i in range(24)]
    alignment = AlignmentResult(lines=[AlignedLine(text=' '.join(w.word for w in words),start=0,end=4.8,words=words)])
    before = alignment.model_dump()
    out = generate_ass(alignment,tmp_path/'fit.ass',config=SubtitleConfig(render_mode='tv',theme='neon',font_size=72,play_res_x=1920,play_res_y=1080))
    text=out.read_text()
    events=[line for line in text.splitlines() if line.startswith('Dialogue:')]
    assert events
    assert all(r'\N' not in event and r'\q2' in event for event in events)
    import re
    assert all(int(size)<72 for size in re.findall(r'\\fs(\d+)', '\n'.join(events)))
    assert alignment.model_dump() == before


def test_tv_karaoke_uniform_font_size_and_stay_sung_continuity(tmp_path):
    from src.storyboard_schema import AlignmentResult, AlignedLine, WordTimestamp
    from src.subtitle import generate_ass
    from src.config import SubtitleConfig
    import re
    # 短句与超长句交替
    line0 = AlignedLine(text="Short intro", start=1.0, end=2.5, words=[WordTimestamp(word="Short", start=1.0, end=1.8), WordTimestamp(word="intro", start=1.9, end=2.5)])
    line1 = AlignedLine(text="A much longer line that needs to scale down the font size to fit landscape row", start=3.0, end=7.0, words=[WordTimestamp(word="A", start=3.0, end=3.5), WordTimestamp(word="much", start=3.6, end=7.0)])
    line2 = AlignedLine(text="Next upper slot", start=7.5, end=9.0, words=[WordTimestamp(word="Next", start=7.5, end=8.0), WordTimestamp(word="slot", start=8.1, end=9.0)])
    alignment = AlignmentResult(lines=[line0, line1, line2])
    out = generate_ass(alignment, tmp_path / "ktv.ass", config=SubtitleConfig(render_mode="tv", theme="neon", font_size=72, play_res_x=1920, play_res_y=1080))
    text = out.read_text()
    events = [l for l in text.splitlines() if l.startswith("Dialogue:")]
    # 提取所有字号
    fs_sizes = set(re.findall(r'\\fs(\d+)', '\n'.join(events)))
    # 全局字号严格统一为单一数值
    assert len(fs_sizes) == 1
    # 存在驻留事件（第0句唱完后在第1句唱期间保持驻留）
    assert any("Dialogue: 0,0:00:02.50,0:00:03.00" in e for e in events)
