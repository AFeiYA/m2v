import pytest

from src.meta_uploader import MetaReelsUploader, format_meta_caption
from src.tiktok_uploader import TikTokUploader, format_tiktok_caption
from tools.publish_all import (
    ALL_PLATFORMS,
    DOMESTIC_PLATFORMS,
    OVERSEAS_PLATFORMS,
    publish_to_platforms,
    resolve_platforms,
)


def test_format_tiktok_caption_basic_and_tags():
    caption = format_tiktok_caption(
        title="Jingle Bells 1857",
        desc="Classic version",
        tags=["christmas", "#music"],
    )
    assert "Jingle Bells 1857" in caption
    assert "Classic version" in caption
    assert "#christmas" in caption
    assert "#music" in caption


def test_format_tiktok_caption_length_cap():
    long_desc = "x" * 3000
    caption = format_tiktok_caption(title="Title", desc=long_desc, tags=["a"])
    assert len(caption) <= 2200


def test_format_meta_caption_basic_and_tags():
    caption = format_meta_caption(
        title="Jingle Bells 1857",
        desc="Reels version",
        tags=["reels", "#holiday"],
    )
    assert "Jingle Bells 1857" in caption
    assert "Reels version" in caption
    assert "#reels" in caption
    assert "#holiday" in caption


def test_format_meta_caption_length_cap():
    long_desc = "y" * 3000
    caption = format_meta_caption(title="Title", desc=long_desc, tags=["b"])
    assert len(caption) <= 2200


def test_tiktok_uploader_status_and_dry_run(tmp_path):
    profile_dir = tmp_path / "tt_profile"
    cookies_path = tmp_path / "tt_cookies.json"
    uploader = TikTokUploader(profile_dir=profile_dir, cookies_path=cookies_path)

    status = uploader.get_account_status()
    assert isinstance(status, dict)
    assert "is_logged_in" in status

    with pytest.raises(FileNotFoundError):
        uploader.publish_video(tmp_path / "missing.mp4", title="Missing", dry_run=True)

    video = tmp_path / "sample.mp4"
    video.write_bytes(b"fake-mp4")
    res = uploader.publish_video(video, title="Test TikTok", tags=["demo"], dry_run=True)
    assert res["success"] is True
    assert res["dry_run"] is True
    assert res["platform"] == "tiktok"


def test_meta_uploader_status_and_dry_run(tmp_path):
    profile_dir = tmp_path / "meta_profile"
    cookies_path = tmp_path / "meta_cookies.json"
    uploader = MetaReelsUploader(profile_dir=profile_dir, cookies_path=cookies_path)

    status = uploader.get_account_status()
    assert isinstance(status, dict)
    assert "is_logged_in" in status

    with pytest.raises(FileNotFoundError):
        uploader.publish_video(tmp_path / "missing.mp4", title="Missing", dry_run=True)

    video = tmp_path / "sample.mp4"
    video.write_bytes(b"fake-mp4")
    res = uploader.publish_video(
        video,
        title="Test Meta",
        tags=["demo"],
        targets=["instagram", "facebook"],
        dry_run=True,
    )
    assert res["success"] is True
    assert res["dry_run"] is True
    assert res["platform"] == "meta"
    assert res["targets"] == ["instagram", "facebook"]


def test_resolve_platforms_aliases_and_errors():
    assert resolve_platforms("all") == list(ALL_PLATFORMS)
    assert resolve_platforms("overseas") == list(OVERSEAS_PLATFORMS)
    assert resolve_platforms("domestic") == list(DOMESTIC_PLATFORMS)
    assert resolve_platforms("ig,fb,xhs") == ["meta", "xiaohongshu"]
    assert resolve_platforms("instagram,facebook") == ["meta"]

    with pytest.raises(ValueError):
        resolve_platforms("unknown_platform")


def test_publish_to_platforms_dry_run_routing(tmp_path):
    en_video = tmp_path / "en.mp4"
    zh_video = tmp_path / "zh.mp4"
    en_video.write_bytes(b"en")
    zh_video.write_bytes(b"zh")

    results = publish_to_platforms(
        platforms=["youtube", "tiktok", "meta", "douyin"],
        en_video=en_video,
        zh_video=zh_video,
        title="中文标题",
        en_title="English Title",
        desc="中文描述",
        en_desc="English Desc",
        tags=["中文"],
        en_tags=["english"],
        dry_run=True,
    )
    assert len(results) == 4
    by_platform = {r["platform"]: r for r in results}
    assert by_platform["youtube"]["success"] is True
    assert by_platform["youtube"]["dry_run"] is True
    assert by_platform["tiktok"]["dry_run"] is True
    assert by_platform["meta"]["dry_run"] is True
    assert by_platform["douyin"]["dry_run"] is True
    assert by_platform["tiktok"]["title"] == "English Title"
    assert by_platform["meta"]["title"] == "English Title"
    assert by_platform["douyin"]["title"] == "中文标题"
    assert "en.mp4" in by_platform["tiktok"]["message"]
    assert "zh.mp4" in by_platform["douyin"]["message"]
