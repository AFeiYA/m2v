"""Portable source credits/artwork, separate from user presentation overrides."""
from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import requests

from src.song_cover import MAX_BYTES, prepare_cover
from src.utils import log


def source_keys(audio_key: str) -> tuple[str, str]:
    parent = PurePosixPath(audio_key).parent
    return str(parent / 'source_suno.json'), str(parent / 'source_cover.jpg')


def download_artwork(url: str) -> bytes:
    parsed = urlparse(url)
    host = parsed.hostname or ''
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443) or not (
        host.endswith('.suno.ai') or host.endswith('.suno.com')
    ):
        raise ValueError('封面地址不属于可读取的 Suno 图片服务')
    with requests.get(url, timeout=(3, 10), stream=True, allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('封面服务未返回图片')
        content = bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > MAX_BYTES:
                raise ValueError('封面超过 10 MB')
    return prepare_cover(bytes(content))[0]


async def save_source(storage, audio_key: str, song) -> dict:
    metadata_key, cover_key = source_keys(audio_key)
    raw = getattr(song, 'raw_clip', {}) or {}
    image = raw.get('image_large_url') or raw.get('image_url') or ''
    artist = getattr(song, 'artist', '') or raw.get('display_name') or raw.get('handle') or ''
    if str(artist).strip().lower() == 'unknown':
        artist = ''
    # Keep only presentation facts, never the full third-party payload.
    metadata = {'version': 'song-source-v1', 'id': song.id, 'title': song.title,
                'artist': artist, 'image_url': image,
                'source_url': f'https://suno.com/song/{song.id}'}
    from src.suno_fetch import parse_suno_prompt_sections
    prompt = getattr(song, 'raw_prompt', '') or ''
    if '[' in prompt:
        metadata['sections'] = parse_suno_prompt_sections(prompt)
    warning = ''
    with tempfile.TemporaryDirectory(prefix='m2v-artwork-') as directory:
        root = Path(directory)
        previous = {}
        if await storage.exists(metadata_key):
            old_path = root / 'previous.json'
            await storage.load(metadata_key, old_path)
            try:
                previous = json.loads(old_path.read_text())
            except (ValueError, OSError):
                pass
        if isinstance(previous, dict) and previous.get('artwork_sha256'):
            metadata['artwork_sha256'] = previous['artwork_sha256']
        if image:
            try:
                content = await asyncio.to_thread(download_artwork, image)
                digest = hashlib.sha256(content).hexdigest()
                if digest != metadata.get('artwork_sha256') or not await storage.exists(cover_key):
                    cover = root / 'cover.jpg'
                    cover.write_bytes(content)
                    await storage.save(cover_key, cover)
                metadata['artwork_sha256'] = digest
            except Exception as exc:
                warning = '封面暂时无法读取，已保留歌曲信息，可稍后重试'
                log.warning('Suno 封面缓存未完成: %s', type(exc).__name__)
        path = root / 'metadata.json'
        path.write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')
        await storage.save(metadata_key, path)
    return {'metadata': metadata, 'warning': warning}
