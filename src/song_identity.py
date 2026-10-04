"""Song presentation is separate from alignment and director decisions."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SongIdentity(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal['motion-song-identity-v1'] = 'motion-song-identity-v1'
    title: str = Field(min_length=1, max_length=120)
    artist: str = Field(default='', max_length=80)
    style: Literal['editorial', 'minimal', 'none'] = 'editorial'
    show_intro: bool = True
    show_signature: bool = True
    show_section: bool = True
    show_outro: bool = True
    visual_theme: Literal["director", "editorial", "neon", "paper"] = "director"
    cover_mode: Literal["background", "none"] = "background"
    cover_x: float = Field(default=50, ge=0, le=100)
    cover_y: float = Field(default=50, ge=0, le=100)
    cover_zoom: float = Field(default=1, ge=1, le=2)

    @field_validator('title', 'artist', mode='before')
    @classmethod
    def clean_text(cls, value):
        return ' '.join(str(value or '').split())


def identity_path(project_path: Path) -> Path:
    name = project_path.stem.removesuffix('_alignment').removesuffix('_project')
    return project_path.with_name(name + '_motion_identity.json')


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def source_identity(project_path: Path, payload: dict, input_root: Path, audio_path: Path | None = None) -> dict:
    name = project_path.stem.removesuffix('_alignment').removesuffix('_project')
    candidates = [project_path.with_name(name + '_suno.json'),
                  input_root / project_path.parent.name / (name + '_suno.json'),
                  input_root / (name + '_suno.json')]
    if audio_path:
        candidates.append(audio_path.with_name(audio_path.stem + '_suno.json'))
    for path in candidates:
        meta = read_json(path)
        if not meta:
            continue
        artist = meta.get('artist') or meta.get('display_name') or meta.get('handle') or ''
        if str(artist).strip().lower() == 'unknown':
            artist = ''
        return {'title': str(meta.get('title') or payload.get('title') or name)[:120],
                'artist': str(artist)[:80], 'source': 'suno-cache', 'cover_url': meta.get('image_large_url') or meta.get('image_url') or ''}
    artist = payload.get('artist') or payload.get('author') or ''
    if str(artist).strip().lower() == 'unknown':
        artist = ''
    return {'title': str(payload.get('title') or name)[:120], 'artist': str(artist)[:80], 'source': 'project'}


def resolve_identity(project_path: Path, payload: dict, input_root: Path, audio_path: Path | None = None) -> dict:
    source = source_identity(project_path, payload, input_root, audio_path)
    saved = read_json(identity_path(project_path))
    try:
        identity = SongIdentity.model_validate(saved) if saved else SongIdentity(title=source['title'], artist=source['artist'])
    except ValueError:
        identity = SongIdentity(title=source['title'], artist=source['artist'])
    return {**identity.model_dump(), 'source_title': source['title'], 'source_artist': source['artist'], 'source': source['source']}
