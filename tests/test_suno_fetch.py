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


def test_auto_process_suno_pipeline_config_and_flow(tmp_path):
    """验证 auto_process_suno 中 PipelineConfig 的导入与 pipeline 执行参数传递"""
    from src.suno_fetch import auto_process_suno

    fake_song = SunoSong(
        id="test-uuid",
        title="测试歌曲",
        artist="Suno AI",
        audio_url="https://cdn.example.com/test.mp3",
        lyrics="歌词第一行",
        raw_prompt="测试歌词 [Verse]\n歌词第一行",
        tags="pop",
        duration=120.0,
    )

    with patch("src.suno_fetch.fetch_song", return_value=fake_song), \
         patch("src.suno_fetch.resolve_or_find_audio", return_value=tmp_path / "test.mp3"), \
         patch("src.suno_fetch.is_valid_audio_file", return_value=True), \
         patch("src.main.process_one") as mock_process_one:

        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"dummy audio")

        config_file = tmp_path / "pipeline.toml"
        config_file.write_text('[aligner]\nlanguage = "zh"\n')
        cb_calls = []
        def _cb(prog, msg):
            cb_calls.append((prog, msg))

        result = auto_process_suno(
            url="https://suno.com/song/test-uuid",
            input_dir=tmp_path / "input",
            output_dir=tmp_path / "output",
            launch_editor=False,
            progress_callback=_cb,
            skip_separation=True,
            use_gpu=True,
            language="auto",
            config_file=config_file,
        )

        assert result["status"] == "ok"
        assert result["title"] == "测试歌曲"
        assert mock_process_one.called
        # 验证传递的 config 对象
        passed_config = mock_process_one.call_args[0][4]
        assert passed_config.skip_separation is True
        assert passed_config.separator.device == "cuda"
        assert passed_config.ass_only is True
        assert passed_config.aligner.language == "auto"
        # 验证进度回调包含极速模式字样
        assert any("极速模式" in msg for _, msg in cb_calls)


def test_suno_import_request_schema():
    from src.local_editor import SunoImportRequest
    req = SunoImportRequest(url="https://suno.com/song/123", skip_separation=True, use_gpu=False)
    assert req.skip_separation is True
    assert req.use_gpu is False


def test_fetch_song_raises_for_unpublished():
    """验证当 Suno 曲目未公开 (is_public: false) 时，强制抛出 SongNotPublishedError"""
    from src.suno_fetch import SongNotPublishedError

    fake_html = """
    <html>
      <link rel="canonical" href="https://suno.com/song/33333333-4444-5555-6666-777777777777" />
      <script>
        self.__next_f.push([1,"{\\"clip\\":{\\"id\\":\\"33333333-4444-5555-6666-777777777777\\",\\"title\\":\\"私密未发布歌曲\\",\\"is_public\\":false,\\"metadata\\":{\\"prompt\\":\\"测试歌词\\",\\"duration\\":100.0}}}"]);
      </script>
    </html>
    """
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.text = fake_html
        mock_resp.url = "https://suno.com/song/33333333-4444-5555-6666-777777777777"
        mock_get.return_value = mock_resp

        with pytest.raises(SongNotPublishedError) as exc_info:
            fetch_song("33333333-4444-5555-6666-777777777777", require_public=True)

        assert "尚未公开" in str(exc_info.value) or "Publish" in str(exc_info.value)





def test_clean_lyrics_removes_full_width_arrangement_and_keeps_sung_english():
    from src.suno_fetch import _clean_lyrics
    raw = "（Fast Kick + 电流噪声渐入）\nYo，Check it out\n左手在右手的左边\n（Bass Drop 前停顿）\n那里正在跳动\nLet’s go!（Drop）\n（Funky Bass + Groove Beat）"
    assert _clean_lyrics(raw).splitlines() == ["Yo，Check it out", "左手在右手的左边", "那里正在跳动", "Let’s go!"]
    assert _clean_lyrics("(Bass Drop)\n[Verse]\nHello world (Drop)\n[Vocal grit] 你好") == "Hello world\n你好"


def test_clean_lyrics_preserves_invisible_stanza_separators():
    from src.suno_fetch import _clean_lyrics
    raw = "\u2060\nPhone buzzing twice\n\u2060\u2060\nYeah, a circus\n\u200b\nYeah, a circus\n\ufeff"
    assert _clean_lyrics(raw) == "Phone buzzing twice\n\nYeah, a circus\n\nYeah, a circus"


def test_suno_section_headers_survive_cleaning_as_stanza_boundaries(tmp_path):
    from src.suno_fetch import _clean_lyrics, download_song, SunoSong
    from src.preprocessor import preprocess_lyrics
    raw = "[Intro]\u2060\n(Disco bass)\n\u2060[Verse 1]\u2060\nPhone buzzing twice\nSecond line\n\u2060[Chorus]\u2060\nA whole circus\n\u2060[Chorus]\u2060\nA whole circus\n[Outro]"
    clean = _clean_lyrics(raw)
    assert clean == "Phone buzzing twice\nSecond line\n\nA whole circus\n\nA whole circus"
    song = SunoSong(id="test", title="test", artist="artist", audio_url="", lyrics=clean, raw_prompt=raw, tags="", duration=0)
    # Keep this regression offline but use the real metadata-to-TXT writer.
    from unittest.mock import patch
    with patch("src.suno_fetch.is_valid_audio_file", return_value=True):
        (tmp_path / "test.mp3").write_bytes(b"existing audio")
        _, lyrics_path, _, _ = download_song(song, tmp_path, song_name="test")
    lines = preprocess_lyrics(lyrics_path)
    assert [line.paragraph for line in lines] == [0, 0, 1, 2]
    assert [line.occurrence for line in lines] == [0, 0, 0, 1]
