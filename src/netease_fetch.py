"""
网易云音乐 (NetEase Cloud Music) 歌曲自动获取
支持从网易云歌曲链接、iframe 外链播放器代码、移动端分享文案或歌曲 ID 提取歌曲元数据、LRC 打点歌词与高清音频。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

import requests

from src.utils import is_valid_audio_file, log


@dataclass
class NetEaseSong:
    """网易云音乐歌曲完整信息"""
    id: str
    title: str
    artist: str
    album: str
    duration: float          # 时长 (秒)
    audio_url: str
    lyrics: str              # 清洗后的纯歌词 (已剔除作词/作曲等元信息行)
    raw_lrc: str             # 原始 LRC 带时间戳歌词
    cover_url: str = ""      # 封面大图地址
    is_vip: bool = False     # 是否为 VIP / 版权限制音频
    raw_data: dict = field(default_factory=dict)


def _sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def resolve_netease_song_id(input_str: str) -> str:
    """
    从输入内容中解析出网易云歌曲 ID。
    支持格式：
    1. 外链播放器 iframe 代码: <iframe ... src="//music.163.com/outchain/player?type=2&id=3364676325..."></iframe>
    2. 网页端链接: https://music.163.com/#/song?id=3364676325 或 https://music.163.com/song?id=3364676325
    3. 移动端/外链链接: https://y.music.163.com/m/song?id=3364676325 或 http://music.163.com/song/3364676325
    4. 分享短链: https://163cn.tv/xxx (自动跟随重定向)
    5. 纯数字 ID: 3364676325
    """
    s = (input_str or "").strip()
    if not s:
        raise ValueError("输入的内容不能为空")

    # 1. 尝试直接匹配纯数字 ID
    if s.isdigit():
        return s

    # 2. 如果是 163cn.tv 短链，先进行重定向探测
    if "163cn.tv" in s:
        try:
            url_match = re.search(r'https?://163cn\.tv/[a-zA-Z0-9]+', s)
            target_short = url_match.group(0) if url_match else s
            resp = requests.head(target_short, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True, timeout=10)
            s = resp.url
        except Exception as e:
            log.warning("解析 163cn.tv 短链重定向失败: %s", e)

    # 3. 正则提取 id= 参数或 /song/ 路径
    match = re.search(r'(?:[?&]id=|\/song(?:\/|\?id=))(\d+)', s)
    if match:
        return match.group(1)

    # 4. 如果是包含 iframe 的字符串，提取里面的 id
    iframe_match = re.search(r'id=(\d+)', s)
    if iframe_match:
        return iframe_match.group(1)

    # 5. 兜底：文本中是否有 5-12 位的独立数字
    digits = re.findall(r'\b(\d{5,12})\b', s)
    if digits:
        return digits[0]

    raise ValueError(f"未能从输入内容中解析出有效的网易云音乐歌曲 ID: {input_str[:80]}")


# 常见歌曲制作、词曲署名元信息正则 (非演唱歌词)
CREDIT_META_RE = re.compile(
    r"^(?:"
    r"(?:作词|作曲|编曲|制作人?|词曲|词|曲|演唱|原唱|翻唱|歌手|合唱|和声|和音|伴唱|伴奏|录音(?:室|师)?|混音(?:室|师)?|母带(?:工程|师)?|企划|监制|总监制|发行(?:人|公司)?|出品(?:人)?|统筹|文案|宣发|吉他|贝斯|鼓手?|打击乐|键盘|钢琴|弦乐|大提琴|小提琴|二胡|古筝|琵琶|笛子|OP|SP)"
    r"(?:\s*[/&、+]\s*(?:作词|作曲|编曲|制作人?|词曲|词|曲|演唱|原唱|歌手|录音|混音|母带))*?"
    r"\s*[:：/\-]\s*"
    r"|(?:Lyrics|Lyricist|Composer|Composed|Music|Written|Produced|Producer|Arranger|Arranged|Mixed|Mixer|Mastered|Recorded|Vocals?|Featuring|Feat\.?|Singer|Artist)"
    r"(?:\s*[/&]\s*(?:Lyrics|Composer|Music|Producer|Arranger))*?"
    r"\s*(?:by)?\s*[:：/\-]\s*"
    r")",
    re.IGNORECASE,
)


def fetch_netease_song(url_or_id: str) -> NetEaseSong:
    """
    从网易云 API 获取歌曲详情、LRC 歌词与音频直链。
    自动剔除作词、作曲、编曲、制作人等非歌词元信息打点行。
    """
    song_id = resolve_netease_song_id(url_or_id)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://music.163.com/",
    }

    # 1. 获取歌曲详情
    detail_url = f"https://music.163.com/api/song/detail/?id={song_id}&ids=[{song_id}]"
    try:
        resp = requests.get(detail_url, headers=headers, timeout=15)
        resp.raise_for_status()
        detail_data = resp.json()
    except Exception as e:
        raise ValueError(f"拉取网易云歌曲详情失败 (ID: {song_id}): {e}")

    songs = detail_data.get("songs", [])
    if not songs:
        raise ValueError(f"未找到网易云歌曲信息 (ID: {song_id})")

    song_info = songs[0]
    title = song_info.get("name") or f"netease_{song_id}"
    artists = [a.get("name", "") for a in song_info.get("artists", []) if a.get("name")]
    artist = ", ".join(artists) if artists else "网易云歌手"
    album = song_info.get("album", {}).get("name", "")
    duration_ms = song_info.get("duration", 0)
    duration = duration_ms / 1000.0 if duration_ms else 0.0
    cover_url = song_info.get("album", {}).get("picUrl", "")
    fee = song_info.get("fee", 0)
    is_vip = fee == 1 or fee == 4  # fee 1/4 通常为 VIP/付费独占

    # 2. 获取歌词
    lyric_url = f"https://music.163.com/api/song/lyric?os=pc&id={song_id}&lv=-1&kv=-1&tv=-1"
    raw_lrc_original = ""
    clean_lyrics = ""
    clean_lrc = ""
    try:
        lresp = requests.get(lyric_url, headers=headers, timeout=15)
        if lresp.status_code == 200:
            ldata = lresp.json()
            raw_lrc_original = ldata.get("lrc", {}).get("lyric", "")
    except Exception as e:
        log.warning("拉取歌词接口异常 (ID: %s): %s", song_id, e)

    if raw_lrc_original:
        # 清洗出纯歌词供文本处理，剔除 [00:00.00] 以及 [作词: ...] 等头部标签
        clean_lines = []
        clean_lrc_lines = []
        for line in raw_lrc_original.splitlines():
            line_str = re.sub(r'\[\d{1,2}:\d{2}(?:\.\d+)?\]', '', line).strip()
            # 过滤常见的作词、作曲、编曲、制作人元信息行
            if CREDIT_META_RE.match(line_str):
                log.info("跳过网易云元信息行 (非歌词): %s", line_str)
                continue
            if line_str:
                clean_lines.append(line_str)
                clean_lrc_lines.append(line)
        clean_lyrics = "\n".join(clean_lines)
        clean_lrc = "\n".join(clean_lrc_lines)

    # 3. 解析外链音频地址
    audio_url = f"https://music.163.com/song/media/outer/url?id={song_id}.mp3"

    song_info_copy = dict(song_info)
    song_info_copy["full_raw_lrc"] = raw_lrc_original

    return NetEaseSong(
        id=song_id,
        title=title,
        artist=artist,
        album=album,
        duration=duration,
        audio_url=audio_url,
        lyrics=clean_lyrics,
        raw_lrc=clean_lrc,
        cover_url=cover_url,
        is_vip=is_vip,
        raw_data=song_info_copy,
    )


def download_netease_song(
    song_or_url: NetEaseSong | str,
    output_dir: Path | str,
    song_name: Optional[str] = None,
    save_json: bool = True,
) -> tuple[Optional[Path], Path, Optional[Path], NetEaseSong]:
    """
    下载网易云歌曲音频与歌词到指定目录。
    返回: (audio_path, lyrics_path, json_path, song)
    """
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    song = fetch_netease_song(song_or_url) if isinstance(song_or_url, str) else song_or_url
    name = song_name or _sanitize_filename(song.title) or f"netease_{song.id}"

    # 1. 保存歌词: 优先保存完整的打点 .lrc，同时保存纯文本 .txt
    lrc_path = output_dir / f"{name}.lrc"
    txt_path = output_dir / f"{name}.txt"

    if song.raw_lrc:
        lrc_path.write_text(song.raw_lrc, encoding="utf-8")
        log.info("已保存网易云打点歌词: %s", lrc_path)
    if song.lyrics:
        txt_path.write_text(song.lyrics, encoding="utf-8")
        log.info("已保存清洗歌词: %s", txt_path)

    lyrics_path = lrc_path if song.raw_lrc else txt_path

    # 2. 保存元数据 JSON
    json_path = None
    if save_json:
        json_path = output_dir / f"{name}_netease.json"
        meta = {
            "id": song.id,
            "title": song.title,
            "artist": song.artist,
            "album": song.album,
            "duration": song.duration,
            "cover_url": song.cover_url,
            "is_vip": song.is_vip,
            "source": "netease",
            "raw_song": song.raw_data,
        }
        json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("已保存元数据 JSON: %s", json_path)

    # 3. 下载音频
    audio_path = output_dir / f"{name}.mp3"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://music.163.com/",
    }

    try:
        log.info("正在从网易云外链下载音频: %s", song.audio_url)
        with requests.get(song.audio_url, headers=headers, stream=True, timeout=25, allow_redirects=True) as r:
            if r.status_code == 200:
                # 检查重定向地址是否到了 404 页面
                if "/404" in r.url or "music.163.com/404" in r.url:
                    log.warning("网易云外链重定向至 404 (可能受版权保护或为 VIP 音频)")
                else:
                    with open(audio_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
            else:
                log.warning("网易云音频下载响应状态码异常: %d", r.status_code)
    except Exception as e:
        log.warning("下载网易云音频异常: %s", e)

    if not audio_path.exists() or audio_path.stat().st_size < 1024 or not is_valid_audio_file(audio_path):
        audio_path.unlink(missing_ok=True)
        audio_path = None

    return audio_path, lyrics_path, json_path, song


def auto_process_netease(
    url_or_id: str,
    input_dir: Path | str,
    output_dir: Path | str,
    config_file: Optional[Path | str] = None,
    launch_editor: bool = False,
    port: int = 8000,
    progress_callback: Optional[Callable[..., None]] = None,
    skip_separation: Optional[bool] = None,
    use_gpu: Optional[bool] = None,
) -> dict[str, Any]:
    """
    全自动网易云导入管线：
    1. 解析歌曲与歌词，下载音频至 input/
    2. 执行音频分轨与时间轴对齐 (CTC / Whisper)
    3. 生成工程数据至 output/
    """
    input_dir = Path(input_dir).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()

    def _safe_cb(prog: int, msg: str, extra: dict | None = None):
        if not progress_callback:
            return
        try:
            if extra:
                progress_callback(prog, msg, extra=extra)
            else:
                progress_callback(prog, msg)
        except TypeError:
            progress_callback(prog, msg)

    _safe_cb(10, "正在从网易云音乐解析歌曲信息与歌词...")
    song = fetch_netease_song(url_or_id)
    song_name = _sanitize_filename(song.title) or f"netease_{song.id}"

    _safe_cb(
        20,
        f"已获取《{song.title}》（{song.artist}）歌词，正在下载音频...",
        extra={
            "title": song.title,
            "lyrics": song.lyrics or song.raw_lrc,
        }
    )

    song_input_dir = input_dir / song_name
    song_output_dir = output_dir / song_name
    song_input_dir.mkdir(parents=True, exist_ok=True)
    song_output_dir.mkdir(parents=True, exist_ok=True)

    audio_path, lyrics_path, json_path, song = download_netease_song(
        song, song_input_dir, song_name=song_name, save_json=True
    )

    if not audio_path or not audio_path.exists() or not is_valid_audio_file(audio_path):
        raise FileNotFoundError(
            f"未能自动下载歌曲《{song.title}》的音频流。\n"
            f"已成功拉取歌曲信息与精确打点 LRC 歌词！\n"
            f"💡 解决方案：该曲目可能受到平台版权保护限制。请在本地歌词编辑器中，直接将该歌曲的本地 MP3/WAV 上传，即可秒级继续生成视频！"
        )

    from src.config import PipelineConfig

    cfg_file = Path(config_file).resolve() if config_file else Path("pipeline.toml")
    config = PipelineConfig.from_file(cfg_file) if cfg_file.exists() else PipelineConfig()
    config.ass_only = True

    if skip_separation is not None:
        config.skip_separation = skip_separation
    if use_gpu is not None:
        config.separator.device = "cuda" if use_gpu else "cpu"
        from src.aligner import is_safe_cuda_available

        config.aligner.device = "cuda" if (use_gpu and is_safe_cuda_available()) else "cpu"

    if config.skip_separation:
        _safe_cb(35, "⚡ 极速模式：正在进行原曲词级时间轴对齐 (CTC Forced Alignment)...")
    else:
        dev_label = "GPU" if (use_gpu or config.separator.device in ("cuda", "mps")) else "CPU"
        _safe_cb(35, f"正在进行人声与伴奏分离及时间轴对齐 (Demucs[{dev_label}] + CTC)...")

    log.info(">>> 自动执行网易云歌曲音频处理与时间轴对齐 (输出至 %s)...", song_output_dir.name)
    from src.main import process_one

    def _on_step_progress(step: str, p: int, msg: str):
        mapped_pct = min(88, max(35, 35 + int(p * 0.55)))
        _safe_cb(mapped_pct, msg)

    try:
        process_one(audio_path, lyrics_path, song_output_dir, None, config, on_progress=_on_step_progress)
    except TypeError:
        process_one(audio_path, lyrics_path, song_output_dir, None, config)

    _safe_cb(90, "时间轴对齐完成，正在检查工程文件...")
    alignment_json = song_output_dir / f"{song_name}_alignment.json"
    if not alignment_json.exists():
        from src.song_source import SongSource
        source = SongSource.from_folder(song_input_dir)
        source.sync_to_output(song_output_dir)

    editor_url = f"http://127.0.0.1:{port}/?song={song_name}"
    _safe_cb(100, f"《{song.title}》已就绪！", extra={"project_id": song_name, "editor_url": editor_url})

    return {
        "title": song.title,
        "artist": song.artist,
        "album": song.album,
        "song_name": song_name,
        "project_id": song_name,
        "editor_url": editor_url,
        "audio_path": str(audio_path),
        "lyrics_path": str(lyrics_path),
        "output_dir": str(song_output_dir),
    }
