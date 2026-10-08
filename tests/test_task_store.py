import json
import time

from src.task_store import TaskStore
from fastapi.testclient import TestClient


def test_finished_task_survives_restart_and_updates_are_atomic(tmp_path):
    store = TaskStore(tmp_path)
    store['lyric_a'] = {'status': 'running'}
    store['lyric_a'].update(status='completed', result={'download_url': '/result.mp4'})
    restored = TaskStore(tmp_path).get('lyric_a')
    assert restored['status'] == 'completed'
    assert restored['result']['download_url'] == '/result.mp4'
    assert not list(tmp_path.glob('*.tmp'))
    assert json.loads((tmp_path / 'lyric_a.json').read_text())['status'] == 'completed'


def test_restart_reports_interruption_without_replaying_work(tmp_path):
    store = TaskStore(tmp_path)
    store['lyric_a'] = {'status': 'running', 'progress': 60}
    task = TaskStore(tmp_path).get('lyric_a')
    assert task['status'] == 'interrupted'
    assert task['progress'] == 60
    assert 'not automatically regenerated' in task['message']


def test_expired_and_invalid_task_ids_do_not_load(tmp_path):
    store = TaskStore(tmp_path)
    store['old'] = {'status': 'completed', 'created_at': time.time() - 8 * 86400}
    assert TaskStore(tmp_path).get('old') is None
    assert not (tmp_path / 'old.json').exists()
    assert store.get('../private') is None


def test_api_can_read_completed_journal_after_server_restart(monkeypatch, tmp_path):
    from src import local_editor
    original = TaskStore(tmp_path)
    original['lyric_finished'] = {'status': 'completed', 'result': {'download_url': '/saved.mp4'}}
    original['lyric_running'] = {'status': 'running'}
    monkeypatch.setattr(local_editor, '_lyric_video_tasks', TaskStore(tmp_path))
    client = TestClient(local_editor.app)
    completed = client.get('/api/lyric_video/task_status', params={'task_id': 'lyric_finished'})
    assert completed.json()['result']['download_url'] == '/saved.mp4'
    interrupted = client.get('/api/lyric_video/task_status', params={'task_id': 'lyric_running'})
    assert interrupted.json()['status'] == 'interrupted'
    assert client.get('/privacy/extension').status_code == 200
