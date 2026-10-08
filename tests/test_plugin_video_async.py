"""Plugin submission returns before slow inference; task failures remain queryable."""
import threading
import time
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src import local_editor, main, suno_fetch, lyric_engine


def wait_task(client, task_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = client.get('/api/lyric_video/task_status', params={'task_id': task_id}).json()
        if task['status'] in ('completed', 'failed'):
            return task
        time.sleep(0.01)
    raise AssertionError('worker did not finish')


def test_submit_returns_before_fetch_and_keeps_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(local_editor, '_get_scan_dir', lambda: tmp_path / 'output')
    entered, release = threading.Event(), threading.Event()

    def fetch(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(title='actual', artist='artist', raw_prompt='', lyrics='hello', raw_clip={})

    monkeypatch.setattr(suno_fetch, 'fetch_song', fetch)
    monkeypatch.setattr(suno_fetch, 'download_song', lambda song, folder, **kw: (folder / 'actual.mp3').write_bytes(b'audio'))

    def process(mp3, lyrics, output, background, config, on_progress):
        on_progress('aligning', 35, '词级对齐中')
        (output / 'actual_alignment.json').write_text('{}')

    def render(**kw):
        kw['progress_callback'](50, '渲染中')
        kw['output_path'].write_bytes(b'video')
        return {'elapsed_seconds': 1}

    monkeypatch.setattr(main, 'process_one', process)
    monkeypatch.setattr(lyric_engine, 'export_lyric_video', render)
    client = TestClient(local_editor.app)
    try:
        payload = {'song_id': 'fake', 'title': 'original', 'request_id': str(uuid.uuid4())}
        response = client.post('/api/plugin/export_video', data=payload)
        assert response.status_code == 200
        task_id = response.json()['task_id']
        assert entered.wait(1)
        # Retrying after a lost submission response uses the same worker.
        duplicate = client.post('/api/plugin/export_video', data=payload)
        assert duplicate.json()['task_id'] == task_id
        conflict = client.post('/api/plugin/export_video', data={**payload, 'title': 'other'})
        assert conflict.status_code == 409
        task = client.get('/api/lyric_video/task_status', params={'task_id': task_id}).json()
        assert task['status'] == 'running'
        assert task['phase'] == 'fetching'
        assert not release.is_set()  # HTTP returned while the worker is still blocked.
    finally:
        release.set()
    task = wait_task(client, task_id)
    assert task['status'] == 'completed', task
    assert task['progress'] == 100
    assert task['title'] == 'actual'
    assert 'download_url' in task['result']


def test_early_pipeline_failure_is_reported_on_task(monkeypatch, tmp_path):
    monkeypatch.setattr(local_editor, '_get_scan_dir', lambda: tmp_path / 'output')
    def fetch(*args, **kwargs):
        raise suno_fetch.SongNotPublishedError('not published')
    monkeypatch.setattr(suno_fetch, 'fetch_song', fetch)
    client = TestClient(local_editor.app)
    response = client.post('/api/plugin/export_video', data={'song_id': 'private'})
    assert response.status_code == 200
    task = wait_task(client, response.json()['task_id'])
    assert task['status'] == 'failed'
    assert task['error'] == 'not published'


def test_upload_survives_request_close_and_is_cleaned(monkeypatch, tmp_path):
    monkeypatch.setattr(local_editor, '_get_scan_dir', lambda: tmp_path / 'output')
    entered, release = threading.Event(), threading.Event()
    def transcode(cmd, **kwargs):
        from pathlib import Path
        entered.set()
        assert release.wait(3)
        assert Path(cmd[cmd.index('-i') + 1]).read_bytes() == b'captured audio'
        Path(cmd[-1]).write_bytes(b'mp3')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr('subprocess.run', transcode)
    monkeypatch.setattr('src.utils.get_ffmpeg_binary', lambda: 'ffmpeg')
    def process(*args, **kwargs):
        raise RuntimeError('alignment failed')
    monkeypatch.setattr(main, 'process_one', process)
    client = TestClient(local_editor.app)
    try:
        response = client.post('/api/plugin/export_video', data={'title': 'upload'},
                               files={'audio_file': ('../capture.mp3', b'captured audio', 'audio/mpeg')})
        task_id = response.json()['task_id']
        assert entered.wait(1)
        assert list((tmp_path / 'work' / 'plugin_uploads').glob('*'))
    finally:
        release.set()
    task = wait_task(client, task_id)
    assert task['error'] == 'alignment failed'
    deadline = time.monotonic() + 1
    while list((tmp_path / 'work' / 'plugin_uploads').glob('*')) and time.monotonic() < deadline:
        time.sleep(.01)
    assert not list((tmp_path / 'work' / 'plugin_uploads').glob('*'))
