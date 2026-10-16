"""Song aggregation, preferences and exports use only the signed-in owner's data."""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from tests.test_saas_isolation import sandbox as sandbox_fixture, headers
from src.models import Task, TaskStatus, User, VideoExport

sandbox = sandbox_fixture


def seed(sandbox):
    async def run():
        async with sandbox.sessions() as db:
            base = datetime(2026, 1, 1, tzinfo=timezone.utc)
            for uid in ('alice', 'bob'):
                for index, options in enumerate([
                    ('old', 'Original title', TaskStatus.COMPLETED, {'suno_song_id':'ABC'}, 'https://suno.com/s/short'),
                    ('new', 'Changed title', TaskStatus.COMPLETED, {}, 'https://suno.com/song/abc?sh=anything'),
                    ('bad', 'Changed title', TaskStatus.FAILED, {'suno_song_id':'abc'}, None),
                    ('other', 'Original title', TaskStatus.COMPLETED, {'suno_song_id':'different'}, None),
                ]):
                    name, title, state, config, url = options
                    task_id = uid+'-'+name
                    db.add(Task(id=task_id, user_id=uid, title=title, song_title=title,
                        status=state, config_snapshot=config, suno_url=url,
                        input_mp3_key=task_id+'.mp3', input_lyrics_key=task_id+'.txt',
                        alignment_json_key=None if state == TaskStatus.FAILED else task_id+'.json',
                        created_at=base+timedelta(days=index), updated_at=base+timedelta(days=index)))
            await db.flush()
            db.add(VideoExport(id='export-a', user_id='alice', task_id='alice-old', title='video', storage_key='private.mp4'))
            db.add(VideoExport(id='export-b', user_id='bob', task_id='bob-old', title='private', storage_key='bob.mp4'))
            await db.commit()
    asyncio.run(run())


def song(sandbox):
    return next(s for s in sandbox.client.get('/api/songs',headers=headers()).json()['songs'] if s['version_count'] == 3)


def test_library_groups_uuid_versions_but_not_identical_titles_and_reads_no_media(sandbox, monkeypatch):
    seed(sandbox)
    async def no_media(*args):
        raise AssertionError('Library must not fetch alignment, audio or cover files')
    monkeypatch.setattr(sandbox.storage, 'load', no_media)
    monkeypatch.setattr(sandbox.storage, 'exists', no_media)
    data = sandbox.client.get('/api/songs',headers=headers()).json()
    assert data['total'] == 2 and data['total_songs'] == 2
    group = song(sandbox)
    assert group['current_task_id'] == 'alice-new'  # Failed import cannot replace editable work.
    assert group['latest_task_id'] == 'alice-bad' and group['status'] == 'failed'
    assert group['export_count'] == 1 and len(group['versions']) == 3
    assert 'input_mp3_key' not in str(data) and 'private.mp4' not in str(data)
    assert sandbox.client.get('/api/songs').status_code == 401


def test_preferences_persist_and_never_touch_other_users_or_credit_balance(sandbox):
    seed(sandbox)
    group = song(sandbox)
    endpoint = '/api/songs/'+group['id']
    assert sandbox.client.patch(endpoint,headers=headers('bob'),json={'starred':True}).status_code == 404
    assert sandbox.client.patch(endpoint,headers=headers(),json={'preferred_task_id':'bob-old'}).status_code == 409
    assert sandbox.client.patch(endpoint,headers=headers(),json={'preferred_task_id':'alice-bad'}).status_code == 409
    for _ in range(2):
        assert sandbox.client.patch(endpoint,headers=headers(),json={'starred':True,'preferred_task_id':'alice-old'}).status_code == 200
    assert song(sandbox)['current_task_id'] == 'alice-old'
    starred = sandbox.client.get('/api/songs?view=starred',headers=headers()).json()
    assert starred['total'] == 1
    assert sandbox.client.patch(endpoint,headers=headers(),json={'archived':True}).status_code == 200
    assert sandbox.client.get('/api/songs',headers=headers()).json()['total'] == 1
    assert sandbox.client.get('/api/songs?view=archived',headers=headers()).json()['total'] == 1
    assert sandbox.client.get('/api/songs?view=starred',headers=headers()).json()['total'] == 0
    assert sandbox.client.get('/api/songs',headers=headers('bob')).json()['total'] == 2
    async def check():
        async with sandbox.sessions() as db:
            assert (await db.get(User,'alice')).credits == 5
            await db.execute(delete(VideoExport).where(VideoExport.task_id == 'alice-old'))
            await db.execute(delete(Task).where(Task.id == 'alice-old'))
            await db.commit()
    asyncio.run(check())
    # A stale current-version preference falls back without losing the song.
    archived = sandbox.client.get('/api/songs?view=archived',headers=headers()).json()['songs'][0]
    assert archived['current_task_id'] == 'alice-new'
    assert sandbox.client.patch(endpoint,headers=headers(),json={'archived':False,'preferred_task_id':None}).status_code == 200
    restored = sandbox.client.get('/api/songs?view=starred',headers=headers()).json()['songs'][0]
    assert restored['version_count'] == 2 and restored['current_task_id'] == 'alice-new'


def test_search_matches_previous_titles_and_pagination_happens_after_grouping(sandbox):
    seed(sandbox)
    data = sandbox.client.get('/api/songs?q=ORIGINAL&sort=title&page_size=1',headers=headers()).json()
    assert data['total'] == 2 and len(data['songs']) == 1
    next_page = sandbox.client.get('/api/songs?q=original&sort=title&page_size=1&page=2',headers=headers()).json()
    assert len(next_page['songs']) == 1 and next_page['songs'][0]['id'] != data['songs'][0]['id']
    assert sandbox.client.get('/api/songs?view=invalid',headers=headers()).status_code == 422
    assert sandbox.client.patch('/api/songs/'+song(sandbox)['id'],headers=headers(),json={'archived':None}).status_code == 422


def test_library_can_reach_songs_beyond_old_fifty_task_limit(sandbox):
    async def many():
        async with sandbox.sessions() as db:
            for i in range(61):
                db.add(Task(id=f'task-{i}', user_id='alice', title=f'Song {i:02}',
                            input_mp3_key=f'{i}.mp3', input_lyrics_key=f'{i}.txt'))
            await db.commit()
    asyncio.run(many())
    page = sandbox.client.get('/api/songs?sort=title&page=6&page_size=12',headers=headers()).json()
    assert page['total'] == 61 and len(page['songs']) == 1
    assert page['songs'][0]['title'] == 'Song 60'
    assert page['active_count'] == 61


def test_song_video_filter_keeps_export_ownership(sandbox):
    seed(sandbox)
    assert sandbox.client.get('/api/exports?task_ids=alice-old',headers=headers()).json()['total'] == 1
    assert sandbox.client.get('/api/exports?task_ids=bob-old',headers=headers()).json()['total'] == 0
    assert sandbox.client.get('/api/exports?task_ids=alice-old,bob-old',headers=headers()).json()['total'] == 1


def test_editing_old_version_does_not_hide_latest_import_failure(sandbox):
    seed(sandbox)
    async def edit():
        async with sandbox.sessions() as db:
            old = await db.get(Task,'alice-old')
            old.updated_at = datetime(2026,10,16,tzinfo=timezone.utc)
            await db.commit()
    asyncio.run(edit())
    group = song(sandbox)
    assert group['latest_task_id'] == 'alice-bad'
    assert group['status'] == 'failed'
    assert group['current_task_id'] == 'alice-new'
    assert group['updated_at'].startswith('2026-10-16')
