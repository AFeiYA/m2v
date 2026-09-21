"""
Suno 歌曲自动获取 — 从 Suno URL 提取歌曲元数据 JSON、歌词与音频

用法:
    # 1. 提取元数据 JSON 并下载音频与歌词到 ./input
    python -m src.suno_fetch https://suno.com/s/LScMFeOajPYsjwCB

    # 2. 仅提取并输出/保存 JSON
    python -m src.suno_fetch https://suno.com/s/LScMFeOajPYsjwCB --json-only

    # 3. 下载后自动运行 M2V 完整管线 (分轨 + 对齐 + ASS)
    python -m src.suno_fetch https://suno.com/s/LScMFeOajPYsjwCB --run-pipeline

工作原理:
    - 支持 Suno 标准链接 (/song/{uuid}) 与分享短链 (/s/{short_id})。
    - 自动跟随重定向或解析 canonical 标签获取全局唯一歌曲 UUID。
    - 解析 Next.js Turbopack / App Router RSC (React Server Components) payload，
      利用标准 JSON 状态机稳健提取完整的歌曲 clip 数据包（含 v6/chirp-hawk 新模型）。
    - 提取纯歌词（去除 [Verse]、[Intro] 等段落标记与音效指示）。
    - 保存完整元数据 JSON ({name}_suno.json) 以供架构下游使用。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests

from src.utils import log


@dataclass
class SunoSong:
    """从 Suno 页面提取的歌曲完整信息"""
    id: str
    title: str
    artist: str
    audio_url: str
    lyrics: str              # 从 prompt 中提取的纯歌词
    raw_prompt: str          # 完整 prompt (含 [Verse]、音效指导等标记)
    tags: str                # 风格标签
    duration: float          # 时长 (秒)
    model_name: str = ""     # 模型名称 (如 chirp-hawk)
    model_version: str = ""  # 模型版本 (如 v6)
    media_urls: list = field(default_factory=list)  # 新版 CDN 多媒体流地址
    raw_clip: dict = field(default_factory=dict)    # 原始完整 clip JSON 数据包


def resolve_suno_page(url_or_id: str) -> tuple[str, str, str]:
    """
    请求 Suno 页面并解析全局唯一 UUID 与规范页面。

    Returns:
        (song_id, final_url, html)
    """
    target = url_or_id.strip()
    uuid_re = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I
    )

    if uuid_re.match(target):
        page_url = f"https://suno.com/song/{target}"
    elif target.startswith("http://") or target.startswith("https://"):
        page_url = target
    else:
        page_url = f"https://suno.com/song/{target}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    log.info("请求 Suno 页面: %s", page_url)
    resp = requests.get(page_url, headers=headers, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    html = resp.text

    # 1. 尝试从 canonical 标签获取标准 song_id
    canonical_match = re.search(r'<link\s+rel="canonical"\s+href="([^"]+)"', html, re.I)
    if canonical_match:
        canonical_url = canonical_match.group(1)
        m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', canonical_url, re.I)
        if m:
            return m.group(0), resp.url, html

    # 2. 尝试从最终跳转 URL 提取
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', resp.url, re.I)
    if m:
        return m.group(0), resp.url, html

    # 3. 尝试在 HTML 中直接搜寻 UUID
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', html, re.I)
    if m:
        return m.group(0), resp.url, html

    raise ValueError(f"无法从 Suno 页面中提取歌曲 UUID: {url_or_id}")


def fetch_song(url_or_id: str) -> SunoSong:
    """
    从 Suno 公开分享页面获取歌曲对象及完整 JSON 元数据。

    Args:
        url_or_id: Suno URL (支持 /song/{uuid} 与 /s/{short_id}) 或 UUID

    Returns:
        SunoSong 实体，包含 title, lyrics, duration, raw_clip 等所有信息
    """
    song_id, final_url, html = resolve_suno_page(url_or_id)

    clip_data = _extract_clip_from_rsc(html)
    if clip_data is None:
        log.warning("无法从页面 RSC 解析 clip 对象，尝试基础回退...")
        # 尝试从 OpenGraph 获取基础信息
        og_title_m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html)
        title = og_title_m.group(1) if og_title_m else song_id
        audio_url = f"https://cdn1.suno.ai/{song_id}.mp3"
        return SunoSong(
            id=song_id,
            title=title,
            artist="unknown",
            audio_url=audio_url,
            lyrics="",
            raw_prompt="",
            tags="",
            duration=0.0,
            raw_clip={"id": song_id, "title": title, "audio_url": audio_url},
        )

    metadata = clip_data.get("metadata", {}) or {}
    raw_prompt = metadata.get("prompt", "") or ""
    lyrics = _clean_lyrics(raw_prompt)

    # 音频地址判定: 优先 media_urls，其次 audio_url，最后 cdn1
    audio_url = ""
    media_urls = clip_data.get("media_urls") or []
    if media_urls and isinstance(media_urls, list):
        for item in media_urls:
            if isinstance(item, dict) and item.get("url"):
                audio_url = item["url"]
                break

    if not audio_url or "forbidden" in audio_url:
        cand_url = clip_data.get("audio_url", "")
        if cand_url and "forbidden" not in cand_url:
            audio_url = cand_url
        else:
            audio_url = f"https://cdn1.suno.ai/{song_id}.mp3"

    title = clip_data.get("title") or song_id
    artist = clip_data.get("display_name") or clip_data.get("handle") or "unknown"
    duration = float(metadata.get("duration", 0.0) or 0.0)
    tags = clip_data.get("display_tags") or metadata.get("tags") or ""
    model_name = clip_data.get("model_name", "")
    model_version = clip_data.get("major_model_version", "")

    return SunoSong(
        id=song_id,
        title=title,
        artist=artist,
        audio_url=audio_url,
        lyrics=lyrics,
        raw_prompt=raw_prompt,
        tags=tags,
        duration=duration,
        model_name=model_name,
        model_version=model_version,
        media_urls=media_urls,
        raw_clip=clip_data,
    )


def _extract_clip_from_rsc(html: str) -> dict | None:
    """
    从 Next.js Turbopack / App Router RSC 数据流中提取完整 clip 字典。
    通过 JSONDecoder 正确处理反斜杠、多字节 Unicode 与复杂转义。
    """
    needle = 'self.__next_f.push([1,'
    pos = 0
    decoder = json.JSONDecoder()

    while True:
        pos = html.find(needle, pos)
        if pos == -1:
            break
        chunk_start = pos + len(needle)
        try:
            raw_str, _ = decoder.raw_decode(html[chunk_start:])
            if '"clip":{' in raw_str:
                clip_idx = raw_str.find('"clip":{')
                obj_start = clip_idx + len('"clip":')
                clip_dict = _parse_enclosing_json(raw_str, obj_start)
                if clip_dict:
                    return clip_dict
            elif '"entity_type":"song_schema"' in raw_str:
                # 寻找包含 song_schema 的最外层对象
                idx = raw_str.find('"entity_type":"song_schema"')
                start_cand = raw_str.rfind('{', 0, idx)
                if start_cand != -1:
                    clip_dict = _parse_enclosing_json(raw_str, start_cand)
                    if clip_dict and clip_dict.get("id"):
                        return clip_dict
        except Exception:
            pass
        pos += len(needle)

    return None


def _parse_enclosing_json(text: str, start: int) -> dict | None:
    """从 text[start] 开始通过括号匹配解析完整的 JSON 对象"""
    i = start
    while i < len(text) and text[i] in ' \t\n\r':
        i += 1
    if i >= len(text) or text[i] != '{':
        return None

    depth = 0
    in_str = False
    escape = False

    for j in range(i, len(text)):
        ch = text[j]
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                substr = text[i:j + 1]
                try:
                    return json.loads(substr)
                except Exception:
                    return None
    return None


def _clean_lyrics(prompt: str) -> str:
    """
    从 Suno prompt 中提取纯歌词文本。
    过滤 [Verse 1]、[Chorus]、[Intro]、[Outro: ...]、[End] 等方括号标签，
    以及 (Ambient wind...) 等音效/乐器演奏指导，保留所有实际歌词。
    """
    lines = prompt.split('\n')
    result: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if result and result[-1] != '':
                result.append('')
            continue

        # 过滤方括号标签，如 [Verse 1], [Chorus], [Intro], [Outro: ...], [End], [Solo]
        if stripped.startswith('[') and stripped.endswith(']'):
            continue

        # 过滤圆括号说明，如 (Warm analog synth pads swell...), (Ambient wind...)
        if stripped.startswith('(') and stripped.endswith(')'):
            continue

        result.append(stripped)

    while result and result[0] == '':
        result.pop(0)
    while result and result[-1] == '':
        result.pop()

    return '\n'.join(result)


def parse_suno_prompt_sections(prompt: str) -> list[dict]:
    """
    解析 Suno prompt 中的乐段标记与音效提示。
    识别 [Intro], [Verse 1], [Pre-Chorus], [Chorus: Style], [Bridge], [Outro], [End] 等标签，
    以及 (Ambient wind...), (Warm synth...) 等音效描述，归类各段包含的歌词文本。
    """
    sections_raw = []
    current_sec = None

    label_map = {
        'intro': '前奏',
        'verse': '主歌',
        'pre-chorus': '预副歌',
        'chorus': '副歌',
        'bridge': '桥段',
        'solo': '间奏',
        'interlude': '间奏',
        'outro': '尾奏',
        'end': '结束'
    }

    name_counts: dict[str, int] = {}

    for raw_line in prompt.split('\n'):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            tag_content = line[1:-1].strip()
            if ':' in tag_content:
                sec_name, sec_style = tag_content.split(':', 1)
                sec_name = sec_name.strip()
                sec_style = sec_style.strip()
            else:
                sec_name = tag_content
                sec_style = ''

            base_lower = sec_name.lower()
            label = sec_name
            for k, v in label_map.items():
                if k in base_lower:
                    num_match = re.search(r'\d+', sec_name)
                    num = f" {num_match.group(0)}" if num_match else ""
                    label = f"{v}{num}"
                    break

            clean_name = re.sub(r'\s*\d+', '', sec_name).strip()
            name_counts[clean_name] = name_counts.get(clean_name, 0) + 1
            if name_counts[clean_name] > 1 and not re.search(r'\d+', sec_name):
                sec_name = f"{sec_name} {name_counts[clean_name]}"
                if not re.search(r'\d+', label):
                    label = f"{label} {name_counts[clean_name]}"

            current_sec = {
                'name': sec_name,
                'label': label,
                'style': sec_style,
                'lyric_texts': []
            }
            sections_raw.append(current_sec)
        elif line.startswith('(') and line.endswith(')'):
            sound_style = line[1:-1].strip()
            if current_sec:
                if current_sec['style']:
                    current_sec['style'] += '; ' + sound_style
                else:
                    current_sec['style'] = sound_style
        else:
            if current_sec is None:
                current_sec = {'name': 'Verse 1', 'label': '主歌 1', 'style': '', 'lyric_texts': []}
                sections_raw.append(current_sec)
            current_sec['lyric_texts'].append(line)

    return sections_raw


def enrich_alignment_sections(
    alignment_json_path: Path,
    raw_prompt: str,
    total_duration: float | None = None,
):
    """
    将 Suno 原始 Prompt 中的乐段与音效提示注入 alignment.json：
    1. 计算每个 Section 的精确时间戳 (start, end)
    2. 为每行歌词标注所属 section
    3. 保留并回写 alignment.json (100% 保持 ASS 与编辑器的向后兼容)
    """
    from src.aligner import AlignmentResult, MusicSection

    alignment = AlignmentResult.load_json(alignment_json_path)
    if not alignment.lines or not raw_prompt:
        return alignment

    parsed_sections = parse_suno_prompt_sections(raw_prompt)
    if not parsed_sections:
        return alignment

    line_cursor = 0
    total_lines = len(alignment.lines)
    music_sections: list[MusicSection] = []

    for sec in parsed_sections:
        texts = sec['lyric_texts']
        count = len(texts)
        sec_name = sec['name']
        sec_label = sec['label']
        sec_style = sec['style']

        if count == 0:
            if 'intro' in sec_name.lower():
                sec_start = 0.0
                sec_end = alignment.lines[0].start if total_lines > 0 else 0.0
                music_sections.append(MusicSection(
                    name=sec_name,
                    label=sec_label,
                    style=sec_style,
                    start=round(sec_start, 3),
                    end=round(sec_end, 3),
                    line_indices=[]
                ))
            continue

        if line_cursor >= total_lines:
            break

        start_idx = line_cursor
        end_idx = min(line_cursor + count, total_lines)
        matched_indices = list(range(start_idx, end_idx))

        for idx in matched_indices:
            alignment.lines[idx].section = sec_name

        sec_start = alignment.lines[start_idx].start
        sec_end = alignment.lines[end_idx - 1].end

        if 'outro' in sec_name.lower() and total_duration and total_duration > sec_end:
            sec_end = total_duration

        music_sections.append(MusicSection(
            name=sec_name,
            label=sec_label,
            style=sec_style,
            start=round(sec_start, 3),
            end=round(sec_end, 3),
            line_indices=matched_indices
        ))

        line_cursor = end_idx

    alignment.sections = music_sections
    alignment.save_json(alignment_json_path)
    log.info("已成功将 %d 个乐段 (含 Intro/Verse/Chorus/Outro) 写入 %s", len(music_sections), alignment_json_path.name)
    return alignment



def download_song(
    url_or_id: str,
    output_dir: Path,
    *,
    song_name: str | None = None,
    save_json: bool = True,
) -> tuple[Path | None, Path, Path, SunoSong]:
    """
    从 Suno 获取歌曲信息，并下载保存：
      1. {name}_suno.json (完整元数据 JSON)
      2. {name}.txt (纯歌词文本)
      3. {name}.mp3 或 {name}.m4a (音频源文件，如不可下载则为 None)

    Returns:
        (audio_path, lyrics_path, json_path, song)
    """
    song = fetch_song(url_or_id)
    name = song_name or _sanitize_filename(song.title)
    if not name:
        name = song.id

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{name}_suno.json"
    lyrics_path = output_dir / f"{name}.txt"

    # 1. 写入完整 JSON 元数据
    if save_json:
        json_path.write_text(
            json.dumps(song.raw_clip, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        log.info("元数据 JSON 已保存: %s", json_path.name)

    # 2. 写入清洗后歌词
    if song.lyrics:
        lyrics_path.write_text(song.lyrics, encoding="utf-8")
        log.info("歌词已保存: %s (%d 行)", lyrics_path.name, song.lyrics.count('\n') + 1)
    else:
        lyrics_path.write_text(song.raw_prompt, encoding="utf-8")
        log.warning("未检测到标准歌词段，已保存原始 prompt")

    # 3. 尝试下载音频
    audio_path = None
    if song.audio_url and "forbidden" not in song.audio_url:
        ext = ".m4a" if ".m4a" in song.audio_url else ".mp3"
        dest_audio = output_dir / f"{name}{ext}"
        log.info("下载音频: %s → %s", song.audio_url, dest_audio.name)
        try:
            resp = requests.get(song.audio_url, stream=True, timeout=120, headers={
                "User-Agent": "Mozilla/5.0",
            })
            if resp.status_code == 200:
                with open(dest_audio, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                file_size_mb = dest_audio.stat().st_size / 1024 / 1024
                log.info("音频下载完成: %.2fMB (%s)", file_size_mb, dest_audio.name)
                audio_path = dest_audio
            else:
                log.warning("音频流不可直接下载 (HTTP %d)，跳过音频下载", resp.status_code)
        except Exception as e:
            log.warning("音频下载异常: %s", e)

    # 4. 若下载失败或流不可用，自动从本地环境/系统 Downloads 智能查找已下载的音频
    if not audio_path or not audio_path.exists() or audio_path.stat().st_size < 100_000:
        local_audio = resolve_or_find_audio(name, song.id, output_dir)
        if local_audio:
            audio_path = local_audio

    return audio_path, lyrics_path, json_path, song


def resolve_or_find_audio(title: str, song_id: str, input_dir: Path) -> Path | None:
    """
    智能定位歌曲的音频文件：
    1. 检查 input_dir/{title}.(mp3|wav|m4a|flac)
    2. 检查系统下载目录 (~/Downloads) 是否有刚从 Suno 导出的音频，自动复制到 input_dir
    """
    import shutil
    input_dir = Path(input_dir).resolve()
    for ext in ['.wav', '.mp3', '.flac', '.m4a']:
        cand = input_dir / f"{title}{ext}"
        if cand.exists() and cand.stat().st_size > 100_000:
            return cand
    dl = Path.home() / "Downloads"
    if dl.exists():
        for ext in ['.wav', '.mp3', '.flac']:
            # 精确匹配
            cand = dl / f"{title}{ext}"
            if cand.exists() and cand.stat().st_size > 100_000:
                dst = input_dir / f"{title}{ext}"
                shutil.copy2(cand, dst)
                log.info("从系统 Downloads 自动发现并导入音频: %s → %s", cand.name, dst.name)
                return dst
            # 模糊匹配
            matches = [f for f in dl.glob(f"*{title}*{ext}") if f.stat().st_size > 100_000]
            if matches:
                newest = max(matches, key=lambda f: f.stat().st_mtime)
                dst = input_dir / f"{title}{ext}"
                shutil.copy2(newest, dst)
                log.info("从系统 Downloads 自动定位最新音频: %s → %s", newest.name, dst.name)
                return dst

        # UUID 匹配
        if song_id:
            uuid_matches = [f for f in dl.glob(f"*{song_id}*") if f.is_file() and f.stat().st_size > 100_000]
            if uuid_matches:
                newest = max(uuid_matches, key=lambda f: f.stat().st_mtime)
                dst = input_dir / f"{title}{newest.suffix}"
                shutil.copy2(newest, dst)
                log.info("根据 UUID 在 Downloads 发现音频: %s → %s", newest.name, dst.name)
                return dst
    return None


def launch_local_editor_browser(song_name: str, port: int = 8000) -> None:
    """确保本地编辑器服务运行并在默认浏览器中直接打开该歌曲的编辑界面"""
    import socket
    import subprocess
    import time
    import webbrowser
    from urllib.parse import quote

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    is_running = (sock.connect_ex(('127.0.0.1', port)) == 0)
    sock.close()

    if not is_running:
        log.info("启动本地双轨编辑器服务 (http://127.0.0.1:%d)...", port)
        root_dir = Path(__file__).resolve().parent.parent
        popen_kwargs = {"cwd": str(root_dir)}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        subprocess.Popen(
            [sys.executable, "-m", "src.local_editor", "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **popen_kwargs,
        )
        for _ in range(25):
            time.sleep(0.2)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.2)
            ok = (s.connect_ex(('127.0.0.1', port)) == 0)
            s.close()
            if ok:
                break

    editor_url = f"http://127.0.0.1:{port}/?song={quote(song_name)}"
    log.info("🚀 正在浏览器中打开编辑页面: %s", editor_url)
    webbrowser.open(editor_url)


def auto_process_suno(
    url: str,
    input_dir: Path | None = None,
    output_dir: Path | None = None,
    config_file: Path | None = None,
    launch_editor: bool = True,
    port: int = 8000,
) -> dict:
    """
    全自动流程:
    Suno URL -> 获取歌词/元数据 -> 定位音频 -> Demucs 人声/伴奏分离 -> 词级时间轴对齐 -> 直接唤起本地双轨编辑器
    所有产物按歌曲名称专属子目录归档: input/{song_name}/ 和 output/{song_name}/
    """
    input_dir = Path(input_dir or "./input").resolve()
    output_dir = Path(output_dir or "./output").resolve()
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info(">>> [步骤 1/3] 从 Suno 获取歌曲信息与歌词...")
    song = fetch_song(url)
    song_name = _sanitize_filename(song.title) or song.id

    # 建立歌曲专属目录
    song_input_dir = input_dir / song_name
    song_output_dir = output_dir / song_name
    song_input_dir.mkdir(parents=True, exist_ok=True)
    song_output_dir.mkdir(parents=True, exist_ok=True)

    audio_path, lyrics_path, json_path, song = download_song(
        url, song_input_dir, song_name=song_name, save_json=True
    )

    if not audio_path or not audio_path.exists():
        audio_path = resolve_or_find_audio(song_name, song.id, song_input_dir)

    if not audio_path or not audio_path.exists():
        raise FileNotFoundError(
            f"未找到歌曲 [{song_name}] 的可处理音频。\n"
            f"已成功拉取歌词与元数据！请在 Suno 网页点击下载该音频，或将其放置于 input/{song_name}/ 目录后重试。"
        )

    log.info(">>> [步骤 2/3] 自动执行音频分轨与字级时间轴对齐 (输出至 %s)...", song_output_dir.name)
    from src.main import process_one
    from src.config import PipelineConfig

    cfg_file = config_file or Path("pipeline.toml")
    config = PipelineConfig.from_file(cfg_file) if cfg_file.exists() else PipelineConfig()
    config.ass_only = True

    process_one(audio_path, lyrics_path, song_output_dir, None, config)

    # 自动解析并注入乐段结构 (Intro, Verse, Chorus, Bridge, Outro) 与情绪描述
    alignment_json_path = song_output_dir / f"{song_name}_alignment.json"
    if alignment_json_path.exists() and song.raw_prompt:
        try:
            enrich_alignment_sections(alignment_json_path, song.raw_prompt, total_duration=song.duration)
        except Exception as e:
            log.warning("乐段结构注入异常 (不影响对齐): %s", e)

    log.info(">>> [步骤 3/3] 对齐已完成，准备载入本地双轨编辑器...")
    if launch_editor:
        launch_local_editor_browser(song_name, port=port)

    from urllib.parse import quote
    return {
        "status": "ok",
        "title": song_name,
        "artist": song.artist,
        "alignment_json": str(song_output_dir / f"{song_name}_alignment.json"),
        "vocals_wav": str(song_output_dir / f"{song_name}_vocals.wav"),
        "instrumental_wav": str(song_output_dir / f"{song_name}_instrumental.wav"),
        "ass_path": str(song_output_dir / f"{song_name}.ass"),
        "editor_url": f"http://127.0.0.1:{port}/?song={quote(song_name)}",
    }


def _sanitize_filename(name: str) -> str:
    """清理文件名非法字符"""
    cleaned = re.sub(r'[<>:"/\\|?*]', '', name).strip(' .')
    return cleaned[:100] if len(cleaned) > 100 else cleaned


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.suno_fetch",
        description="从 Suno URL 自动提取元数据、对齐时间轴并直达本地双轨编辑器",
    )
    parser.add_argument(
        "url",
        help="Suno 歌曲 URL (如 https://suno.com/s/xxx 或 https://suno.com/song/xxx)",
    )
    parser.add_argument(
        "--output", "-o",
        default="./output",
        help="对齐产物输出目录 (默认: ./output)",
    )
    parser.add_argument(
        "--input-dir",
        default="./input",
        help="源文件下载/存放目录 (默认: ./input)",
    )
    parser.add_argument(
        "--name", "-n",
        default=None,
        help="自定义保存名称 (不含扩展名)，默认使用歌曲标题",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="仅提取并输出歌曲完整 JSON，不进行音频处理",
    )
    parser.add_argument(
        "--edit", "-e",
        action="store_true",
        help="【全自动】一键完成下载、分轨、时间轴对齐并在浏览器打开本地双轨编辑页",
    )
    parser.add_argument(
        "--run-pipeline",
        action="store_true",
        help="下载后自动运行处理管线 (分轨 + 对齐 + ASS)",
    )
    parser.add_argument(
        "--config-file",
        default=None,
        help="配置文件路径 (.toml/.json)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="本地编辑器端口 (默认: 8000)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()

    if args.json_only:
        try:
            song = fetch_song(args.url)
            print(json.dumps(song.raw_clip, ensure_ascii=False, indent=2))
            input_dir.mkdir(parents=True, exist_ok=True)
            name = args.name or _sanitize_filename(song.title) or song.id
            out_json = input_dir / f"{name}_suno.json"
            out_json.write_text(json.dumps(song.raw_clip, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n[OK] JSON 已保存至: {out_json}", file=sys.stderr)
            return
        except Exception as e:
            print(f"[错误] 提取失败: {e}", file=sys.stderr)
            sys.exit(1)

    # 全自动直达编辑器流程
    if args.edit:
        try:
            cfg_path = Path(args.config_file).resolve() if args.config_file else None
            result = auto_process_suno(
                args.url,
                input_dir=input_dir,
                output_dir=output_dir,
                config_file=cfg_path,
                launch_editor=True,
                port=args.port,
            )
            print(f"\n{'='*55}")
            print(f"  ✅ 自动化流程完成！")
            print(f"  歌曲: {result['title']}")
            print(f"  编辑器已打开: {result['editor_url']}")
            print(f"{'='*55}")
            return
        except Exception as e:
            print(f"[错误] 自动化流程失败: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        audio_path, lyrics_path, json_path, song = download_song(
            args.url, input_dir, song_name=args.name, save_json=True
        )
    except ValueError as e:
        print(f"[错误] {e}")
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"[错误] 网络请求失败: {e}")
        sys.exit(1)

    print(f"\n{'='*55}")
    print(f"  歌曲:     {song.title}")
    print(f"  作者:     {song.artist}")
    print(f"  模型:     {song.model_name} ({song.model_version})")
    print(f"  时长:     {song.duration:.1f}s")
    print(f"  风格:     {song.tags}")
    print(f"  元数据:   {json_path}")
    print(f"  歌词文件: {lyrics_path}")
    if audio_path:
        print(f"  音频文件: {audio_path}")
    print(f"{'='*55}")

    if args.run_pipeline:
        if not audio_path:
            print("\n[警告] 未获取到音频文件，无法继续运行音频处理管线。")
            return
        print("\n开始运行处理管线...")
        from src.main import process_one
        from src.config import PipelineConfig

        config = PipelineConfig.from_file(args.config_file) if args.config_file else PipelineConfig()

        output_dir.mkdir(parents=True, exist_ok=True)
        process_one(audio_path, lyrics_path, output_dir, None, config)


if __name__ == "__main__":
    main()
