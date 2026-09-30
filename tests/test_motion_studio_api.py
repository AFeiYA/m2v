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
        whole_input=client.post('/api/motion/director/input',json={'project_id':id,'instruction':'保持安静的节奏'})
        assert whole_input.status_code==200
        assert '保持安静的节奏' in whole_input.json()['prompt']


@pytest.mark.skipif(os.getenv('RUN_MOTION_RENDER')!='1',reason='需显式启用 Chrome/FFmpeg 成片测试')
@pytest.mark.parametrize('worker',['render.mjs','render-remotion.mjs'])
def test_render_worker_outputs_audio_video_and_exact_frames(song,tmp_path,worker):
    from src.motion_director import rule_plan
    path,id=song
    root=Path(__file__).resolve().parents[1]
    project=json.loads(path.read_text());project['motion_plan']=rule_plan(project).model_dump()
    project['lines'][0]['words']=[{'word':'听','start':.2,'end':.7},{'word':'见','start':.7,'end':1.2},{'word':'你','start':1.2,'end':1.8}]
    project['motion_plan']['cues'][0]['poster']={'version':'motion-poster-direction-v1','status':'draft','layout':'center-stack','intent':'逐组拼成整句','background':'#eeeee6','accent':'#c1ee47','motif':'none','visibility':'cumulative','final_hold':'available-tail','transition_out':'cut','transition_note':'','nodes':[{'text':ch,'word_indices':[i],'role':'primary' if i==1 else 'secondary','emphasis':'','color_role':'foreground','entrance':'slide-up','settle_fraction':.25} for i,ch in enumerate('听见你')]}
    project['motion_plan']['cues'][0]['groups']=[{'text':'听见你','word_indices':[0],'action':'push','emphasis':'你','intensity':.7}]
    snapshot=tmp_path/'job.json';out=tmp_path/'result.mp4'
    snapshot.write_text(json.dumps({'project':project,'options':{'aspect':'16:9','height':360,'preset':'impact','mode':'phrase','bloom':.7,'grain':.035,'shake':.65,'punch':.7,'post':True},'start':.2,'length':1.6,'audioPath':str(path.parent/'test.wav')}))
    result=subprocess.run([shutil.which('node'),str(root/'frontend/motion/scripts'/worker),str(snapshot),str(out)],capture_output=True,text=True,timeout=120)
    assert result.returncode==0,result.stderr
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(out)]))
    video=next(s for s in info['streams'] if s['codec_type']=='video')
    assert video['width']==640 and video['height']==360
    assert int(video['nb_frames'])==48
    assert any(s['codec_type']=='audio' for s in info['streams'])
    assert float(info['format']['duration'])==pytest.approx(1.6,abs=.1)
    # First frame is the empty poster; after all alignment anchors the poster has text.
    from PIL import Image
    for time,name in [(0,'empty'),(1.5,'complete')]:
        subprocess.run(['ffmpeg','-v','error','-ss',str(time),'-i',str(out),'-frames:v','1',str(tmp_path/(name+'.png'))],check=True)
    empty=np.asarray(Image.open(tmp_path/'empty.png').convert('RGB'),dtype=float)
    complete=np.asarray(Image.open(tmp_path/'complete.png').convert('RGB'),dtype=float)
    assert empty.std(axis=(0,1)).max()<3
    assert complete.std(axis=(0,1)).max()>10



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


def test_single_line_validate_apply_conflict_and_other_cues(song):
    path,id=song
    data=json.loads(path.read_text());data['lines'].append({'text':'下一句','start':.3,'end':1.9})
    path.write_text(json.dumps(data))
    with TestClient(app) as client:
        plan=client.post('/api/motion/director/rules',json={'project_id':id}).json()
        request={'project_id':id,'line_id':'line_0001','instruction':'强调听见你，整句保留'}
        bundle=client.post('/api/motion/director/line/input',json=request).json()
        response=bundle['response_example'];response['cue']['intent']='邀请听见'
        body={**request,'response':response}
        before=path.with_name('test_motion_plan.json').read_text()
        checked=client.post('/api/motion/director/line/validate',json=body)
        assert checked.status_code==200,checked.text
        assert checked.json()['compiled_groups'][0]['start']==.2
        assert path.with_name('test_motion_plan.json').read_text()==before
        # Another line changed after prompt creation: merge must preserve its new state.
        plan['cues'][1]['intensity']=.15
        client.put('/api/motion/plan',json={'project_id':id,'plan':plan,'from_llm':False})
        applied=client.post('/api/motion/director/line/apply',json=body)
        assert applied.status_code==200,applied.text
        assert applied.json()['plan']['cues'][1]['intensity']==.15
        # Reusing the prompt after this same line changed is a conflict.
        assert client.post('/api/motion/director/line/apply',json=body).status_code==409
        fresh=client.post('/api/motion/director/line/input',json=request).json()
        plan=applied.json()['plan'];plan['cues'][0]['locked']=True
        client.put('/api/motion/plan',json={'project_id':id,'plan':plan,'from_llm':False})
        assert client.post('/api/motion/director/line/apply',json={**request,'response':fresh['response_example']}).status_code==409
        unknown=client.post('/api/motion/director/line/input',json={**request,'line_id':'line_9999'})
        assert unknown.status_code==422
