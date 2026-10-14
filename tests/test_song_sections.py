"""Source music sections survive directions, line wrapping and retiming."""
import copy

from src.song_sections import bind_source_sections
from src.suno_fetch import parse_suno_prompt_sections, enrich_alignment_sections


def test_performance_tags_do_not_replace_pre_chorus():
    prompt = '[Verse 1]\n[Soft, conversational male vocal]\n走过雨天\n[Pre-Chorus]\n[Build-up, emotive harmonica melody]\n终于知道\n[Chorus]\n[Full acoustic arrangement]\n[Vocal]\n回家了\n[Outro]\n[Spoken softly] 我回来了'
    sections = parse_suno_prompt_sections(prompt)
    assert [s['name'] for s in sections] == ['Verse 1', 'Pre-Chorus', 'Chorus', 'Outro']
    assert sections[1]['lyric_texts'] == ['终于知道']
    assert sections[1]['style'] == 'Build-up, emotive harmonica melody'
    assert sections[-1]['lyric_texts'] == ['我回来了']


def test_text_spans_support_merged_lines_and_repeated_choruses_without_retiming(tmp_path):
    source = parse_suno_prompt_sections('[Intro]\n[Verse 1]\n第一行\n第二行\n[Pre-Chorus]\n蓄势\n[Chorus]\n回家\n[Chorus]\n回家\n[Outro]')
    payload = {'duration': 15, 'lines': [
        {'text': text, 'start': start, 'end': start + 1, 'words': []}
        for text, start in [('第一行，第二行', 2), ('蓄势', 5), ('回家', 8), ('回家', 11)]], 'analysis': {}}
    before = copy.deepcopy(payload)
    assert bind_source_sections(payload, source)
    assert [l['section'] for l in payload['lines']] == ['Verse 1', 'Pre-Chorus', 'Chorus', 'Chorus 2']
    assert [(s['name'], s['start'], s['end']) for s in payload['sections']] == [
        ('Intro', 0, 2), ('Verse 1', 2, 5), ('Pre-Chorus', 5, 8), ('Chorus', 8, 11), ('Chorus 2', 11, 12), ('Outro', 12, 15)]
    for old, new in zip(before['lines'], payload['lines']):
        assert {k:v for k,v in new.items() if k != 'section'} == old
    import json
    path = tmp_path / 'alignment.json'
    path.write_text(json.dumps(before))
    result = enrich_alignment_sections(path, '[Verse 1]\n第一行\n第二行\n[Pre-Chorus]\n蓄势\n[Chorus]\n回家\n[Chorus]\n回家')
    assert result.lines[1].section == 'Pre-Chorus'


def test_changed_lyrics_or_cross_section_merge_is_not_guessed():
    source = parse_suno_prompt_sections('[Verse]\n甲乙\n[Pre-Chorus]\n丙丁')
    for lines in ([{'text':'甲乙丙戊','start':0,'end':1}], [{'text':'甲乙丙丁','start':0,'end':1}]):
        payload = {'lines': lines}
        before = copy.deepcopy(payload)
        assert bind_source_sections(payload, source) is False
        assert payload == before
