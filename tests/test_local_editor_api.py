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


def test_api_llm_prompt_and_merge(tmp_path):
    song_dir = tmp_path / "song_02"
    song_dir.mkdir(parents=True)
    json_path = song_dir / "song_02_alignment.json"

    proj = AlignmentProject(
        title="song_02",
        duration=10.0,
        lines=[
            AlignedLine(text="海浪拍打着礁石", start=1.0, end=4.0, section="Verse"),
            AlignedLine(text="群星在夜空中闪烁", start=5.0, end=8.0, section="Chorus"),
        ],
    )
    proj.save_json(json_path)

    app.state.scan_dir = tmp_path
    client = TestClient(app)

    # 1. 测试 /api/director/llm_prompt
    res_prompt = client.post(
        "/api/director/llm_prompt",
        json={"json_path": str(json_path)},
    )
    assert res_prompt.status_code == 200
    data_prompt = res_prompt.json()
    assert data_prompt["status"] == "ok"
    assert "海浪拍打着礁石" in data_prompt["prompt"]
    assert "群星在夜空中闪烁" in data_prompt["prompt"]
    assert Path(data_prompt["prompt_path"]).exists()

    # 2. 模拟大模型输出 JSON 并调用 /api/director/llm_merge
    mock_llm_response = [
        {
            "line_index": 0,
            "text": "海浪拍打着礁石",
            "video_prompt": "Cinematic wide shot of ocean waves crashing against dark rocks at dusk.",
            "design_rationale": "【导演构思】全景展示海浪拍击礁石，冷色调暗喻内心的孤寂与顽强抵抗。",
            "transition_rationale": "【镜头衔接】作为开篇建立镜头，向下一镜头的星空做慢速仰角升起衔接。",
            "storyboard_design": {
                "composition": "【全景】潮汐涌动，海浪撞击黑色礁石激起白色泡沫",
                "motion_effect": "慢速推镜头，水滴在空中凝固折射夕阳余晖",
            },
            "layout_design": {
                "primary_colour": "#A0D8EF",
                "secondary_colour": "#1C305C",
            },
        },
        {
            "line_index": 1,
            "text": "群星在夜空中闪烁",
            "video_prompt": "Extreme wide shot of starry night sky and Milky Way galaxy.",
            "design_rationale": "【导演构思】远景星河表达开阔与释然，暖金色文字破晓而出。",
            "transition_rationale": "【镜头衔接】承接上一镜头的仰起动势，以夜空完成视线向上延伸（Eyeline Match）。",
            "storyboard_design": {
                "composition": "【远景】银河横跨天际，繁星闪烁",
                "motion_effect": "仰视缓慢平移，星轨流动",
            },
            "layout_design": {
                "primary_colour": "#FFF3B0",
                "secondary_colour": "#332244",
            },
        },
    ]

    res_merge = client.post(
        "/api/director/llm_merge",
        json={
            "json_path": str(json_path),
            "response_data": mock_llm_response,
        },
    )
    assert res_merge.status_code == 200
    data_merge = res_merge.json()
    assert data_merge["status"] == "ok"
    assert data_merge["shots_count"] == 2
    shot0 = data_merge["project"]["storyboard"][0]
    assert "Cinematic wide shot" in shot0["prompt_en"]
    assert "【构图】" in shot0["prompt_zh"]
    assert "海浪拍击礁石" in shot0["design_rationale"]
    assert "慢速仰角升起" in shot0["transition_rationale"]

    # 验证生成的 clip prompt 文件与 storyboard 卡片
    clips_dir = song_dir / "clips"
    assert clips_dir.exists()
    clip_txt = (clips_dir / "clip_000_prompt.txt").read_text(encoding="utf-8")
    assert "【导演设计构思与理念 (Design Rationale)】" in clip_txt
    assert "海浪拍击礁石" in clip_txt
    assert "【镜头衔接与转场语言 (Transition / Montage)】" in clip_txt
    assert "慢速仰角升起" in clip_txt
    assert (song_dir / "storyboard" / "shot_001.png").exists()


def test_plugin_direct_import_endpoint(tmp_path, monkeypatch):
    """测试 Chrome 插件 / 外部扩展直传接口 /api/plugin/import"""
    app.state.scan_dir = tmp_path
    client = TestClient(app)

    # 模拟 process_one 避免真实 Demucs 模型推理消耗时间
    def mock_process_one(audio_file, lyrics_file, out_dir, stems_dir, config):
        out_dir.mkdir(parents=True, exist_ok=True)
        # 生成虚拟 alignment.json
        from src.storyboard_schema import AlignmentProject, AlignedLine
        proj = AlignmentProject(
            title="Plugin_Test_Song",
            duration=5.0,
            lines=[AlignedLine(text="万物并不需要理由", start=0.5, end=3.5)],
        )
        proj.save_json(out_dir / "Plugin_Test_Song_alignment.json")

    monkeypatch.setattr("src.main.process_one", mock_process_one)

    # 构建虚拟 MP3 二进制流
    dummy_audio = b"\xff\xfb\x90\x44" + b"\x00" * 2048

    files = {
        "audio_file": ("test_track.mp3", dummy_audio, "audio/mpeg"),
    }
    data = {
        "title": "Plugin_Test_Song",
        "lyrics": "万物并不需要理由\n它们只是在呈现自己",
        "prompt": "[Intro]\n[Verse 1]\n万物并不需要理由\n它们只是在呈现自己",
        "artist": "Luca",
        "song_id": "plugin-1234",
    }

    res = client.post("/api/plugin/import", files=files, data=data)
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["status"] == "ok"
    assert res_data["title"] == "Plugin_Test_Song"
    assert "Plugin_Test_Song" in res_data["editor_url"]

    # 验证 input 目录与 output 目录中的产物
    input_song_dir = tmp_path.parent / "input" / "Plugin_Test_Song"
    assert (input_song_dir / "Plugin_Test_Song.txt").exists()
    assert (input_song_dir / "Plugin_Test_Song_suno.json").exists()
    assert (tmp_path / "Plugin_Test_Song" / "Plugin_Test_Song_alignment.json").exists()


def test_get_gpu_status():
    """测试 /api/gpu/status 算力状态与配额诊断接口"""
    client = TestClient(app)
    res = client.get("/api/gpu/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "device_type" in data
    assert "zerogpu_config" in data
    assert data["zerogpu_config"]["duration"] == 35


def test_plugin_direct_export_video_rejects_unpublished():
    """测试当 Chrome 插件请求未公开 (is_public=False) 曲目时，后端坚决拒绝并提示 Publish"""
    client = TestClient(app)
    data = {
        "title": "Private_Song",
        "is_public": "false",
        "song_id": "priv-1234",
    }
    res = client.post("/api/plugin/export_video", data=data)
    assert res.status_code == 400
    assert "Publish" in res.json().get("detail", "") or "公开" in res.json().get("detail", "")


def test_get_asset_file_download_header(tmp_path):
    """测试 /api/asset_file 支持 download=true 产生 Content-Disposition 附件头"""
    app.state.scan_dir = tmp_path
    client = TestClient(app)

    test_file = tmp_path / "sample_video.mp4"
    test_file.write_bytes(b"dummy mp4 data")

    # 1. 默认流式 (无附件头)
    res_stream = client.get(f"/api/asset_file?path={test_file}")
    assert res_stream.status_code == 200
    assert "content-disposition" not in res_stream.headers

    # 2. 携带 download=true
    res_dl = client.get(f"/api/asset_file?path={test_file}&download=true&filename=my_mv.mp4")
    assert res_dl.status_code == 200
    assert "attachment" in res_dl.headers.get("content-disposition", "")
    assert "my_mv.mp4" in res_dl.headers.get("content-disposition", "")




