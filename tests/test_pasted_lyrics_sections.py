"""Section markers in pasted lyrics are metadata, not spoken lyrics."""
import pytest

from src.preprocessor import preprocess_lyrics
from src.align import stablets_adapter
from src.storyboard_schema import AlignmentResult
from src.suno_fetch import _clean_lyrics


def test_pasted_headings_never_reach_interlude_alignment(tmp_path, monkeypatch):
    path = tmp_path / 'lyrics.txt'
    path.write_text('[Intro — Spoken, playful]\nZero. S-O-E\n\n【副歌】\n这就是我', encoding='utf-8')
    lines = preprocess_lyrics(path)
    assert [line.text for line in lines if line.is_annotation] == ['[Intro — Spoken, playful]', '【副歌】']
    observed = []
    from src.align import interlude_guard
    monkeypatch.setattr(stablets_adapter, 'get_stablets_model', lambda **kw: object())
    def fake_align(**kwargs):
        observed.extend(line.text for line in kwargs['lyrics'])
        return AlignmentResult(lines=[])
    monkeypatch.setattr(interlude_guard, 'align_with_interlude_guard', fake_align)
    stablets_adapter.align_lyrics_stablets('unused.wav', lines)
    assert observed == ['Zero. S-O-E', '这就是我']


def test_only_headings_fail_before_loading_the_model(tmp_path, monkeypatch):
    path = tmp_path / 'lyrics.txt'
    path.write_text('[Intro]\n【副歌】', encoding='utf-8')
    monkeypatch.setattr(stablets_adapter, 'get_stablets_model', lambda **kw: pytest.fail('must not load model'))
    with pytest.raises(ValueError, match='No singable lyrics'):
        stablets_adapter.align_lyrics_stablets('unused.wav', preprocess_lyrics(path))


def test_pasted_and_suno_lyrics_share_cleaning_and_stanza_boundaries(tmp_path):
    raw = '[Intro — Spoken, playful]\nHello [soft] world\n【主歌】\n镜子里的我（低声）\n[Chorus]\n回家了'
    pasted, suno = tmp_path / 'pasted.txt', tmp_path / 'suno.txt'
    pasted.write_text(raw, encoding='utf-8')
    suno.write_text(_clean_lyrics(raw), encoding='utf-8')
    def sung(path):
        return [(line.text, line.paragraph) for line in preprocess_lyrics(path) if not line.is_annotation]
    assert sung(pasted) == sung(suno) == [('Hello  world', 0), ('镜子里的我', 1), ('回家了', 2)]
