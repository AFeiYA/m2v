"""工具函数 — 文件发现 / 格式转换 / 日志 / 时间格式化"""

import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

def setup_logger(name: str = "m2v", level: int = logging.INFO) -> logging.Logger:
    """创建统一格式的 logger"""
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

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
    扫描歌曲目录，查找歌曲专属子目录下的音频与歌词文件对。
    规范结构: input/{song_name}/{song_name}.(mp3|wav|m4a|flac) 与 {song_name}.(lrc|txt)
    如果传入的 input_dir 本身就是单首歌曲的专属目录，直接匹配该目录中的文件。
    歌词文件优先级: 同名 .lrc > 同名 .txt
    返回: [(audio_path, lyrics_path), ...]
    """
    pairs: list[tuple[Path, Path]] = []
    audio_exts = [".mp3", ".wav", ".m4a", ".flac"]

    subdirs = [d for d in input_dir.iterdir() if d.is_dir()]
    candidate_dirs = sorted(subdirs) if subdirs else [input_dir]

    for sdir in candidate_dirs:
        stem = sdir.name
        audio_file = None
        for ext in audio_exts:
            cand = sdir / f"{stem}{ext}"
            if cand.exists():
                audio_file = cand
                break
        if not audio_file:
            continue

        lrc = sdir / f"{stem}.lrc"
        txt = sdir / f"{stem}.txt"
        if lrc.exists():
            pairs.append((audio_file, lrc))
        elif txt.exists():
            pairs.append((audio_file, txt))
        else:
            log.warning("跳过歌曲目录 %s — 未找到同名 .lrc 或 .txt 歌词文件", sdir.name)

    log.info("发现 %d 对 (音频 + 歌词) 歌曲目录", len(pairs))
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
