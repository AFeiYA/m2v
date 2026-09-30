import json
import shutil
import subprocess
import os
from pathlib import Path
import numpy as np
import soundfile as sf
import pytest
from fastapi.testclient import TestClient
from src.local_editor import app

@pytest.fixture
def song(tmp_path,monkeypatch):
    output=tmp_path/'output';directory=output/'test';directory.mkdir(parents=True)
    path=directory/'test_alignment.json'
    data={'title':'字幕测试','duration':2,'lines':[{'text':'听见你','start':.2,'end':1.8,'words':[{'word':'听见你','start':.2,'end':1.8}]}]}
    path.write_text(json.dumps(data,ensure_ascii=False));sf.write(directory/'test.wav',np.zeros(22050*2),22050)
    monkeypatch.setattr(app.state,'scan_dir',output,raising=False)
    return path,'test/test_alignment.json'


def test_plan_save_locks_and_route_shared_song_store(song):
    path,id=song
    with TestClient(app) as client:
        assert client.get('/motion_studio').status_code==200
        rows=client.get('/api/motion/projects').json();assert rows[0]['id']==id
        plan=client.post('/api/motion/director/rules',json={'project_id':id}).json()
        original=path.read_text()
        plan['cues'][0]['locked']=True
        assert client.put('/api/motion/plan',json={'project_id':id,'plan':plan,'from_llm':False}).status_code==200
        plan['cues'][0]['intensity']=.95
        assert client.put('/api/motion/plan',json={'project_id':id,'plan':plan}).status_code==422
        assert path.read_text()==original
        payload=client.get('/api/motion/project',params={'project_id':id}).json()
        assert payload['plan']['cues'][0]['locked']
        assert payload['audio_url'].startswith('/api/audio?')
        assert client.get('/api/motion/project',params={'project_id':'../other_alignment.json'}).status_code==400
        assert client.post('/api/motion/render',json={'project_id':id,'start':1,'length':5}).status_code==422
        assert client.post('/api/motion/director/input',json={'project_id':id}).status_code==200


@pytest.mark.skipif(os.getenv('RUN_MOTION_RENDER')!='1',reason='需显式启用 Chrome/FFmpeg 成片测试')
def test_render_worker_outputs_audio_video_and_exact_frames(song,tmp_path):
    from src.motion_director import rule_plan
    path,id=song
    root=Path(__file__).resolve().parents[1]
    project=json.loads(path.read_text());project['motion_plan']=rule_plan(project).model_dump()
    snapshot=tmp_path/'job.json';out=tmp_path/'result.mp4'
    snapshot.write_text(json.dumps({'project':project,'options':{'aspect':'16:9','height':360,'preset':'impact','mode':'phrase','bloom':.7,'grain':.035,'shake':.65,'punch':.7,'post':True},'start':0,'length':2,'audioPath':str(path.parent/'test.wav')}))
    result=subprocess.run([shutil.which('node'),str(root/'frontend/motion/scripts/render.mjs'),str(snapshot),str(out)],capture_output=True,text=True,timeout=120)
    assert result.returncode==0,result.stderr
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(out)]))
    video=next(s for s in info['streams'] if s['codec_type']=='video')
    assert video['width']==640 and video['height']==360
    assert int(video['nb_frames'])==60
    assert any(s['codec_type']=='audio' for s in info['streams'])
    assert float(info['format']['duration'])==pytest.approx(2,abs=.1)


def test_partial_regeneration_preserves_other_edits(song):
    path,id=song
    payload=json.loads(path.read_text())
    payload['lines'].append({'text':'第二句','start':.3,'end':1.9})
    path.write_text(json.dumps(payload))
    with TestClient(app) as client:
        plan=client.post('/api/motion/director/rules',json={'project_id':id}).json()
        plan['cues'][1]['palette']='neon';plan['cues'][1]['intensity']=.13
        assert client.put('/api/motion/plan',json={'project_id':id,'plan':plan,'from_llm':False}).status_code==200
        updated=client.post('/api/motion/director/rules',json={'project_id':id,'line_id':'line_0001'}).json()
        assert updated['cues'][1]==plan['cues'][1]
