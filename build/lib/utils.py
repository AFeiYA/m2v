"""工具函数 — 文件发现 / 格式转换 / 日志 / 时间格式化"""

import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

def setup_logger(name: str = "m2v", level: int = logging.INFO) -> logging.Logger:
    """创建统一格式的 logger"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(handler)
    return logger

log = setup_logger()

# ---------------------------------------------------------------------------
# 文件发现
# ---------------------------------------------------------------------------

def discover_pairs(input_dir: Path) -> list[tuple[Path, Path]]:
    """
    扫描 input_dir，找到所有 (mp3, lyrics) 配对。
    歌词文件优先级: 同名 .lrc > 同名 .txt
    返回: [(mp3_path, lyrics_path), ...]
    """
    pairs: list[tuple[Path, Path]] = []
    mp3_files = sorted(input_dir.glob("*.mp3"))

    for mp3 in mp3_files:
        stem = mp3.stem
        lrc = mp3.with_suffix(".lrc")
        txt = mp3.with_suffix(".txt")
        if lrc.exists():
            pairs.append((mp3, lrc))
        elif txt.exists():
            pairs.append((mp3, txt))
        else:
            log.warning("跳过 %s — 未找到同名 .lrc 或 .txt 歌词文件", mp3.name)

    log.info("发现 %d 对 (MP3 + 歌词) 文件", len(pairs))
    return pairs

# ---------------------------------------------------------------------------
# 时间格式化
# ---------------------------------------------------------------------------

def seconds_to_ass_time(seconds: float) -> str:
    """
    秒数 → ASS 时间格式  H:MM:SS.cc  (centiseconds)
    例: 65.32 → '0:01:05.32'
    """
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def seconds_to_centiseconds(seconds: float) -> int:
    """秒数 → 厘秒 (ASS \\k 标签单位)"""
    return max(1, round(seconds * 100))

# ---------------------------------------------------------------------------
# FFmpeg 可用性检查
# ---------------------------------------------------------------------------

def check_ffmpeg() -> bool:
    """检查 ffmpeg 是否在 PATH 中"""
    import shutil
    return shutil.which("ffmpeg") is not None
