"""Local, portable cover assets for previews and render snapshots."""
from __future__ import annotations
import base64
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from src.song_identity import source_identity

MAX_BYTES = 10 * 1024 * 1024


def cover_path(project_path: Path, custom=True) -> Path:
    name = project_path.stem.removesuffix('_alignment').removesuffix('_project')
    return project_path.with_name(name + ('_motion_cover.jpg' if custom else '_motion_suno_cover.jpg'))


def prepare_cover(content: bytes) -> tuple[bytes, int, int]:
    if not content or len(content) > MAX_BYTES:
        raise ValueError('封面文件需小于 10 MB')
    try:
        with Image.open(BytesIO(content)) as original:
            if original.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValueError('封面仅支持 JPG、PNG、WebP')
            if original.width * original.height > 24_000_000:
                raise ValueError('封面像素过大，请使用小于 2400 万像素的图片')
            image = ImageOps.exif_transpose(original).convert('RGBA')
            image.thumbnail((1600, 1600))
            background = Image.new('RGB', image.size, '#101010')
            background.paste(image, mask=image.getchannel('A'))
            output = BytesIO()
            background.save(output, format='JPEG', quality=90)
            return output.getvalue(), image.width, image.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('无法读取封面图片，请选择有效的 JPG、PNG 或 WebP') from exc


@lru_cache(maxsize=16)
def _asset(path: str, modified: int, size: int) -> dict:
    content, width, height = prepare_cover(Path(path).read_bytes())
    return {'data_url': 'data:image/jpeg;base64,' + base64.b64encode(content).decode(), 'width': width, 'height': height}


def resolve_cover(project_path: Path, payload: dict, input_root: Path, audio_path: Path | None = None) -> dict:
    name = project_path.stem.removesuffix('_alignment').removesuffix('_project')
    candidates = [cover_path(project_path), cover_path(project_path, False)]
    for directory in [project_path.parent, input_root / project_path.parent.name, input_root]:
        candidates.extend(directory / (name + '_cover' + suffix) for suffix in ('.png', '.jpg', '.jpeg', '.webp'))
    if audio_path:
        candidates.extend(audio_path.with_name(audio_path.stem + '_cover' + suffix) for suffix in ('.png', '.jpg', '.jpeg', '.webp'))
    source_url = source_identity(project_path, payload, input_root, audio_path).get('cover_url', '')
    for path in candidates:
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            return {**_asset(str(path), stat.st_mtime_ns, stat.st_size), 'source': 'custom' if path == candidates[0] else 'suno', 'source_url': source_url}
        except (ValueError, OSError):
            continue
    return {'data_url': '', 'width': 0, 'height': 0, 'source': 'none', 'source_url': source_url}
