"""
测试 tools/upload_youtube.py 命令行发布工具
涵盖规格探测、Shorts 规则保护拦截、伴随文件读取、元数据生成与发布调度
"""
from unittest.mock import MagicMock, patch

from tools.upload_youtube import (
    find_companion_files,
    parse_song_from_filename,
    probe_video,
)


def test_parse_song_from_filename():
    """验证从各种常见格式文件名提取歌名、风格与艺人"""
    p1 = parse_song_from_filename("Everglow-Full song-16_9-apple.mp4")
    assert p1["title"] == "Everglow"
    assert "Made with fovea.si" in p1["artist"]

    p2 = parse_song_from_filename("Coldplay - Everglow-Custom clip-9_16-apple-karaoke.mp4")
    assert p2["title"] == "Everglow"
    assert p2["artist"] == "Coldplay"
    assert "卡拉OK" in p2["style"] or "高潮" in p2["style"]


def test_find_companion_files(tmp_path):
    """验证自动读取同名 .json 与封面图"""
    v = tmp_path / "song.mp4"
    v.write_text("fake video")

    meta = tmp_path / "song.json"
    meta.write_text('{"title": "Custom Song", "artist": "Singer", "tags": ["tag1"]}')

    cover = tmp_path / "song.jpg"
    cover.write_text("fake cover")

    res = find_companion_files(v)
    assert res["meta"]["title"] == "Custom Song"
    assert res["meta"]["artist"] == "Singer"
    assert res["cover"] == str(cover.resolve())


@patch("subprocess.run")
def test_probe_video_portrait_shorts(mock_run, tmp_path):
    """验证通过 ffprobe 探测 9:16 竖屏短视频"""
    v = tmp_path / "shorts.mp4"
    v.write_text("video")

    mock_run.return_value = MagicMock(
        stdout='{"streams":[{"width": 1080, "height": 1920, "duration": "45.0"}], "format":{"duration": "45.0"}}'
    )
    res = probe_video(v)
    assert res["aspect"] == "9:16"
    assert res["is_shorts"] is True
    assert res["duration"] == 45.0


@patch("subprocess.run")
def test_probe_video_landscape(mock_run, tmp_path):
    """验证通过 ffprobe 探测 16:9 横屏长视频"""
    v = tmp_path / "full.mp4"
    v.write_text("video")

    mock_run.return_value = MagicMock(
        stdout='{"streams":[{"width": 1920, "height": 1080, "duration": "240.0"}], "format":{"duration": "240.0"}}'
    )
    res = probe_video(v)
    assert res["aspect"] == "16:9"
    assert res["is_shorts"] is False
    assert res["duration"] == 240.0


@patch("src.youtube_uploader.youtube_uploader.publish_video")
@patch("tools.upload_youtube.probe_video")
def test_cli_dry_run_execution(mock_probe, mock_publish, tmp_path):
    """验证 CLI 在 dry-run 模式下的执行"""
    v = tmp_path / "Everglow-Full song-16_9-apple.mp4"
    v.write_text("video data")

    mock_probe.return_value = {
        "width": 1920,
        "height": 1080,
        "duration": 280.0,
        "aspect": "16:9",
        "is_shorts": False,
        "size_mb": 150.0,
    }
    mock_publish.return_value = {
        "success": True,
        "dry_run": True,
        "video_id": "dry_run_id",
        "url": "https://youtu.be/dry_run_id",
    }

    import sys
    test_args = ["upload_youtube.py", str(v), "--dry-run"]
    with patch.object(sys, "argv", test_args):
        from tools.upload_youtube import main
        main()

    mock_publish.assert_called_once()
    kwargs = mock_publish.call_args.kwargs
    assert kwargs["dry_run"] is True
    assert kwargs["privacy_status"] == "unlisted"
