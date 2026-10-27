"""Audio-only downloads must use song identity, independently of mutable lyrics."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src import local_editor, suno_fetch
from src.suno_audio_cache import provenance_path, remember_audio, source_directory, verified_audio

A = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'


def song(identity=A, lyrics='Original lyrics', title='Same title'):
    return suno_fetch.SunoSong(id=identity, title=title, artist='Artist',
        audio_url=f'https://example.invalid/{identity}.mp3', lyrics=lyrics,
        raw_prompt=lyrics, tags='', duration=10,
        raw_clip={'id':identity, 'title':title, 'metadata':{'prompt':lyrics}})


@pytest.fixture
def offline(monkeypatch, tmp_path):
    downloads = []
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    def get(url, **kwargs):
        downloads.append(url)
        return SimpleNamespace(status_code=200, iter_content=lambda chunk_size: [b'audio:' + url.encode()])
    monkeypatch.setattr(suno_fetch.requests, 'get', get)
    monkeypatch.setattr(suno_fetch, 'is_valid_audio_file', lambda p: p.is_file() and p.read_bytes().startswith(b'audio:'))
    return downloads


def test_audio_only_endpoint_separates_same_titles_and_resolves_each_url_once(monkeypatch, tmp_path, offline):
    monkeypatch.setattr(local_editor, '_get_scan_dir', lambda: tmp_path / 'output')
    urls = {'https://suno.com/s/short-A':song(A), 'https://suno.com/s/short-B':song(B)}
    resolved = []
    def fetch(url):
        resolved.append(url)
        return urls[url]
    monkeypatch.setattr(suno_fetch, 'fetch_song', fetch)
    client = TestClient(local_editor.app)
    first = client.get('/api/suno/download_mp3', params={'url':next(iter(urls))})
    second = client.get('/api/suno/download_mp3', params={'url':'https://suno.com/s/short-B'})
    assert first.status_code == second.status_code == 200
    assert first.content != second.content
    assert resolved == list(urls)
    assert len(offline) == 2
    for identity in (A, B):
        folder = source_directory(tmp_path / 'input', identity)
        assert verified_audio(folder / 'Same title.mp3', identity)
        assert json.loads((folder / 'Same title_suno.json').read_text())['id'] == identity
    assert 'Same%20title.mp3' in first.headers['content-disposition']


def test_same_uuid_short_and_long_urls_reuse_audio_and_only_update_changed_lyrics(monkeypatch, tmp_path, offline):
    monkeypatch.setattr(local_editor, '_get_scan_dir', lambda: tmp_path / 'output')
    current = song()
    monkeypatch.setattr(suno_fetch, 'fetch_song', lambda url: current)
    client = TestClient(local_editor.app)
    first = client.get('/api/suno/download_mp3', params={'url':'https://suno.com/s/short-A'})
    folder = source_directory(tmp_path / 'input', A)
    audio = folder / 'Same title.mp3'
    lyrics = folder / 'Same title.txt'
    metadata = folder / 'Same title_suno.json'
    before = {p:p.stat().st_mtime_ns for p in (audio, lyrics, metadata, provenance_path(audio))}
    second = client.get('/api/suno/download_mp3', params={'url':f'https://suno.com/song/{A}'})
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert {p:p.stat().st_mtime_ns for p in before} == before
    current = song(lyrics='Corrected lyrics')
    third = client.get('/api/suno/download_mp3', params={'url':f'https://suno.com/song/{A}'})
    assert third.status_code == 200
    assert third.content == first.content
    assert lyrics.read_text() == 'Corrected lyrics'
    assert json.loads(metadata.read_text())['metadata']['prompt'] == 'Corrected lyrics'
    assert audio.stat().st_mtime_ns == before[audio]
    assert len(offline) == 1


def test_old_metadata_cannot_vouch_for_unverified_same_title_audio(tmp_path, offline):
    current = song()
    legacy = tmp_path / 'Same title.mp3'
    legacy.write_bytes(b'audio:wrong song, even though metadata was overwritten')
    (tmp_path / 'Same title_suno.json').write_text(json.dumps(current.raw_clip))
    audio, *_ = suno_fetch.download_song(current, tmp_path, allow_local_fallback=False)
    assert audio.read_bytes() == b'audio:' + current.audio_url.encode()
    assert len(offline) == 1
    assert verified_audio(audio, A)


def test_failed_download_never_adopts_title_only_audio_or_erases_it(monkeypatch, tmp_path, offline):
    root = tmp_path / 'input'
    root.mkdir()
    legacy = root / 'Same title.mp3'
    legacy.write_bytes(b'audio:another song')
    downloads = tmp_path / 'Downloads'
    downloads.mkdir()
    (downloads / 'Suno_Same title_final.mp3').write_bytes(b'audio:also another song')
    monkeypatch.setattr(suno_fetch.requests, 'get', lambda *a, **kw: SimpleNamespace(status_code=403))
    audio, *_ = suno_fetch.download_song(song(), root)
    assert audio is None
    assert legacy.read_bytes() == b'audio:another song'
    assert not provenance_path(legacy).exists()
    assert not list(root.glob('.m2v-download-*'))


@pytest.mark.parametrize('damage', ['wrong-uuid', 'same-size-tamper', 'malformed-record'])
def test_invalid_provenance_or_changed_audio_forces_download(tmp_path, offline, damage):
    current = song()
    audio, *_ = suno_fetch.download_song(current, tmp_path, allow_local_fallback=False)
    expected = audio.read_bytes()
    if damage == 'wrong-uuid':
        remember_audio(audio, B)
    elif damage == 'same-size-tamper':
        audio.write_bytes(b'audio:' + b'x' * (len(expected) - 6))
    else:
        provenance_path(audio).write_text('{broken')
    updated, *_ = suno_fetch.download_song(current, tmp_path, allow_local_fallback=False)
    assert updated.read_bytes() == expected
    assert len(offline) == 2
    assert verified_audio(updated, A)


def test_renaming_same_uuid_reuses_audio_but_updates_presentation(tmp_path, offline):
    original, *_ = suno_fetch.download_song(song(), tmp_path, allow_local_fallback=False)
    renamed, lyrics, metadata, _ = suno_fetch.download_song(song(title='New title'), tmp_path, allow_local_fallback=False)
    assert renamed == original
    assert lyrics.name == 'New title.txt'
    assert json.loads(metadata.read_text())['title'] == 'New title'
    assert len(offline) == 1


def test_interrupted_download_cannot_publish_partial_audio(monkeypatch, tmp_path, offline):
    def chunks(chunk_size):
        yield b'audio:partial'
        raise OSError('Disconnected')
    monkeypatch.setattr(suno_fetch.requests, 'get', lambda *a, **kw: SimpleNamespace(status_code=200, iter_content=chunks))
    audio, *_ = suno_fetch.download_song(song(), tmp_path, allow_local_fallback=False)
    assert audio is None
    assert not (tmp_path / 'Same title.mp3').exists()
    assert not list(tmp_path.glob('*.source.json'))
    assert not list(tmp_path.glob('.m2v-download-*'))


@pytest.mark.parametrize('succeeds', [True, False])
def test_audio_only_conversion_validates_output_before_publishing(monkeypatch, tmp_path, offline, succeeds):
    import subprocess
    from src import utils
    current = song()
    folder = source_directory(tmp_path / 'input', A)
    folder.mkdir(parents=True)
    wav = folder / 'Same title.wav'
    wav.write_bytes(b'audio:verified wav')
    remember_audio(wav, A)
    mp3 = folder / 'Same title.mp3'
    mp3.write_bytes(b'audio:unverified old conversion')
    monkeypatch.setattr(local_editor, '_get_scan_dir', lambda: tmp_path / 'output')
    monkeypatch.setattr(suno_fetch, 'fetch_song', lambda url: current)
    monkeypatch.setattr(utils, 'is_valid_audio_file', lambda p: p.is_file() and p.read_bytes().startswith(b'audio:'))
    monkeypatch.setattr(utils, 'get_ffmpeg_binary', lambda: 'ffmpeg')
    def convert(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b'audio:converted' if succeeds else b'partial')
        return SimpleNamespace(returncode=0 if succeeds else 1)
    monkeypatch.setattr(subprocess, 'run', convert)
    response = TestClient(local_editor.app).get('/api/suno/download_mp3', params={'url':f'https://suno.com/song/{A}'})
    if succeeds:
        assert response.status_code == 200
        assert response.content == b'audio:converted'
        assert verified_audio(mp3, A)
    else:
        assert response.status_code == 502
        assert mp3.read_bytes() == b'audio:unverified old conversion'
        assert not verified_audio(mp3, A)
    assert not list(folder.glob('.m2v-download-*'))
    assert offline == []
