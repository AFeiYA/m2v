"""工具函数 — 文件发现 / 格式转换 / 日志 / 时间格式化"""

import logging
import os
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
    audio_exts = [".mp3", ".wav", ".flac", ".m4a"]

    subdirs = [d for d in input_dir.iterdir() if d.is_dir()]
    candidate_dirs = sorted(subdirs) if subdirs else [input_dir]

    for sdir in candidate_dirs:
        stem = sdir.name
        audio_file = None
        for ext in audio_exts:
            cand = sdir / f"{stem}{ext}"
            if cand.exists() and is_valid_audio_file(cand):
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
# FFmpeg & 音频可用性检查
# ---------------------------------------------------------------------------

# 优先将完备且未损坏的 ffmpeg-full 置于 PATH 最前列，确保 Demucs 及子进程均使用此版本
for _p in ["/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin"]:
    if Path(_p).is_dir() and _p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{_p}:{os.environ.get('PATH', '')}"


def get_ffmpeg_binary() -> str:
    """获取可用的 ffmpeg 可执行文件路径 (优先匹配具备 libass 的 ffmpeg-full)"""
    import shutil
    candidates = [
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
    ]
    for c in candidates:
        if Path(c).is_file():
            return c
    found = shutil.which("ffmpeg")
    return found or "ffmpeg"



def get_ffprobe_binary() -> str:
    """获取可用的 ffprobe 可执行文件路径"""
    import shutil
    candidates = [
        "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe",
        "/usr/local/opt/ffmpeg-full/bin/ffprobe",
    ]
    for c in candidates:
        if Path(c).is_file():
            return c
    found = shutil.which("ffprobe")
    return found or "ffprobe"


def check_ffmpeg() -> bool:
    """检查 ffmpeg 是否可用"""
    import shutil
    bin_path = get_ffmpeg_binary()
    if Path(bin_path).is_file():
        return True
    return shutil.which(bin_path) is not None


def is_valid_audio_file(path: Path | str) -> bool:
    """
    检查音频文件是否存在且可被正确解码（具备有效音轨与时长）。
    能精准拦截下载中断、缺少 moov atom 或受 Suno 防盗链混淆的破损音频。
    """
    p = Path(path)
    if not p.is_file() or p.stat().st_size < 1024:
        return False

    import subprocess
    cmd = [
        get_ffprobe_binary(), "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(p)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            return False
        dur_str = res.stdout.strip()
        if not dur_str:
            return False
        return float(dur_str) > 0.0
    except (subprocess.SubprocessError, ValueError, OSError):
        return p.stat().st_size > 100_000
