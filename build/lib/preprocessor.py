"""
Module 1: 歌词预处理器
- TXT / LRC 解析
- 数字 → 中文文字 (cn2an)
- 繁体 → 简体 (OpenCC)
- 去除不可发音符号
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import chardet

from src.config import PreprocessorConfig
from src.utils import log

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class LyricLine:
    """一行歌词，可选带 LRC 时间戳"""
    text: str
    timestamp: float | None = None   # 秒，来自 LRC 行级时间戳
    paragraph: int = 0               # 段落索引 (0-based)，由空行分隔


# ---------------------------------------------------------------------------
# LRC 时间戳正则:  [mm:ss.xx] 或 [mm:ss.xxx]
# ---------------------------------------------------------------------------
_LRC_TAG_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{2,3}))?\]")
# 匹配元数据标签: [ti:xxx] [ar:xxx] 等
_LRC_META_RE = re.compile(r"^\[(?:ti|ar|al|by|offset|re|ve):", re.IGNORECASE)
# 不可发音符号（保留中文、字母、数字、基本标点、空格）
_UNPRINTABLE_RE = re.compile(r"[^\u4e00-\u9fff\u3400-\u4dbf\w\s，。、！？；：""''…—\-,\.!?;:'\"]")


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def preprocess_lyrics(
    lyrics_path: Path,
    config: PreprocessorConfig | None = None,
) -> list[LyricLine]:
    """
    读取歌词文件，返回清洗后的 LyricLine 列表。
    支持 .txt 和 .lrc 格式。
    """
    if config is None:
        config = PreprocessorConfig()

    raw_text = _read_file_auto_encoding(lyrics_path)
    log.info("读取歌词: %s (%d 字符)", lyrics_path.name, len(raw_text))

    # 判断格式
    is_lrc = lyrics_path.suffix.lower() == ".lrc" or _LRC_TAG_RE.search(raw_text) is not None
    if is_lrc:
        lines = _parse_lrc(raw_text)
    else:
        lines = _parse_txt(raw_text)

    # 清洗
    cleaned: list[LyricLine] = []
    for line in lines:
        text = line.text.strip()
        if not text:
            continue

        # 数字转中文
        if config.convert_numbers:
            text = _convert_numbers(text)

        # 繁体转简体
        if config.convert_traditional:
            text = _convert_traditional(text, config.opencc_config)

        # 去除不可发音符号
        text = _clean_symbols(text)

        text = text.strip()
        if text:
            cleaned.append(LyricLine(text=text, timestamp=line.timestamp, paragraph=line.paragraph))

    log.info("预处理完成: %d 行有效歌词", len(cleaned))
    return cleaned


# ---------------------------------------------------------------------------
# 文件读取 (自动编码检测)
# ---------------------------------------------------------------------------

def _read_file_auto_encoding(path: Path) -> str:
    """自动检测编码并读取文件内容"""
    raw_bytes = path.read_bytes()
    detected = chardet.detect(raw_bytes)
    encoding = detected.get("encoding", "utf-8") or "utf-8"
    log.debug("编码检测: %s (confidence=%.2f)", encoding, detected.get("confidence", 0))
    return raw_bytes.decode(encoding, errors="replace")


# ---------------------------------------------------------------------------
# LRC 格式解析
# ---------------------------------------------------------------------------

def _parse_lrc(text: str) -> list[LyricLine]:
    """解析 LRC 歌词，提取时间戳和文本"""
    lines: list[LyricLine] = []
    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        # 跳过元数据标签
        if _LRC_META_RE.match(raw_line):
            continue

        # 提取所有时间标签（一行可能有多个: [00:12.34][00:45.67]歌词）
        timestamps: list[float] = []
        for m in _LRC_TAG_RE.finditer(raw_line):
            minutes = int(m.group(1))
            seconds = int(m.group(2))
            centiseconds_str = m.group(3) or "0"
            # 兼容 2 位和 3 位小数
            if len(centiseconds_str) == 2:
                frac = int(centiseconds_str) / 100.0
            else:
                frac = int(centiseconds_str) / 1000.0
            timestamps.append(minutes * 60 + seconds + frac)

        # 去掉所有时间标签，保留纯文本
        lyric_text = _LRC_TAG_RE.sub("", raw_line).strip()
        if not lyric_text:
            continue

        # 每个时间戳生成一行
        if timestamps:
            for ts in timestamps:
                lines.append(LyricLine(text=lyric_text, timestamp=ts))
        else:
            lines.append(LyricLine(text=lyric_text, timestamp=None))

    # 按时间戳排序
    lines.sort(key=lambda l: l.timestamp if l.timestamp is not None else float("inf"))
    return lines


def _parse_txt(text: str) -> list[LyricLine]:
    """解析纯文本歌词，每行一句，空行分段落"""
    lines: list[LyricLine] = []
    paragraph = 0
    prev_was_blank = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if lines:  # 仅在已有内容后才计为段落分隔
                prev_was_blank = True
            continue
        if prev_was_blank:
            paragraph += 1
            prev_was_blank = False
        lines.append(LyricLine(text=stripped, paragraph=paragraph))
    return lines


# ---------------------------------------------------------------------------
# 数字转中文文字
# ---------------------------------------------------------------------------

def _convert_numbers(text: str) -> str:
    """将文本中的阿拉伯数字转为中文"""
    try:
        import cn2an
        # 使用 transform 模式：句子中的数字自动转换
        return cn2an.transform(text, "an2cn")
    except ImportError:
        log.warning("cn2an 未安装，跳过数字转换")
        return text
    except Exception:
        # cn2an 对某些混合文本可能报错，回退原文
        return text


# ---------------------------------------------------------------------------
# 繁体 → 简体
# ---------------------------------------------------------------------------

def _convert_traditional(text: str, opencc_config: str = "t2s") -> str:
    """使用 OpenCC 将繁体中文转为简体"""
    try:
        from opencc import OpenCC
        converter = OpenCC(opencc_config)
        return converter.convert(text)
    except ImportError:
        log.warning("OpenCC 未安装，跳过繁简转换")
        return text


# ---------------------------------------------------------------------------
# 符号清理
# ---------------------------------------------------------------------------

def _clean_symbols(text: str) -> str:
    """去除不可发音的特殊符号，保留文字和基本标点"""
    return _UNPRINTABLE_RE.sub("", text)
