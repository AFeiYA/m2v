"""Synthetic files and isolated accounts; no real rendering or cloud storage."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from tests.test_saas_isolation import sandbox, seed_cloud_motion, headers  # noqa: F401
from src import motion_browser_exports as browser
from src.models import CreditReservation, VideoExport
from src.settings import get_settings

VIDEO = b'\x00\x00\x00\x18ftypmp42synthetic-video'


@pytest.fixture
def ready(sandbox, monkeypatch):
    seed_cloud_motion(sandbox)
    monkeypatch.setattr(get_settings(), 'MOTION_WEBCODECS_CREDITS', 2)
    monkeypatch.setattr(browser, 'inspect_video', lambda path: {'resolution':[1080,1920], 'duration':2})
    return sandbox


def upload(s, params=None, content=VIDEO, uid='alice'):
    return s.client.post('/api/cloud-motion/browser-exports',
        params=params or options(), content=content,
        headers={**headers(uid), 'Content-Type':'video/mp4'})


def options(**changes):
    return dict(project_id='alice_motion',request_id=str(uuid4()),accepted_cost=2,**changes)


def balance(s):
    return s.client.get('/api/credits',headers=headers()).json()['available']


def test_upload_archives_actual_mp4_and_replay_keeps_original_price(ready, monkeypatch):
    params=options()
    first=upload(ready,params)
    assert first.status_code==200, first.text
    export_id=first.json()['id']
    monkeypatch.setattr(get_settings(),'MOTION_WEBCODECS_CREDITS',4)
    replay=upload(ready,params)
    assert replay.status_code==200 and replay.json()['replay']
    assert balance(ready)==3
    access=ready.client.get(f'/api/exports/{export_id}/access',headers=headers())
    assert access.status_code==200
    assert ready.client.get(access.json()['url']).content==VIDEO
    async def check():
        async with ready.sessions() as db:
            row=await db.get(VideoExport,export_id)
            assert row.storage_key.endswith('.mp4')
            assert row.details['size_bytes']==len(VIDEO)
            assert (await db.execute(select(CreditReservation))).scalar_one().state=='settled'
    asyncio.run(check())
    assert ready.client.get(f'/api/exports/{export_id}/access',headers=headers('bob')).status_code==404


def test_parallel_duplicate_uploads_charge_once(ready):
    params=options()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:upload(ready,params),range(2)))
    assert [r.status_code for r in responses]==[200,200]
    assert len({r.json()['id'] for r in responses})==1
    assert balance(ready)==3


@pytest.mark.parametrize('failure',['save','verify','archive'])
def test_failed_storage_or_library_publication_never_charges(ready, monkeypatch, failure):
    if failure=='save':
        async def broken(*args):raise HTTPException(503,'Storage unavailable')
        monkeypatch.setattr(ready.storage,'save',broken)
    elif failure=='verify':
        async def wrong_size(*args):return 0
        monkeypatch.setattr(ready.storage,'get_size',wrong_size)
    else:
        async def unavailable(*args,**kwargs):return False
        monkeypatch.setattr(browser,'record_export',unavailable)
    response=upload(ready)
    assert response.status_code in (409,503)
    assert balance(ready)==5
    async def check():
        async with ready.sessions() as db:
            assert not (await db.execute(select(VideoExport))).scalars().all()
            assert not (await db.execute(select(CreditReservation))).scalars().all()
    asyncio.run(check())
    assert not asyncio.run(ready.storage.list_keys('exports/'))


def test_ownership_price_and_request_validation(ready):
    assert upload(ready,uid='bob').status_code==404
    params=options();params['accepted_cost']=0
    assert upload(ready,params).status_code==409
    params['request_id']='../../outside'
    assert upload(ready,params).status_code==422
    assert balance(ready)==5


def test_conflicting_or_deleted_request_cannot_be_reused(ready):
    params=options();first=upload(ready,params)
    assert upload(ready,params,content=VIDEO+b'other').status_code==409
    assert ready.client.delete('/api/exports/'+first.json()['id'],headers=headers()).status_code==200
    assert upload(ready,params).status_code==409
    assert balance(ready)==3


def test_size_limit_and_invalid_media_fail_without_charging(ready,monkeypatch):
    monkeypatch.setattr(browser,'MAX_UPLOAD_BYTES',4)
    assert upload(ready).status_code==413
    assert balance(ready)==5


def test_legacy_metadata_record_is_not_served_as_mp4(ready):
    async def seed():
        async with ready.sessions() as db:
            db.add(VideoExport(id='legacy',user_id='alice',task_id='alice_motion',
                               storage_key='old_status.json',kind='webcodecs'))
            await db.commit()
    asyncio.run(seed())
    response=ready.client.get('/api/exports/legacy/access',headers=headers())
    assert response.status_code==409
    assert 'metadata only' in response.json()['detail']


@pytest.mark.parametrize('audio',[True,False])
def test_probe_requires_video_and_audio(tmp_path,monkeypatch,audio):
    path=tmp_path/'video.mp4';path.write_bytes(VIDEO)
    info={'streams':[{'codec_type':'video','width':1080,'height':1920}], 'format':{'duration':'2'}}
    if audio:info['streams'].append({'codec_type':'audio'})
    monkeypatch.setattr(browser.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(stdout=json.dumps(info)))
    if audio:assert browser.inspect_video(path)['duration']==2
    else:
        with pytest.raises(HTTPException):browser.inspect_video(path)
