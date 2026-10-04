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


def test_semantic_relations_persist_in_plan_store(song):
    path,id=song
    with TestClient(app) as client:
        plan=client.post('/api/motion/director/rules',json={'project_id':id}).json()
        bundle=client.post('/api/motion/director/line/input',json={'project_id':id,'line_id':'line_0001'}).json()
        response=bundle['response_example']
        relation={'kind':'spatial','node_indices':[0],'intent':'整句中的空间意象；仅为导演数据'}
        response['cue']['poster']['relations']=[relation]
        applied=client.post('/api/motion/director/line/apply',json={'project_id':id,'line_id':'line_0001','response':response})
        assert applied.status_code==200,applied.text
        saved=client.get('/api/motion/project',params={'project_id':id}).json()['plan']
        assert saved['cues'][0]['poster']['relations']==[relation]
        response['base_cue_signature']=None
        response['cue']['poster']['relations'][0]['node_indices']=[5]
        assert client.post('/api/motion/director/line/validate',json={'project_id':id,'line_id':'line_0001','response':response}).status_code==422


@pytest.mark.skipif(os.getenv('RUN_MOTION_RENDER')!='1',reason='需显式启用 Chrome/FFmpeg 成片测试')
def test_portrait_export_preserves_readable_lyric_during_handover_gap(tmp_path):
    from src.motion_director import rule_plan
    from PIL import Image
    root=Path(__file__).resolve().parents[1]
    project={'title':'交接测试','duration':3,'lines':[
        {'text':'引导 核心','start':.2,'end':1.0,'words':[{'word':'引导','start':.2,'end':.5},{'word':'核心','start':.5,'end':1.0}]},
        {'text':'下一句','start':1.9,'end':2.8,'words':[{'word':'下一句','start':1.9,'end':2.8}]}]}
    plan=rule_plan(project).model_dump()
    from src.motion_director import example_poster
    from src.motion_director import director_input
    for cue,row in zip(plan['cues'],director_input(project)['lines']):
        cue['poster']=example_poster(row).model_dump();cue['poster']['transition_out']='fade'
    base=plan['cues'][0]['poster']['nodes'][0]
    plan['cues'][0]['poster']['nodes']=[{**base,'text':'引导','word_indices':[0],'role':'secondary'}, {**base,'text':'核心','word_indices':[1],'role':'primary'}]
    plan['cues'][0]['poster']['relations']=[{'kind':'guidance','node_indices':[0,1],'intent':'引导承接核心'}]
    project['motion_plan']=plan
    audio=tmp_path/'audio.wav';sf.write(audio,np.zeros(22050*3),22050)
    job=tmp_path/'job.json';video=tmp_path/'portrait.mp4'
    job.write_text(json.dumps({'project':project,'options':{'aspect':'9:16','height':720},'start':0,'length':3,'audioPath':str(audio)}))
    result=subprocess.run([shutil.which('node'),str(root/'frontend/motion/scripts/render-remotion.mjs'),str(job),str(video)],capture_output=True,text=True,timeout=120)
    assert result.returncode==0,result.stderr
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(video)]))
    v=next(s for s in info['streams'] if s['codec_type']=='video');assert (v['width'],v['height'],int(v['nb_frames']))==(720,1280,90)
    assert any(s['codec_type']=='audio' for s in info['streams'])
    values=[]
    for time,name in [(0,'empty'),(1.2,'gap'),(2.3,'next')]:
        path=tmp_path/(name+'.png')
        subprocess.run(['ffmpeg','-v','error','-ss',str(time),'-i',str(video),'-frames:v','1',str(path)],check=True)
        values.append(np.asarray(Image.open(path).convert('RGB'),dtype=float).std(axis=(0,1)).max())
    assert values[0]<3 and values[1]>10 and values[2]>10


def test_studio_script_url_changes_with_build_content(tmp_path,monkeypatch):
    import src.local_editor as editor
    front=tmp_path/'frontend';(front/'motion').mkdir(parents=True)
    (front/'motion_studio_director.html').write_text('<link href="/motion-lab.css"><script src="/motion/studio.js"></script>')
    script=front/'motion/studio.js';script.write_text('first build')
    style=front/'motion-lab.css';style.write_text('first style')
    monkeypatch.setattr(editor,'_FRONTEND_DIR',front)
    with TestClient(app) as client:
        first=client.get('/motion_studio')
        assert first.headers['cache-control']=='no-cache'
        assert '/motion/studio.js?v=' in first.text
        assert '/motion-lab.css?v=' in first.text
        assert client.get('/motion_studio').text==first.text
        script.write_text('new build')
        second=client.get('/motion_studio').text
        assert second!=first.text
        style.write_text('new style')
        assert client.get('/motion_studio').text!=second


def wait_director(client,job_id):
    import time
    for _ in range(100):
        result=client.get('/api/motion/director/jobs/'+job_id).json()
        if result['status'] in ('ready','failed'):return result
        time.sleep(.01)
    pytest.fail('director worker did not finish')


def mock_director_config(monkeypatch):
    from src.motion_llm import DirectorConfig
    monkeypatch.setattr('src.motion_api.configuration',lambda:DirectorConfig('https://example.test','gemini-3.8-flash','test-secret'))


def test_gemini_line_generates_draft_then_applies_without_changing_alignment(song,monkeypatch):
    from src.motion_director import line_prompt_bundle
    path,id=song;original=path.read_text();mock_director_config(monkeypatch)
    with TestClient(app) as client:
        old=client.post('/api/motion/director/rules',json={'project_id':id}).json()
        response=line_prompt_bundle(json.loads(original),'line_0001',old)['response_example']
        response['cue']['poster']['visual_intensity']='restrained'
        monkeypatch.setattr('src.motion_api.generate_json',lambda *args:response)
        submitted=client.post('/api/motion/director/generate',json={'project_id':id,'line_id':'line_0001'})
        assert submitted.status_code==202
        job=wait_director(client,submitted.json()['id']);assert job['status']=='ready'
        assert 'test-secret' not in json.dumps(job) and 'baseline' not in job
        assert client.get('/api/motion/project',params={'project_id':id}).json()['plan']==old
        applied=client.post('/api/motion/director/jobs/'+job['id']+'/apply')
        assert applied.status_code==200
        assert applied.json()['plan']['cues'][0]['poster']['visual_intensity']=='restrained'
        assert path.read_text()==original
        assert client.post('/api/motion/director/jobs/'+job['id']+'/apply').status_code==409


def test_gemini_repair_once_and_conflict_never_overwrites_changes(song,monkeypatch):
    from src.motion_director import line_prompt_bundle
    path,id=song;mock_director_config(monkeypatch);calls=[]
    with TestClient(app) as client:
        old=client.post('/api/motion/director/rules',json={'project_id':id}).json()
        valid=line_prompt_bundle(json.loads(path.read_text()),'line_0001',old)['response_example']
        def generate(config,prompt,repair):
            calls.append(repair)
            return {'version':'motion-plan-v1'} if len(calls)==1 else valid
        monkeypatch.setattr('src.motion_api.generate_json',generate)
        job=wait_director(client,client.post('/api/motion/director/generate',json={'project_id':id,'line_id':'line_0001'}).json()['id'])
        assert job['status']=='ready' and len(calls)==2 and calls[1]
        old['cues'][0]['intensity']=.85
        assert client.put('/api/motion/plan',json={'project_id':id,'plan':old,'from_llm':False}).status_code==200
        assert client.post('/api/motion/director/jobs/'+job['id']+'/apply').status_code==409
        assert client.get('/api/motion/project',params={'project_id':id}).json()['plan']['cues'][0]['intensity']==.85


def test_gemini_invalid_result_fails_twice_and_locked_target_never_calls_api(song,monkeypatch):
    path,id=song;mock_director_config(monkeypatch);calls=[]
    monkeypatch.setattr('src.motion_api.generate_json',lambda *args:(calls.append(1) or {}))
    with TestClient(app) as client:
        old=client.post('/api/motion/director/rules',json={'project_id':id}).json()
        job=wait_director(client,client.post('/api/motion/director/generate',json={'project_id':id}).json()['id'])
        assert job['status']=='failed' and len(calls)==2
        assert client.get('/api/motion/project',params={'project_id':id}).json()['plan']==old
        old['cues'][0]['locked']=True;client.put('/api/motion/plan',json={'project_id':id,'plan':old,'from_llm':False})
        assert client.post('/api/motion/director/generate',json={'project_id':id,'line_id':'line_0001'}).status_code==409
        assert len(calls)==2


@pytest.mark.parametrize('change',['timing','lyrics'])
def test_gemini_generation_rebinds_timing_but_conflicts_on_lyrics(song,monkeypatch,change):
    from src.motion_director import example_poster,director_input
    path,id=song;mock_director_config(monkeypatch)
    with TestClient(app) as client:
        plan=client.post('/api/motion/director/rules',json={'project_id':id}).json()
        plan['cues'][0]['poster']=example_poster(director_input(json.loads(path.read_text()))['lines'][0]).model_dump()
        monkeypatch.setattr('src.motion_api.generate_json',lambda *args:plan)
        job=wait_director(client,client.post('/api/motion/director/generate',json={'project_id':id}).json()['id'])
        assert job['status']=='ready'
        data=json.loads(path.read_text())
        if change=='timing': data['lines'][0]['words'][0]['start']=.3
        else: data['lines'][0]['text']='听见我'
        path.write_text(json.dumps(data))
        response=client.post('/api/motion/director/jobs/'+job['id']+'/apply')
        assert response.status_code==(200 if change=='timing' else 409)


def test_unconfigured_gemini_is_clear_and_does_not_start_job(song,monkeypatch):
    from src.motion_llm import DirectorAPIError
    def missing(): raise DirectorAPIError('请在后端配置 GEMINI_API_KEY')
    monkeypatch.setattr('src.motion_api.configuration',missing)
    with TestClient(app) as client:
        config=client.get('/api/motion/director/config').json();assert not config['configured']
        assert client.post('/api/motion/director/generate',json={'project_id':song[1]}).status_code==503


@pytest.mark.parametrize('outcome',['success','repair','both_exhausted','authentication'])
def test_gemini_quota_fallback_is_bounded_and_repairs_stay_on_lite(song,monkeypatch,outcome):
    from src.motion_director import line_prompt_bundle
    from src.motion_llm import DirectorQuotaError,DirectorAPIError
    path,id=song;mock_director_config(monkeypatch);calls=[]
    with TestClient(app) as client:
        old=client.post('/api/motion/director/rules',json={'project_id':id}).json()
        valid=line_prompt_bundle(json.loads(path.read_text()),'line_0001',old)['response_example']
        def generate(config,prompt,repair):
            calls.append(config.model)
            if len(calls)==1:
                if outcome=='authentication':raise DirectorAPIError('认证失败')
                raise DirectorQuotaError('额度不足')
            if outcome=='both_exhausted':raise DirectorQuotaError('额度不足')
            if outcome=='repair' and len(calls)==2:return {}
            return valid
        monkeypatch.setattr('src.motion_api.generate_json',generate)
        job=wait_director(client,client.post('/api/motion/director/generate',json={'project_id':id,'line_id':'line_0001'}).json()['id'])
        assert job['requested_model']=='gemini-3.8-flash'
        if outcome=='authentication':
            assert calls==['gemini-3.8-flash'] and not job['fallback_used'] and job['status']=='failed'
        else:
            assert calls==['gemini-3.8-flash']+['gemini-3.5-flash-lite']*(2 if outcome=='repair' else 1)
            assert job['fallback_used'] and job['model']=='gemini-3.5-flash-lite'
            assert job['status']==('failed' if outcome=='both_exhausted' else 'ready')
        assert client.get('/api/motion/project',params={'project_id':id}).json()['plan']==old


@pytest.mark.skipif(os.getenv('RUN_MOTION_RENDER')!='1',reason='需显式启用 Chrome/FFmpeg 成片测试')
def test_fractional_mp3_clip_preserves_all_remotion_frames(tmp_path):
    from src.motion_director import rule_plan
    root=Path(__file__).resolve().parents[1]
    project={'title':'非整帧片段测试','duration':40,'lines':[{'text':'水往低处流去','start':34.12,'end':36.91,'words':[]}]}
    project['motion_plan']=rule_plan(project).model_dump()
    wav=tmp_path/'source.wav';mp3=tmp_path/'source.mp3';sf.write(wav,np.zeros(22050*40),22050)
    subprocess.run(['ffmpeg','-v','error','-i',str(wav),str(mp3)],check=True)
    job=tmp_path/'job.json';out=tmp_path/'clip.mp4'
    job.write_text(json.dumps({'project':project,'options':{'aspect':'9:16','height':360},'start':33.92,'length':3.99,'audioPath':str(mp3)}))
    result=subprocess.run([shutil.which('node'),str(root/'frontend/motion/scripts/render-remotion.mjs'),str(job),str(out)],capture_output=True,text=True,timeout=120)
    assert result.returncode==0,result.stderr
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(out)]))
    video=next(s for s in info['streams'] if s['codec_type']=='video');audio=next(s for s in info['streams'] if s['codec_type']=='audio')
    assert int(video['nb_frames'])==120
    assert float(video['duration'])==pytest.approx(4,abs=.001)
    assert float(audio['duration'])==pytest.approx(4,abs=.05)


def test_director_input_and_generation_gracefully_ignore_obsolete_plan_when_lyrics_change(song, monkeypatch):
    path, id = song
    mock_director_config(monkeypatch)
    with TestClient(app) as client:
        # Save an initial plan for original lyrics
        old = client.post('/api/motion/director/rules', json={'project_id': id}).json()
        assert old['cues']
        # Modify the lyrics (e.g. insert or change line text)
        data = json.loads(path.read_text(encoding='utf-8'))
        data['lines'][0]['text'] = '全新修改后的第一句歌词'
        s = data['lines'][0]['start']
        data['lines'][0]['words'] = [{'word': '全新', 'start': s, 'end': s + 0.5}]
        path.write_text(json.dumps(data, ensure_ascii=False))

        # Downloading prompt for full song or single line should NOT fail with 422
        resp = client.post('/api/motion/director/input', json={'project_id': id})
        assert resp.status_code == 200
        assert '全新修改后的第一句歌词' in resp.json()['prompt']

        line_resp = client.post('/api/motion/director/line/input', json={'project_id': id, 'line_id': 'line_0001'})
        assert line_resp.status_code == 200
        assert '全新修改后的第一句歌词' in line_resp.json()['prompt']



def test_song_identity_defaults_edits_and_does_not_change_alignment(song):
    path, project_id = song
    cache = path.with_name('test_suno.json')
    cache.write_text(json.dumps({'title': '兔子洞', 'display_name': 'Luca'}))
    original = path.read_bytes()
    with TestClient(app) as client:
        identity = client.get('/api/motion/project', params={'project_id': project_id}).json()['project']['song_identity']
        assert (identity['title'], identity['artist']) == ('兔子洞', 'Luca')
        assert identity['source'] == 'suno-cache'
        editable = {k: v for k, v in identity.items() if not k.startswith('source')}
        editable.update(title='自己的歌名', artist='', style='minimal', show_intro=False)
        response = client.put('/api/motion/identity', json={'project_id': project_id, 'identity': editable})
        assert response.status_code == 200, response.text
        project = client.get('/api/motion/project', params={'project_id': project_id}).json()['project']
        assert project['title'] == '自己的歌名'
        assert project['artist'] == ''
        assert project['song_identity']['source_title'] == '兔子洞'
        assert project['song_identity']['show_intro'] is False
        assert path.read_bytes() == original
        editable['title'] = '  '
        assert client.put('/api/motion/identity', json={'project_id': project_id, 'identity': editable}).status_code == 422
        editable['title'] = '有效歌名'
        assert client.put('/api/motion/identity', json={'project_id': '../test_alignment.json', 'identity': editable}).status_code == 400


def test_cover_upload_is_portable_validated_and_restorable(song):
    from io import BytesIO
    from PIL import Image
    from src.song_cover import cover_path
    path, project_id = song
    image = BytesIO()
    Image.new('RGB', (640, 320), '#a02b4b').save(image, 'PNG')
    original = path.read_bytes()
    with TestClient(app) as client:
        response = client.post('/api/motion/cover', data={'project_id': project_id}, files={'file': ('cover.png', image.getvalue(), 'image/png')})
        assert response.status_code == 200, response.text
        cover = response.json()['cover']
        assert cover['source'] == 'custom'
        assert (cover['width'], cover['height']) == (640, 320)
        assert cover['data_url'].startswith('data:image/jpeg;base64,')
        assert path.read_bytes() == original
        assert client.get('/api/motion/project', params={'project_id': project_id}).json()['project']['song_cover'] == cover
        assert client.post('/api/motion/cover', data={'project_id': project_id}, files={'file': ('cover.png', b'not an image', 'image/png')}).status_code == 422
        assert client.post('/api/motion/cover', data={'project_id': '../escape_alignment.json'}, files={'file': ('cover.png', image.getvalue(), 'image/png')}).status_code == 400
        cover_path(path, False).write_bytes(cover_path(path).read_bytes())
        assert client.post('/api/motion/cover/suno', json={'project_id': project_id}).json()['cover']['source'] == 'custom'
        restored = client.post('/api/motion/cover/suno', json={'project_id': project_id, 'restore': True})
        assert restored.status_code == 200
        assert restored.json()['cover']['source'] == 'suno'
        assert not cover_path(path).exists()


def test_cover_rejects_external_suno_source(song):
    path, project_id = song
    path.with_name('test_suno.json').write_text(json.dumps({'title': 'Song', 'image_url': 'http://127.0.0.1/private'}))
    with TestClient(app) as client:
        assert client.post('/api/motion/cover/suno', json={'project_id': project_id}).status_code == 422
