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


def test_identity_particles_mode_defaults_and_override():
    from src.song_identity import SongIdentity
    ident = SongIdentity(title="测试", artist="歌手")
    assert ident.particles_mode == "particles"
    assert ident.ambient_particles is True
    assert ident.particles_speed == 0.5
    assert ident.particles_darken == 0.4

    ident_off = SongIdentity(title="测试", artist="歌手", particles_mode="none", ambient_particles=False, particles_speed=0.2, particles_darken=0.8)
    assert ident_off.particles_mode == "none"
    assert ident_off.ambient_particles is False
    assert ident_off.particles_speed == 0.2
    assert ident_off.particles_darken == 0.8


def test_identity_supports_holiday_themes_and_snow_particles():
    from src.song_identity import SongIdentity
    ident = SongIdentity(title="Jingle Bells", artist="Studio", visual_theme="christmas2026", particles_mode="snow")
    assert ident.visual_theme == "christmas2026"
    assert ident.particles_mode == "snow"

    ident_blank = SongIdentity(title="Track", visual_theme="   ", particles_mode="  ")
    assert ident_blank.visual_theme == "director"
    assert ident_blank.particles_mode == "particles"
