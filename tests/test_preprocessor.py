"""歌词预处理器 单元测试"""

from src.preprocessor import (
    preprocess_lyrics,
    _parse_lrc,
    _parse_txt,
    _clean_symbols,
    LyricLine,
)
from src.config import PreprocessorConfig
from pathlib import Path
import tempfile
import pytest


# ---------------------------------------------------------------------------
# 辅助: 写临时文件
# ---------------------------------------------------------------------------

def _write_temp(content: str, suffix: str = ".txt") -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return Path(f.name)


# ---------------------------------------------------------------------------
# TXT 解析
# ---------------------------------------------------------------------------

class TestParseTxt:
    def test_basic(self):
        lines = _parse_txt("第一行\n第二行\n第三行")
        assert len(lines) == 3
        assert lines[0].text == "第一行"
        assert lines[0].timestamp is None

    def test_empty_lines(self):
        lines = _parse_txt("第一行\n\n第三行\n")
        assert len(lines) == 4  # 包含空行


# ---------------------------------------------------------------------------
# LRC 解析
# ---------------------------------------------------------------------------

class TestParseLrc:
    def test_basic_lrc(self):
        lrc = "[00:12.34]我站在风中\n[00:15.67]等你的出现"
        lines = _parse_lrc(lrc)
        assert len(lines) == 2
        assert lines[0].text == "我站在风中"
        assert abs(lines[0].timestamp - 12.34) < 0.01
        assert lines[1].text == "等你的出现"
        assert abs(lines[1].timestamp - 15.67) < 0.01

    def test_multi_timestamp(self):
        """一行多个时间标签"""
        lrc = "[00:12.34][01:05.00]重复的歌词"
        lines = _parse_lrc(lrc)
        assert len(lines) == 2
        assert lines[0].text == "重复的歌词"
        assert lines[1].text == "重复的歌词"

    def test_metadata_skipped(self):
        """元数据标签应被跳过"""
        lrc = "[ti:歌曲名]\n[ar:歌手]\n[00:05.00]第一句歌词"
        lines = _parse_lrc(lrc)
        assert len(lines) == 1
        assert lines[0].text == "第一句歌词"

    def test_3digit_centiseconds(self):
        """兼容 3 位毫秒格式"""
        lrc = "[00:12.345]测试"
        lines = _parse_lrc(lrc)
        assert abs(lines[0].timestamp - 12.345) < 0.001


# ---------------------------------------------------------------------------
# 符号清理
# ---------------------------------------------------------------------------

class TestCleanSymbols:
    def test_keeps_chinese(self):
        assert _clean_symbols("我爱你") == "我爱你"

    def test_keeps_basic_punctuation(self):
        assert _clean_symbols("你好，世界！") == "你好，世界！"

    def test_removes_special(self):
        result = _clean_symbols("♪歌词♪")
        assert "♪" not in result
        assert "歌词" in result

    def test_keeps_letters_numbers(self):
        assert _clean_symbols("Hello123") == "Hello123"


# ---------------------------------------------------------------------------
# 完整预处理流程
# ---------------------------------------------------------------------------

class TestPreprocessLyrics:
    def test_txt_basic(self):
        path = _write_temp("第一行\n\n第二行\n")
        config = PreprocessorConfig(convert_numbers=False, convert_traditional=False)
        lines = preprocess_lyrics(path, config)
        assert len(lines) == 2
        assert lines[0].text == "第一行"

    def test_lrc_basic(self):
        path = _write_temp("[00:05.00]你好\n[00:10.00]世界", suffix=".lrc")
        config = PreprocessorConfig(convert_numbers=False, convert_traditional=False)
        lines = preprocess_lyrics(path, config)
        assert len(lines) == 2
        assert lines[0].text == "你好"
        assert lines[0].timestamp is not None
