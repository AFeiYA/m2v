import json
from src.song_identity import resolve_identity, identity_path


def test_identity_missing_cache_and_corrupt_override_use_project_metadata(tmp_path):
    path = tmp_path / 'song_alignment.json'
    source = {'title': '自己的歌曲', 'artist': 'unknown'}
    result = resolve_identity(path, source, tmp_path / 'input')
    assert result['title'] == '自己的歌曲'
    assert result['artist'] == ''
    identity_path(path).write_text('{broken json')
    assert resolve_identity(path, source, tmp_path / 'input')['title'] == '自己的歌曲'


def test_identity_reads_suno_import_cache_and_preserves_user_override(tmp_path):
    path = tmp_path / 'output' / 'song' / 'song_alignment.json'
    path.parent.mkdir(parents=True)
    cache = tmp_path / 'input' / 'song' / 'song_suno.json'
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({'title': 'Suno song', 'display_name': 'Suno artist'}))
    identity = resolve_identity(path, {'title': 'filename'}, tmp_path / 'input')
    assert identity['title'] == 'Suno song'
    assert identity['artist'] == 'Suno artist'
    saved = {k: v for k, v in identity.items() if not k.startswith('source')}
    saved.update(title='New title', artist='')
    identity_path(path).write_text(json.dumps(saved))
    loaded = resolve_identity(path, {'title': 'filename'}, tmp_path / 'input')
    assert loaded['title'] == 'New title'
    assert loaded['artist'] == ''
    assert loaded['source_artist'] == 'Suno artist'
