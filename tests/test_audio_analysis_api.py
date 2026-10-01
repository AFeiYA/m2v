"""Analysis is independent of CTC and preserves lyric edits made while running."""
import json
import threading
import time

from fastapi.testclient import TestClient
from src.local_editor import app
from src.storyboard_schema import SongAnalysis


def test_analysis_job_reuses_active_job_and_preserves_edits(tmp_path, monkeypatch):
    import src.audio_analyzer as analyzer
    from src.local_editor import _audio_analysis_tasks
    output = tmp_path / 'output'
    song = output / 'song'
    song.mkdir(parents=True)
    audio = song / 'song.wav'
    audio.write_bytes(b'fixture')
    path = song / 'song_alignment.json'
    original = {'lines': [{'text': 'old', 'start': 0, 'end': 1}], 'custom_field': 'retain', 'sections': []}
    path.write_text(json.dumps(original))
    monkeypatch.setattr(app.state, 'scan_dir', output, raising=False)
    entered, release = threading.Event(), threading.Event()
    def compute(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return SongAnalysis(duration=8, bpm=0, metadata={'cache_hit': False})
    monkeypatch.setattr(analyzer, 'cached_audio_analysis', compute)
    with TestClient(app) as client:
        task = client.post('/api/audio/analyze', json={'json_path': str(path)}).json()
        assert entered.wait(5)
        duplicate = client.post('/api/audio/analyze', json={'json_path': str(path)}).json()
        assert duplicate['task_id'] == task['task_id']
        edited = {**original, 'lines': [{'text': 'edited', 'start': 0, 'end': 1}]}
        path.write_text(json.dumps(edited))
        release.set()
        for _ in range(100):
            result = client.get('/api/audio/analyze/' + task['task_id']).json()
            if result['status'] != 'running': break
            time.sleep(.02)
        assert result['status'] == 'done', result
        saved = json.loads(path.read_text())
        assert saved['lines'] == edited['lines']
        assert saved['custom_field'] == 'retain'
        assert saved['analysis']['duration'] == 8
        assert saved['audio_path'] == str(audio)
        assert client.get('/api/audio/analyze/missing').status_code == 404
    _audio_analysis_tasks.pop(task['task_id'], None)


def test_analysis_failure_is_visible_and_does_not_touch_project(tmp_path, monkeypatch):
    import src.audio_analyzer as analyzer
    song = tmp_path / 'output' / 'song'
    song.mkdir(parents=True)
    path = song / 'song_alignment.json'
    path.write_text('{"lines": []}')
    monkeypatch.setattr(app.state, 'scan_dir', song.parent, raising=False)
    with TestClient(app) as client:
        assert client.post('/api/audio/analyze', json={'json_path': str(path)}).status_code == 404
        (song / 'song.wav').write_bytes(b'corrupt audio')
        def fail(*args, **kwargs): raise ValueError('invalid audio')
        monkeypatch.setattr(analyzer, 'cached_audio_analysis', fail)
        task = client.post('/api/audio/analyze', json={'json_path': str(path)}).json()
        for _ in range(100):
            result = client.get('/api/audio/analyze/' + task['task_id']).json()
            if result['status'] != 'running': break
            time.sleep(.02)
        assert result['status'] == 'error' and 'invalid audio' in result['error']
        assert path.read_text() == '{"lines": []}'
