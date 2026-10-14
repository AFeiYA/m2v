"""Source metadata is portable and cannot replace user artwork on failure."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from src import song_assets
from src.storage import LocalStorage


def test_failed_artwork_refresh_preserves_previous_cover_and_minimal_metadata(tmp_path, monkeypatch):
    storage = LocalStorage(tmp_path)
    audio_key = 'uploads/alice/task/source.mp3'
    metadata_key, cover_key = song_assets.source_keys(audio_key)
    previous = storage.get_local_path(cover_key)
    previous.parent.mkdir(parents=True, exist_ok=True)
    previous.write_bytes(b'previous-cover')
    def unavailable(url):
        raise ValueError('image unavailable')
    monkeypatch.setattr(song_assets, 'download_artwork', unavailable)
    song = SimpleNamespace(id='song', title='A song', artist='An artist',
        raw_clip={'image_url':'https://cdn1.suno.ai/cover.jpeg', 'cookies':'private'})
    result = asyncio.run(song_assets.save_source(storage, audio_key, song))
    assert result['warning']
    assert previous.read_bytes() == b'previous-cover'
    metadata = json.loads(storage.get_local_path(metadata_key).read_text())
    assert metadata['artist'] == 'An artist'
    assert metadata['title'] == 'A song'
    assert 'cookies' not in metadata


@pytest.mark.parametrize('url', [
    'http://cdn1.suno.ai/a.jpg', 'https://localhost/a.jpg',
    'https://cdn1.suno.ai.evil.example/a.jpg', 'https://cdn1.suno.ai:8888/a.jpg',
    'https://user:password@cdn1.suno.ai/a.jpg',
])
def test_artwork_url_is_rejected_before_any_network_request(url, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('untrusted artwork URL must never be requested')
    monkeypatch.setattr(song_assets.requests, 'get', forbidden)
    with pytest.raises(ValueError):
        song_assets.download_artwork(url)
