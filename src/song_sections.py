"""Bind source section headings to current lyrics without changing alignment."""
from __future__ import annotations

import unicodedata


def _text(value: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum())


def bind_source_sections(payload: dict, source: list[dict]) -> bool:
    """Require the complete lyric sequence, allowing punctuation/line wrapping edits.

    Count-based assignment shifts every later heading after a merged/missing line.
    Use character spans instead; do not attach source labels to changed lyrics or
    a single aligned line that crosses two source sections.
    """
    lines = payload.get('lines') or []
    source_texts = [''.join(_text(t) for t in s.get('lyric_texts', [])) for s in source]
    line_texts = [_text(line.get('text', '')) for line in lines]
    if not source or not lines or not all(line_texts) or ''.join(source_texts) != ''.join(line_texts):
        return False
    spans, cursor = [], 0
    for text in source_texts:
        spans.append((cursor, cursor + len(text)))
        cursor += len(text)
    members = [[] for _ in source]
    cursor = 0
    for index, text in enumerate(line_texts):
        end = cursor + len(text)
        section = next((i for i, (start, stop) in enumerate(spans) if start <= cursor < end <= stop), None)
        if section is None:
            return False
        members[section].append(index)
        cursor = end
    duration = max(float(payload.get('duration') or 0), float((payload.get('analysis') or {}).get('duration') or 0),
                   float(lines[-1]['end']))
    sections = []
    for i, (section, indices) in enumerate(zip(source, members)):
        previous = next((group[-1] for group in reversed(members[:i]) if group), None)
        following = next((group[0] for group in members[i + 1:] if group), None)
        start = float(lines[indices[0]]['start']) if indices else (float(lines[previous]['end']) if previous is not None else 0)
        # A section includes its lyric pauses, until the next section starts.
        end = float(lines[following]['start']) if following is not None else duration
        if i + 1 < len(source) and not members[i + 1] and indices:
            end = float(lines[indices[-1]]['end'])
        if end <= start:
            continue
        name = section['name']
        for index in indices:
            lines[index]['section'] = name
        sections.append({key: section.get(key, '') for key in ('name', 'label', 'style')} |
                        {'start': start, 'end': end, 'line_indices': indices})
    payload['sections'] = sections
    if isinstance(payload.get('analysis'), dict):
        payload['analysis']['sections'] = sections
    return True
