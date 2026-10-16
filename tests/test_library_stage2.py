"""Stage two: reversible version removal, selective loading and private artwork."""
import asyncio
import json

from tests.test_song_library import sandbox as sandbox_fixture, seed, song
from tests.test_saas_isolation import headers
from src.models import Task, VersionTrash

sandbox = sandbox_fixture


def test_trash_keeps_video_access_and_restore_recovers_editor(sandbox):
    seed(sandbox)
    path=sandbox.storage.get_local_path('private.mp4');path.write_bytes(b'finished-video')
    alignment=sandbox.storage.get_local_path('alice-old.json');alignment.write_text('{"lines":[]}')
    access=sandbox.client.get('/api/exports/export-a/access',headers=headers()).json()['url']
    for _ in range(2):
        assert sandbox.client.post('/api/songs/versions/alice-old/trash',headers=headers()).status_code==200
    assert sandbox.client.get('/api/editor/tasks/alice-old/align',headers=headers()).status_code==404
    assert sandbox.client.get('/api/tasks/alice-old',headers=headers()).status_code==404
    assert sandbox.client.get(access).content==b'finished-video'
    group=next(s for s in sandbox.client.get('/api/songs',headers=headers()).json()['songs'] if s['current_task_id']=='alice-new')
    assert group['version_count']==2 and group['export_count']==1
    assert 'alice-old' in group['export_task_ids']
    trash=sandbox.client.get('/api/songs/trash/versions',headers=headers()).json()['versions']
    assert [v['id'] for v in trash]==['alice-old']
    assert sandbox.client.post('/api/songs/versions/alice-old/restore',headers=headers('bob')).status_code==404
    assert sandbox.client.get('/api/songs/trash/versions',headers=headers('bob')).json()['versions']==[]
    assert sandbox.client.post('/api/songs/versions/alice-old/restore',headers=headers()).status_code==200
    assert sandbox.client.get('/api/editor/tasks/alice-old/align',headers=headers()).status_code==200
    assert song(sandbox)['version_count']==3


def test_foreign_version_cannot_be_trashed_and_all_removed_song_disappears(sandbox):
    seed(sandbox)
    assert sandbox.client.post('/api/songs/versions/bob-old/trash',headers=headers()).status_code==404
    for name in ('old','new','bad'):
        assert sandbox.client.post('/api/songs/versions/alice-'+name+'/trash',headers=headers()).status_code==200
    assert sandbox.client.get('/api/songs',headers=headers()).json()['total']==1
    assert sandbox.client.get('/api/exports',headers=headers()).json()['total']==1


def test_presentation_reads_existing_source_and_custom_cover_privately(sandbox):
    seed(sandbox)
    from src.song_assets import source_keys
    from src.motion_cloud import task_prefix
    metadata,cover=source_keys('alice-old.mp3')
    path=sandbox.storage.get_local_path(metadata);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'artist':'Original artist'}))
    sandbox.storage.get_local_path(cover).write_bytes(b'original-cover')
    prefix=task_prefix('alice','alice-old')
    identity=sandbox.storage.get_local_path(prefix+'source_motion_identity.json');identity.parent.mkdir(parents=True,exist_ok=True)
    identity.write_text(json.dumps({'title':'Custom title','artist':'Custom artist'}))
    sandbox.storage.get_local_path(prefix+'source_motion_cover.jpg').write_bytes(b'custom-cover')
    response=sandbox.client.get('/api/songs/versions/alice-old/presentation',headers=headers())
    assert response.status_code==200
    data=response.json()
    assert data['artist']=='Custom artist' and data['title']=='Custom title'
    assert sandbox.client.get(data['cover_url']).content==b'custom-cover'
    assert sandbox.client.get('/api/songs/versions/alice-old/presentation',headers=headers('bob')).status_code==404
    assert sandbox.client.get(data['cover_url'].replace('alice-old/cover','bob-old/cover')).status_code==401
    assert sandbox.client.post('/api/songs/versions/alice-old/trash',headers=headers()).status_code==200
    assert sandbox.client.get(data['cover_url']).status_code==404


def test_selected_version_info_checks_only_its_own_tracks_not_all_alignments(sandbox,monkeypatch):
    seed(sandbox)
    async def forbidden(*args):raise AssertionError('Info must not read any alignment files')
    monkeypatch.setattr(sandbox.storage,'load',forbidden)
    response=sandbox.client.get('/api/editor/tasks/alice-old/info',headers=headers())
    assert response.status_code==200 and response.json()['task_id']=='alice-old'
    assert sandbox.client.get('/api/editor/tasks/alice-old/info',headers=headers('bob')).status_code==404


def test_trash_returns_pending_hold_once_and_late_worker_cannot_complete(sandbox,monkeypatch):
    from src import api_server,worker
    from tests.test_saas_isolation import submit
    monkeypatch.setattr(api_server,'_dispatch_task',lambda *a:'queued')
    task=submit(sandbox,monkeypatch,'suno').json()['task_id']
    for _ in range(2):assert sandbox.client.post('/api/songs/versions/'+task+'/trash',headers=headers()).status_code==200
    data=sandbox.client.get('/api/credits',headers=headers()).json()
    assert data['available']==5 and data['reserved']==0
    worker._update_task_status(task,status='completed')
    async def check():
        async with sandbox.sessions() as db:
            assert (await db.get(Task,task)).status.value=='failed'
            assert await db.get(VersionTrash,task)
    asyncio.run(check())
    assert sandbox.client.post('/api/songs/versions/'+task+'/restore',headers=headers()).status_code==200
    assert sandbox.client.get('/api/tasks/'+task,headers=headers()).json()['status']=='failed'
