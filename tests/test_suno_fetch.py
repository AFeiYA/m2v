"""
测试 Suno 音频获取与智能回退优先 MP3 机制
"""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.utils import is_valid_audio_file
from src.suno_fetch import fetch_song, resolve_or_find_audio, download_song, SunoSong


def test_is_valid_audio_file_nonexistent(tmp_path):
    assert is_valid_audio_file(tmp_path / "nonexistent.mp3") is False


def test_is_valid_audio_file_empty(tmp_path):
    empty_file = tmp_path / "empty.mp3"
    empty_file.write_bytes(b"")
    assert is_valid_audio_file(empty_file) is False


def test_is_valid_audio_file_corrupt(tmp_path):
    corrupt_file = tmp_path / "corrupt.m4a"
    corrupt_file.write_bytes(b"random gibberish data" * 100)
    # ffprobe will fail on this
    assert is_valid_audio_file(corrupt_file) is False


def test_fetch_song_skips_m4a_opus_and_picks_mp3():
    fake_html = """
    <html>
      <link rel="canonical" href="https://suno.com/song/11111111-2222-3333-4444-555555555555" />
      <script>
        self.__next_f.push([1,"{\\"clip\\":{\\"id\\":\\"11111111-2222-3333-4444-555555555555\\",\\"title\\":\\"测试歌曲\\",\\"audio_url\\":\\"https://studio-api.prod.suno.com/api/forbidden\\",\\"media_urls\\":[{\\"url\\":\\"https://cdn.example.com/bad.m4a\\",\\"content_type\\":\\"m4a-opus\\",\\"encoding\\":\\"1.0.0\\"},{\\"url\\":\\"https://cdn.example.com/good.mp3\\",\\"content_type\\":\\"audio/mp3\\"}],\\"metadata\\":{\\"prompt\\":\\"测试歌词\\",\\"duration\\":120.0}}}"]);
      </script>
    </html>
    """
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.text = fake_html
        mock_resp.url = "https://suno.com/song/11111111-2222-3333-4444-555555555555"
        mock_get.return_value = mock_resp

        song = fetch_song("11111111-2222-3333-4444-555555555555")
        assert song.title == "测试歌曲"
        # 必须跳过 m4a-opus，选中 good.mp3
        assert song.audio_url == "https://cdn.example.com/good.mp3"


def test_resolve_or_find_audio_cleans_corrupt_m4a_and_imports_mp3(tmp_path):
    input_dir = tmp_path / "input"
    downloads_dir = tmp_path / "Downloads"
    input_dir.mkdir(parents=True)
    downloads_dir.mkdir(parents=True)

    # 1. input 目录下有一个损坏的 m4a (如未闭合的流)
    bad_m4a = input_dir / "好听的歌.m4a"
    bad_m4a.write_bytes(b"corrupt header without moov atom")

    # 2. Downloads 目录下有用户在网页点击下载的标准 mp3
    valid_mp3 = downloads_dir / "好听的歌.mp3"
    valid_mp3.write_bytes(b"ID3" + b"\x00" * 2000)

    with patch("pathlib.Path.home", return_value=tmp_path):
        with patch("src.suno_fetch.is_valid_audio_file") as mock_val:
            def side_effect(path):
                # 模拟 bad_m4a 损坏，valid_mp3 有效
                return Path(path).name.endswith(".mp3")
            mock_val.side_effect = side_effect

            res = resolve_or_find_audio("好听的歌", "song-uuid-123", input_dir)
            assert res is not None
            assert res.name == "好听的歌.mp3"
            assert res.exists()
            # 损坏的 m4a 应该已被清理
            assert not bad_m4a.exists()


def test_resolve_or_find_audio_fuzzy_match_mp3(tmp_path):
    input_dir = tmp_path / "input"
    downloads_dir = tmp_path / "Downloads"
    input_dir.mkdir(parents=True)
    downloads_dir.mkdir(parents=True)

    # 用户下载的文件名可能包含序号或后缀，例如 "Suno_好听的歌_final.mp3"
    dl_mp3 = downloads_dir / "Suno_好听的歌_final.mp3"
    dl_mp3.write_bytes(b"ID3" + b"\x00" * 2000)

    with patch("pathlib.Path.home", return_value=tmp_path):
        with patch("src.suno_fetch.is_valid_audio_file", return_value=True):
            res = resolve_or_find_audio("好听的歌", "song-uuid-123", input_dir)
            assert res is not None
            assert res.name == "好听的歌.mp3"
            assert res.exists()
