"""Audio-only API reuses Suno MP4 fallback, without executing AI pipeline."""
import shutil
import subprocess
import time
from types import SimpleNamespace
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest
from fastapi.testclient import TestClient
from src import local_editor, suno_fetch, main


def wait_task(client, task_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        task = client.get('/api/lyric_video/task_status', params={'task_id': task_id}).json()
        if task['status'] in ('completed', 'failed'):
            return task
        time.sleep(.02)
    raise AssertionError('audio task did not finish')


@pytest.fixture
def media_server(tmp_path):
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/source.mp4'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_mp4_fallback_reuses_download_function_and_never_aligns(monkeypatch, tmp_path, media_server):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('FFmpeg required for MP4 audio extraction')
    video = tmp_path / 'source.mp4'
    subprocess.run([ffmpeg, '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                    '-c:a', 'aac', str(video)], check=True, capture_output=True)
    song = suno_fetch.SunoSong(id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', title='track', artist='',
                              audio_url='https://cdn1.suno.ai/denied.mp3', video_url=media_server,
                              lyrics='', raw_prompt='', tags='', duration=1)
    monkeypatch.setattr(local_editor, '_get_scan_dir', lambda: tmp_path / 'output')
    monkeypatch.setattr(suno_fetch, 'fetch_song', lambda *a, **kw: song)
    monkeypatch.setattr(suno_fetch.requests, 'get', lambda *a, **kw: SimpleNamespace(status_code=403))
    monkeypatch.setattr(main, 'process_one', lambda *a, **kw: pytest.fail('audio download must not run AI'))
    # Exercise the real download_song -> FFmpeg MP4 fallback, rather than mocking it.
    client = TestClient(local_editor.app)
    response = client.post('/api/plugin/export_audio', data={'song_id': song.id, 'title': 'track'})
    assert response.status_code == 200
    task = wait_task(client, response.json()['task_id'])
    assert task['status'] == 'completed', task
    output = tmp_path / 'output' / '_plugin_audio' / task['task_id'] / 'track.mp3'
    assert output.read_bytes()[:3] == b'ID3'
    assert task['result']['filename'] == 'track.mp3'
    downloaded = client.get(task['result']['download_url'])
    assert downloaded.status_code == 200
    assert downloaded.content == output.read_bytes()
    assert not list(output.parent.glob('source_*'))


def test_audio_failure_and_invalid_id_are_explicit(monkeypatch, tmp_path):
    monkeypatch.setattr(local_editor, '_get_scan_dir', lambda: tmp_path / 'output')
    monkeypatch.setattr(suno_fetch, 'download_song', lambda *a, **kw: (None, None, None, None))
    client = TestClient(local_editor.app)
    assert client.post('/api/plugin/export_audio', data={'song_id': '../escape'}).status_code == 400
    response = client.post('/api/plugin/export_audio', data={'song_id': 'shortlink'})
    task = wait_task(client, response.json()['task_id'])
    assert task['status'] == 'failed'
    assert '音轨' in task['error']
