import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.config import CompositorConfig, PipelineConfig
from src.main import parse_args, process_one
from src.local_editor import RegenRequest, LyricVideoExportRequest


def test_config_defaults_and_instrumental_flag():
    # 默认值
    compositor_cfg = CompositorConfig()
    assert compositor_cfg.audio_track == "mix"

    pipeline_cfg = PipelineConfig()
    assert pipeline_cfg.use_instrumental is False
    assert pipeline_cfg.compositor.audio_track == "mix"


def test_config_from_toml_with_instrumental(tmp_path: Path):
    toml_file = tmp_path / "pipeline.toml"
    toml_file.write_text(
        """
[pipeline]
skip_separation = true
use_instrumental = true

[compositor]
audio_track = "instrumental"
""",
        encoding="utf-8",
    )
    cfg = PipelineConfig.from_file(toml_file)
    assert cfg.use_instrumental is True
    assert cfg.compositor.audio_track == "instrumental"


def test_parse_args_instrumental_flags():
    with patch("sys.argv", ["m2v", "-i", "input/song.mp3", "--instrumental"]):
        args = parse_args()
        assert args.instrumental is True
        assert args.audio_track is None

    with patch("sys.argv", ["m2v", "-i", "input/song.mp3", "--audio-track", "instrumental"]):
        args = parse_args()
        assert args.audio_track == "instrumental"


def test_video_only_karaoke_composite(tmp_path: Path):
    mp3 = tmp_path / "my_song.mp3"
    mp3.write_bytes(b"FAKE_AUDIO")
    inst = tmp_path / "my_song_instrumental.wav"
    inst.write_bytes(b"FAKE_INST")
    ass = tmp_path / "my_song.ass"
    ass.write_text("[Script Info]\nTitle: Test\n", encoding="utf-8")
    out_dir = tmp_path / "output"
    out_dir.mkdir()

    cfg = PipelineConfig()
    cfg.video_only = True
    cfg.use_instrumental = True
    cfg.ass_file = ass

    with patch("src.compositor.compose_video") as mock_compose:
        out_file = process_one(
            mp3_path=mp3,
            lyrics_path=None,
            output_dir=out_dir,
            background=None,
            config=cfg,
        )
        assert out_file == out_dir / "my_song_karaoke.mp4"
        mock_compose.assert_called_once()
        _, kwargs = mock_compose.call_args
        # 应该使用伴奏音频而非原音频
        assert kwargs["audio_path"] == inst
        assert kwargs["output_path"] == out_dir / "my_song_karaoke.mp4"


def test_local_editor_requests_schema():
    regen = RegenRequest(
        json_path="output/test_alignment.json",
        mode="video",
        audio_track="instrumental",
    )
    assert regen.audio_track == "instrumental"

    export_req = LyricVideoExportRequest(
        json_path="output/test_alignment.json",
        audio_track="instrumental",
    )
    assert export_req.audio_track == "instrumental"


def test_lyric_engine_export_instrumental(tmp_path: Path):
    from src.lyric_engine import export_lyric_video
    from src.storyboard_schema import AlignmentResult

    mp3 = tmp_path / "demo.mp3"
    mp3.write_bytes(b"DEMO_AUDIO")
    inst = tmp_path / "demo_instrumental.mp3"
    inst.write_bytes(b"DEMO_INST")
    out_mp4 = tmp_path / "demo_karaoke.mp4"

    alignment = AlignmentResult(lines=[])

    def mock_build_cmd(**kwargs):
        # 创建有效大小输出文件以模拟 FFmpeg 成功生成
        out_mp4.write_bytes(b"0" * 15000)
        return ["ffmpeg", "-version"]

    mock_run_res = MagicMock()
    mock_run_res.returncode = 0

    with patch("src.lyric_engine.check_ffmpeg", return_value=True), \
         patch("src.lyric_engine.generate_ass"), \
         patch("src.lyric_engine.build_lyric_video_ffmpeg_cmd", side_effect=mock_build_cmd) as mock_cmd, \
         patch("subprocess.run", return_value=mock_run_res):

        res = export_lyric_video(
            alignment_source=alignment,
            audio_path=mp3,
            output_path=out_mp4,
            audio_track="instrumental",
        )
        assert res["status"] == "ok"
        assert res["audio_track"] == "instrumental"
        mock_cmd.assert_called_once()
        called_audio = mock_cmd.call_args.kwargs.get("audio_path")
        # 确认传递给视频合成命令的 audio_path 为伴奏音频
        assert called_audio == inst


def test_motion_api_render_request_schema():
    from src.motion_api import RenderRequest

    req = RenderRequest(
        project_id="test_proj",
        audio_track="instrumental",
    )
    assert req.audio_track == "instrumental"
