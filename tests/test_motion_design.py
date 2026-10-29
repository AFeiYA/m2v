"""Authoring documents persist independently of lyrics and renderer output."""
import copy
import json
from fastapi.testclient import TestClient
from src.local_editor import app
from tests.test_motion_studio_api import song  # noqa: F401


def test_document_round_trip_and_director_edits_are_mode_scoped(song):
    path, project_id = song
    with TestClient(app) as client:
        initial = client.get('/api/motion/project', params={'project_id': project_id}).json()
        design = initial['design']
        assert design['modes']['kinetic']['plan'] is None
        plan = client.post('/api/motion/director/rules', json={'project_id': project_id}).json()
        design.update(active_mode='apple', height=360)
        design['modes']['kinetic']['plan'] = plan
        design['modes']['apple'].update(aspect='16:9', focus_y=.5, theme={'palette': 'neon', 'background': 'light'})
        design['modes']['tv']['preview_seconds'] = 1
        result = client.put('/api/motion/design', json={'project_id': project_id, 'design': design})
        assert result.status_code == 200, result.text
        saved = result.json()['design']
        source = path.read_bytes()
        loaded = client.get('/api/motion/project', params={'project_id': project_id}).json()
        assert loaded['design'] == saved
        assert loaded['project']['motion_design'] == saved
        assert path.read_bytes() == source
        # A director operation edits only the poster namespace.
        modified = copy.deepcopy(plan)
        modified['cues'][0]['locked'] = True
        assert client.put('/api/motion/plan', json={'project_id': project_id, 'plan': modified, 'from_llm': False}).status_code == 200
        updated = client.get('/api/motion/project', params={'project_id': project_id}).json()['design']
        assert updated['active_mode'] == 'apple'
        assert updated['modes']['apple'] == saved['modes']['apple']
        assert updated['modes']['tv'] == saved['modes']['tv']
        assert updated['modes']['kinetic']['plan']['cues'][0]['locked']


def test_invalid_document_cannot_partially_overwrite_a_saved_design(song):
    path, project_id = song
    with TestClient(app) as client:
        design = client.get('/api/motion/project', params={'project_id': project_id}).json()['design']
        assert client.put('/api/motion/design', json={'project_id': project_id, 'design': design}).status_code == 200
        destination = path.with_name('test_motion_design.json')
        before = destination.read_bytes()
        bad = copy.deepcopy(design)
        bad['modes']['tv']['preview_seconds'] = -1
        assert client.put('/api/motion/design', json={'project_id': project_id, 'design': bad}).status_code == 422
        assert destination.read_bytes() == before
        bad = copy.deepcopy(design)
        bad['modes']['kinetic']['plan'] = {'version': 'motion-plan-v1', 'source_signature': 'wrong', 'seed': 1, 'cues': []}
        assert client.put('/api/motion/design', json={'project_id': project_id, 'design': bad}).status_code == 422
        assert destination.read_bytes() == before
        bad = copy.deepcopy(design)
        bad['active_mode'] = 'unknown'
        assert client.put('/api/motion/design', json={'project_id': project_id, 'design': bad}).status_code == 422
        assert json.loads(destination.read_text()) == design


def test_stream_export_does_not_require_or_validate_a_poster_plan(song):
    path, project_id = song
    # Stop before starting a render worker; this regression tests admission order.
    (path.parent / 'test.wav').unlink()
    with TestClient(app) as client:
        for mode in ('apple', 'tv'):
            response=client.post('/api/motion/render',json={'project_id':project_id,'visual_mode':mode})
            assert response.status_code==404,response.text
            assert 'MP4' in response.json()['detail']
        assert client.post('/api/motion/render',json={'project_id':project_id,'visual_mode':'kinetic'}).status_code==422


def test_plan_preserved_when_lyrics_updated_and_design_saved(song):
    path, project_id = song
    with TestClient(app) as client:
        # 1. Generate and save a kinetic plan
        plan = client.post('/api/motion/director/rules', json={'project_id': project_id}).json()
        assert client.put('/api/motion/plan', json={'project_id': project_id, 'plan': plan, 'from_llm': False}).status_code == 200

        # 2. Modify song lyrics in the alignment file
        data = json.loads(path.read_text())
        data['lines'][0]['text'] = '修改后的新歌词'
        path.write_text(json.dumps(data, ensure_ascii=False))

        # 3. GET project: should keep plan, not wipe it to None, and mark plan_needs_sync=True
        loaded = client.get('/api/motion/project', params={'project_id': project_id}).json()
        assert loaded['plan'] is not None
        assert loaded['plan_needs_sync'] is True
        assert '不匹配' in loaded['plan_error']
        assert loaded['design']['modes']['kinetic']['plan'] is not None

        # 4. User saves design (e.g. changing active mode or apple settings)
        design = loaded['design']
        design['active_mode'] = 'apple'
        res = client.put('/api/motion/design', json={'project_id': project_id, 'design': design})
        assert res.status_code == 200

        # 5. Verify the plan on disk was NOT wiped
        reloaded = client.get('/api/motion/project', params={'project_id': project_id}).json()
        assert reloaded['plan'] is not None
        assert reloaded['design']['modes']['kinetic']['plan'] is not None
        assert reloaded['design']['active_mode'] == 'apple'
