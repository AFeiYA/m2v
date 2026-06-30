"""
Suno 歌曲自动获取 — 从 Suno URL 提取 MP3 和歌词

用法:
    python -m src.suno_fetch https://suno.com/song/xxxxx
    python -m src.suno_fetch https://suno.com/s/xxxxx --output ./input

工作原理:
    Suno 页面使用 Next.js RSC (React Server Components)，
    歌曲元数据（标题、音频 CDN URL、歌词/prompt）嵌入在页面 HTML 的
    RSC payload 中。本模块解析该 payload 提取所需数据。

注意:
    仅对公开分享的歌曲有效。私有歌曲需要登录，本模块不支持。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from src.utils import log


@dataclass
class SunoSong:
    """从 Suno 页面提取的歌曲信息"""
    id: str
    title: str
    artist: str
    audio_url: str
    lyrics: str           # 从 prompt 中提取的纯歌词
    raw_prompt: str       # 完整 prompt (含 [Verse] 等标记)
    tags: str             # 风格标签
    duration: float


def extract_song_id(url: str) -> str:
    """
    从 Suno URL 提取歌曲 ID。

    支持的格式:
      - https://suno.com/song/{id}
      - https://suno.com/s/{id}
      - 直接传入 UUID
    """
    url = url.strip()

    # 纯 UUID
    uuid_re = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I
    )
    if uuid_re.match(url):
        return url

    parsed = urlparse(url)
    # /song/{id} 或 /s/{id}
    parts = [p for p in parsed.path.split('/') if p]
    if len(parts) >= 2 and parts[0] in ('song', 's'):
        candidate = parts[1]
        if uuid_re.match(candidate):
            return candidate

    # 如果无法直接提取（例如是 /s/3pkzqXgDSlZq9xcm 缩短链接），尝试进行一次网络请求以跟随重定向
    try:
        log.info("尝试跟随重定向解析 Suno URL: %s", url)
        # 用 requests.get 跟随重定向，这里设置较短的 timeout 并只允许 GET
        resp = requests.get(url, allow_redirects=True, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        final_url = resp.url
        parsed_final = urlparse(final_url)
        parts_final = [p for p in parsed_final.path.split('/') if p]
        if len(parts_final) >= 2 and parts_final[0] in ('song', 's'):
            candidate = parts_final[1]
            if uuid_re.match(candidate):
                return candidate
    except Exception as e:
        log.warning("跟随重定向解析失败: %s", e)

    raise ValueError(
        f"无法从 URL 提取歌曲 ID: {url}\n"
        "支持格式: https://suno.com/song/UUID 或 https://suno.com/s/UUID"
    )


def fetch_song(url_or_id: str) -> SunoSong:
    """
    从 Suno 公开页面获取歌曲信息。

    Args:
        url_or_id: Suno 歌曲 URL 或 UUID

    Returns:
        SunoSong 对象，包含标题、音频 URL、歌词等

    Raises:
        ValueError: URL 格式错误或页面无法解析
        requests.HTTPError: 网络请求失败
    """
    song_id = extract_song_id(url_or_id)
    page_url = f"https://suno.com/song/{song_id}"

    log.info("获取 Suno 页面: %s", page_url)
    resp = requests.get(page_url, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html",
    })
    resp.raise_for_status()

    html = resp.text

    # --- 从 RSC payload 中提取 clip 数据 ---
    # Suno 使用 Next.js RSC，歌曲数据以 JSON 格式嵌入在 self.__next_f.push 调用中
    # clip 数据包含 "audio_url", "title", "metadata" 等字段
    clip_data = _extract_clip_from_rsc(html)
    if clip_data is None:
        # 尝试从 CDN URL 猜测 (fallback)
        audio_url = f"https://cdn1.suno.ai/{song_id}.mp3"
        log.warning("无法从页面提取完整数据，使用猜测的 CDN URL: %s", audio_url)
        return SunoSong(
            id=song_id, title=song_id, artist="unknown",
            audio_url=audio_url, lyrics="", raw_prompt="",
            tags="", duration=0.0,
        )

    metadata = clip_data.get("metadata", {})
    raw_prompt = metadata.get("prompt", "")
    lyrics = _clean_lyrics(raw_prompt)

    return SunoSong(
        id=song_id,
        title=clip_data.get("title", song_id),
        artist=clip_data.get("display_name", "unknown"),
        audio_url=clip_data.get("audio_url", f"https://cdn1.suno.ai/{song_id}.mp3"),
        lyrics=lyrics,
        raw_prompt=raw_prompt,
        tags=clip_data.get("display_tags", metadata.get("tags", "")),
        duration=metadata.get("duration", 0.0),
    )


def _extract_clip_from_rsc(html: str) -> dict | None:
    """
    从 Suno 页面的 RSC payload 中提取 clip(歌曲)数据。

    RSC payload 格式: self.__next_f.push([1,"...escaped JSON..."])
    其中包含 "clip":{...} 或 "audio_url":"https://cdn1.suno.ai/..." 的片段。
    """
    # 查找页面中所有的 script 标签内容
    script_contents = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)

    for content in script_contents:
        content = content.strip()
        if "self.__next_f.push" not in content:
            continue

        # 查找数组边界以安全解析 JSON (避开正则表达式在匹配包含 ) 等字符时提前终止的问题)
        start_idx = content.find("[")
        end_idx = content.rfind("]")
        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            continue

        array_str = content[start_idx:end_idx+1]
        try:
            parsed_args = json.loads(array_str)
            if not (isinstance(parsed_args, list) and len(parsed_args) >= 2 and isinstance(parsed_args[1], str)):
                continue
            
            unescaped = parsed_args[1]
            if '"audio_url"' not in unescaped or 'cdn1.suno.ai' not in unescaped:
                continue

            # 尝试找到 clip JSON 对象
            clip_match = re.search(r'"clip"\s*:\s*\{', unescaped)
            if clip_match:
                # 从 clip_match 开始，找到匹配的 }
                start = clip_match.start() + len('"clip":')
                clip_json = _extract_json_object(unescaped, start)
                if clip_json:
                    try:
                        return json.loads(clip_json)
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            log.warning("解析 script 标签中的 RSC 数据失败: %s", e)

    return None


def _extract_json_object(text: str, start: int) -> str | None:
    """从 text[start] 开始提取一个完整的 JSON 对象 {...}"""
    # 跳过空白
    i = start
    while i < len(text) and text[i] in ' \t\n\r':
        i += 1

    if i >= len(text) or text[i] != '{':
        return None

    depth = 0
    in_string = False
    escape = False

    for j in range(i, len(text)):
        ch = text[j]
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[i:j + 1]

    return None


def _clean_lyrics(prompt: str) -> str:
    """
    从 Suno prompt 中提取纯歌词文本。

    去除方括号标记如 [Verse 1], [Chorus], [Intro] 等,
    去除纯器乐描述行，保留实际歌词。
    """
    lines = prompt.split('\n')
    result = []
    skip_until_next_section = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            # 空行保留 (段落分隔)
            if result and result[-1] != '':
                result.append('')
            continue

        # 方括号标记行
        if stripped.startswith('[') and stripped.endswith(']'):
            tag = stripped[1:-1].lower()
            # 纯器乐段落标记 → 跳过后续内容直到下一个标记
            instrumental_tags = ['interlude', 'instrumental',
                                 'bridge instrumental', 'solo', 'guitar solo']
            if any(t in tag for t in instrumental_tags):
                skip_until_next_section = True
            else:
                skip_until_next_section = False
            continue

        if skip_until_next_section:
            continue

        # 纯器乐描述行 (通常以小写方括号包裹)
        if stripped.startswith('[') or stripped.startswith('('):
            # 可能是舞台指导如 [strummed acoustic guitar]
            continue

        result.append(stripped)

    # 清理首尾空行
    while result and result[0] == '':
        result.pop(0)
    while result and result[-1] == '':
        result.pop()

    return '\n'.join(result)


def download_song(
    url_or_id: str,
    output_dir: Path,
    *,
    song_name: str | None = None,
) -> tuple[Path, Path, SunoSong]:
    """
    下载 Suno 歌曲的 MP3 和歌词到本地。

    Args:
        url_or_id: Suno URL 或 歌曲 UUID
        output_dir: 输出目录
        song_name: 可选，自定义文件名 (不含扩展名)

    Returns:
        (mp3_path, lyrics_path, song_info)
    """
    song = fetch_song(url_or_id)

    # 确定文件名
    name = song_name or _sanitize_filename(song.title)
    if not name:
        name = song.id

    output_dir.mkdir(parents=True, exist_ok=True)
    mp3_path = output_dir / f"{name}.mp3"
    lyrics_path = output_dir / f"{name}.txt"

    # 下载 MP3
    log.info("下载 MP3: %s → %s", song.audio_url, mp3_path.name)
    resp = requests.get(song.audio_url, timeout=120, stream=True, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    resp.raise_for_status()

    with open(mp3_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    file_size_mb = mp3_path.stat().st_size / 1024 / 1024
    log.info("MP3 下载完成: %.1fMB", file_size_mb)

    # 保存歌词
    if song.lyrics:
        lyrics_path.write_text(song.lyrics, encoding='utf-8')
        log.info("歌词已保存: %s (%d 行)", lyrics_path.name, song.lyrics.count('\n') + 1)
    else:
        log.warning("未提取到歌词，可能需要手动添加")
        lyrics_path.write_text("", encoding='utf-8')

    return mp3_path, lyrics_path, song


def _sanitize_filename(name: str) -> str:
    """清理文件名，去除非法字符"""
    # 去除 Windows 非法字符
    cleaned = re.sub(r'[<>:"/\\|?*]', '', name)
    # 去除首尾空白和点
    cleaned = cleaned.strip(' .')
    # 截断
    if len(cleaned) > 100:
        cleaned = cleaned[:100]
    return cleaned


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.suno_fetch",
        description="从 Suno URL 自动下载 MP3 + 歌词",
    )
    parser.add_argument(
        "url",
        help="Suno 歌曲 URL (如 https://suno.com/song/xxx 或 https://suno.com/s/xxx)",
    )
    parser.add_argument(
        "--output", "-o",
        default="./input",
        help="输出目录 (默认: ./input)",
    )
    parser.add_argument(
        "--name", "-n",
        default=None,
        help="自定义文件名 (不含扩展名)，默认使用歌曲标题",
    )
    parser.add_argument(
        "--run-pipeline",
        action="store_true",
        help="下载后自动运行完整处理管线 (分轨 + 对齐 + ASS)",
    )
    parser.add_argument(
        "--config-file",
        default=None,
        help="配置文件路径 (.toml/.json)，仅在 --run-pipeline 时使用",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    output_dir = Path(args.output).expanduser().resolve()

    try:
        mp3_path, lyrics_path, song = download_song(
            args.url, output_dir, song_name=args.name,
        )
    except ValueError as e:
        print(f"[错误] {e}")
        sys.exit(1)
    except requests.HTTPError as e:
        print(f"[错误] 网络请求失败: {e}")
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"  歌曲: {song.title}")
    print(f"  作者: {song.artist}")
    print(f"  时长: {song.duration:.1f}s")
    print(f"  风格: {song.tags}")
    print(f"  MP3:  {mp3_path}")
    print(f"  歌词: {lyrics_path}")
    print(f"{'='*50}")

    if args.run_pipeline:
        print("\n开始运行处理管线...")
        from src.main import process_one
        from src.config import PipelineConfig
        import tomllib

        config = PipelineConfig()
        if args.config_file:
            config_path = Path(args.config_file).expanduser().resolve()
            from src.main import _apply_config_file
            _apply_config_file(config, config_path)

        pipeline_output = Path("./output").resolve()
        pipeline_output.mkdir(parents=True, exist_ok=True)

        process_one(mp3_path, lyrics_path, pipeline_output, None, config)


if __name__ == "__main__":
    main()
