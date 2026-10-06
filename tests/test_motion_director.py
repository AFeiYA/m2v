import copy
import json
import pytest
from src.motion_director import rule_plan, validate_plan, director_input, llm_prompt

@pytest.fixture
def project():
    return {'title':'测试歌','duration':20,'lines':[
        {'text':'标记','start':0,'end':0},
        {'text':'听见你','start':1,'end':4,'section':'Verse','words':[{'word':'听见你','start':1,'end':4}]},
        {'text':'放大这一刻','start':5,'end':8,'section':'Chorus','words':[{'word':'放大','start':5,'end':6},{'word':'这一刻','start':6,'end':8}]},
        {'text':'余音','start':17,'end':19,'section':'Outro'}],
        'analysis':{'bpm':120,'beats':[1,2,3,5,6,7], 'energy_curve':[{'time':1,'energy':.4}], 'metadata':{'audio_path':'private/path','downbeats_method':'estimated_4_4'}}}


def test_input_summary_and_deterministic_rules(project):
    before=copy.deepcopy(project)
    summary=director_input(project)
    assert len(summary['lines'])==3
    assert summary['lines'][0]['line_id']=='line_0002'
    assert 'private/path' not in llm_prompt(project)
    plan=rule_plan(project)
    assert [cue.template for cue in plan.cues]==['phrase-rise','word-impact','quiet-hold']
    assert plan==rule_plan(project)
    assert validate_plan(project,plan.model_dump())==plan
    assert before==project

@pytest.mark.parametrize('change',['signature','duplicate','missing','template','emphasis','intensity','extra'])
def test_invalid_llm_output_rejected(project,change):
    data=rule_plan(project).model_dump()
    if change=='signature': data['source_signature']='wrong'
    elif change=='duplicate': data['cues'][1]=data['cues'][0]
    elif change=='missing': data['cues'].pop()
    elif change=='template': data['cues'][0]['template']='made-up'
    elif change=='emphasis': data['cues'][0]['emphasis']='不存在'
    elif change=='intensity': data['cues'][0]['intensity']=2
    else: data['cues'][0]['code']='alert(1)'
    with pytest.raises(ValueError): validate_plan(project,data)


def test_timing_edit_preserves_plan_and_locks_survive_regeneration(project):
    old=rule_plan(project).model_dump();old['seed']=123;old['cues'][0].update(locked=True,palette='neon',intensity=.1)
    regenerated=rule_plan(project,old).model_dump()
    assert regenerated['cues'][0]==old['cues'][0]
    assert regenerated['seed']==123
    project['lines'][1]['words'][0]['start']=1.1
    assert validate_plan(project,old).model_dump()==old
    project['lines'][1]['words'][0]['word']='听见我'
    with pytest.raises(ValueError,match='不匹配'): validate_plan(project,old)


def test_legacy_plan_migrates_without_changing_design(project):
    from src.motion_director import legacy_source_signature, source_signature
    old=rule_plan(project).model_dump()
    old['source_signature']=legacy_source_signature(project)
    result=validate_plan(project,old)
    assert result.source_signature==source_signature(project)
    assert result.cues==rule_plan(project).cues


def test_legacy_text_plan_rebinds_timing_but_rejects_lyric_changes(project):
    from src.motion_director import legacy_source_signature, line_prompt_bundle
    old=rule_plan(project).model_dump()
    for cue in old['cues']:
        cue['poster']=line_prompt_bundle(project,cue['line_id'],old)['response_example']['cue']['poster']
    old['source_signature']=legacy_source_signature(project)
    project['lines'][1]['words'][0]['start']=1.1
    validate_plan(project,old)
    project['lines'][1]['words'][0]['word']='听见我'
    with pytest.raises(ValueError): validate_plan(project,old)


def test_single_line_prompt_uses_only_target_words_and_neighbors(project):
    from src.motion_director import line_prompt_bundle, line_response
    bundle=line_prompt_bundle(project,'line_0003',rule_plan(project).model_dump(),instruction='整句保留，强调这一刻')
    assert bundle['input']['target']['text']=='放大这一刻'
    assert [w['word_index'] for w in bundle['input']['target']['words']]==[0,1]
    assert len(bundle['input']['neighbors'])==2
    assert '终局视觉平衡' in bundle['prompt'] and '没有真正的三维' in bundle['prompt']
    response,groups=line_response(project,bundle['response_example'],'line_0003')
    assert groups[0]['start']==5 and groups[0]['end']==8
    assert response.cue.whole_line_visible

@pytest.mark.parametrize('bad',['missing','duplicate','reorder','rewrite','time','empty','hide'])
def test_single_line_phrase_validation(project,bad):
    from src.motion_director import line_prompt_bundle, line_response
    data=line_prompt_bundle(project,'line_0003')['response_example']
    data['cue'].pop('poster')
    data['cue']['groups']=[{'text':'放大这一刻','word_indices':[0,1],'action':'hold','emphasis':'','intensity':.5}]
    if bad=='missing':data['cue']['groups'][0]['word_indices']=[0]
    elif bad=='duplicate':data['cue']['groups'][0]['word_indices']=[0,0,1]
    elif bad=='reorder':data['cue']['groups'][0]['word_indices']=[1,0]
    elif bad=='rewrite':data['cue']['groups'][0]['text']='改写歌词'
    elif bad=='time':data['cue']['groups'][0]['start']=10
    elif bad=='empty':data['cue']['groups']=[]
    else:data['cue']['whole_line_visible']=False
    with pytest.raises(ValueError):line_response(project,data,'line_0003')


def test_poster_prompt_contract_and_legacy_compatibility(project):
    from src.motion_director import line_prompt_bundle, line_response
    bundle=line_prompt_bundle(project,'line_0003')
    schema=bundle['input']['output_schema']
    assert schema['$defs']['CuePlan']['anyOf'][1]['required']==['line_id','poster']
    assert not {'template','groups'} & schema['$defs']['CuePlan']['anyOf'][1]['properties'].keys()
    assert not {'template','groups'} & bundle['response_example']['cue'].keys()
    assert 'settle_fraction' in schema['$defs']['PosterNode']['properties']
    assert not {'start','x','y','fontSize','size'} & schema['$defs']['PosterNode']['properties'].keys()
    assert 'cumulative-entrances' in bundle['input']['capabilities']['poster_runtime']
    assert 'Remotion' not in bundle['prompt']
    assert '未锁定 cue' in llm_prompt(project)
    response,_=line_response(project,bundle['response_example'],'line_0003')
    assert response.cue.poster.visibility=='cumulative'
    assert response.cue.poster.status=='draft'
    validate_plan(project,rule_plan(project).model_dump())
    wordless=line_prompt_bundle(project,'line_0004')['response_example']
    assert line_response(project,wordless,'line_0004')[0].cue.poster.nodes[0].word_indices==[]


@pytest.mark.parametrize('bad',['coordinates','font_size','primary','duplicate','rewrite','fraction','time','emphasis','layout'])
def test_invalid_poster_design_rejected(project,bad):
    from src.motion_director import line_prompt_bundle, line_response
    data=line_prompt_bundle(project,'line_0003')['response_example']
    poster=data['cue']['poster'];node=poster['nodes'][0]
    if bad=='coordinates':node['x']=.8
    elif bad=='font_size':node['fontSize']=120
    elif bad=='primary':node['role']='support'
    elif bad=='duplicate':node['word_indices']=[0,0,1]
    elif bad=='rewrite':node['text']='篡改歌词'
    elif bad=='fraction':node['settle_fraction']=float('nan')
    elif bad=='time':node['start']=5
    elif bad=='emphasis':node['emphasis']='不存在'
    else:poster['layout']='unknown-grid'
    with pytest.raises(ValueError):line_response(project,data,'line_0003')


def test_rule_regeneration_preserves_visual_language(project):
    plan=rule_plan(project).model_dump()
    plan['visual_language']={'direction':'纸色与绿','background':'#eeeee6','foreground':'#20261e','accent':'#c1ee47','rhythm':'主歌轻，副歌突出'}
    assert rule_plan(project,plan).model_dump()['visual_language']==plan['visual_language']


def test_one_alignment_line_is_one_poster_despite_full_width_spaces():
    from src.motion_director import line_prompt_bundle, line_response
    text='天花板在脚下　地板在云端抽离'
    chars=list(text.replace('　',''))
    project={'lines':[{'text':text,'start':1,'end':14,'words':[{'word':ch,'start':i+1,'end':i+2} for i,ch in enumerate(chars)]}]}
    bundle=line_prompt_bundle(project,'line_0001')
    assert bundle['input']['target']['text']==text
    assert bundle['input']['capabilities']['poster_scope']['count']=='one-poster-per-line'
    assert '严格采用 alignment 的句界' in bundle['prompt']
    assert '不能发生在当前句的词组之间' in bundle['prompt']
    assert len(director_input(project)['lines'])==1
    response,_=line_response(project,bundle['response_example'],'line_0001')
    assert len(response.cue.poster.nodes)==1
    data=rule_plan(project).model_dump()
    data['cues'].append({**data['cues'][0],'line_id':'line_0001-part2'})
    with pytest.raises(ValueError,match='完整覆盖'):validate_plan(project,data)


def test_hold_reactivity_is_bounded_to_supported_intents_and_primary(project):
    from src.motion_director import line_prompt_bundle,line_response
    data=line_prompt_bundle(project,'line_0003')['response_example']
    node=data['cue']['poster']['nodes'][0]
    node.update(hold='drift',beat_reaction='pulse')
    assert line_response(project,data,'line_0003')[0].cue.poster.nodes[0].hold=='drift'
    node['beat_reaction']='glitch'
    with pytest.raises(ValueError):line_response(project,data,'line_0003')
    node.update(beat_reaction='pulse',role='secondary')
    with pytest.raises(ValueError):line_response(project,data,'line_0003')


def test_semantic_relations_round_trip_and_old_signatures_stay_valid(project):
    from src.motion_director import line_prompt_bundle,line_response,cue_signature
    import hashlib
    plan=rule_plan(project)
    bundle=line_prompt_bundle(project,'line_0003')
    poster=bundle['response_example']['cue']['poster']
    poster['nodes']=[{**poster['nodes'][0],'text':'放大','word_indices':[0]},
                     {**poster['nodes'][0],'text':'这一刻','word_indices':[1],'role':'secondary'}]
    poster['relations']=[{'kind':'guidance','node_indices':[0,1],'intent':'放大引导阅读焦点到这一刻'}]
    response,_=line_response(project,bundle['response_example'],'line_0003')
    plan.cues[1]=response.cue
    assert validate_plan(project,plan.model_dump()).cues[1].poster.relations[0].node_indices==[0,1]
    assert 'semantic_relations' in director_input(project)['capabilities']
    assert 'PosterRelation' in bundle['input']['output_schema']['$defs']
    empty=copy.deepcopy(bundle['response_example']);empty['cue']['poster'].pop('relations')
    old,_=line_response(project,empty,'line_0003');plan.cues[1]=old.cue
    legacy=old.cue.model_dump();legacy['poster'].pop('relations');legacy['poster'].pop('semantic_mode');legacy['poster'].pop('visual_intensity')
    expected=hashlib.sha256(json.dumps({'cue':legacy,'seed':plan.seed},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    assert cue_signature(plan,'line_0003')==expected


@pytest.mark.parametrize('bad',['negative','missing','duplicate','bool','unknown','coordinate','single_contrast'])
def test_invalid_semantic_relation_rejected(project,bad):
    from src.motion_director import line_prompt_bundle,line_response
    data=line_prompt_bundle(project,'line_0003')['response_example']
    relation={'kind':'spatial','node_indices':[0],'intent':'单块内部的空间意象'}
    if bad=='negative':relation['node_indices']=[-1]
    elif bad=='missing':relation['node_indices']=[1]
    elif bad=='duplicate':relation['node_indices']=[0,0]
    elif bad=='bool':relation['node_indices']=[True]
    elif bad=='unknown':relation['kind']='glitch'
    elif bad=='coordinate':relation['x']=100
    else:relation['kind']='contrast'
    data['cue']['poster']['relations']=[relation]
    with pytest.raises(ValueError):line_response(project,data,'line_0003')


def test_semantic_mode_is_optional_bounded_and_changes_cue_signature(project):
    from src.motion_director import line_prompt_bundle,line_response,cue_signature
    data=line_prompt_bundle(project,'line_0003')['response_example']
    plan=rule_plan(project);plan.cues[1]=line_response(project,data,'line_0003')[0].cue
    signature=cue_signature(plan,'line_0003')
    data['cue']['poster']['semantic_mode']='off'
    plan.cues[1]=line_response(project,data,'line_0003')[0].cue
    assert cue_signature(plan,'line_0003')!=signature
    data['cue']['poster']['semantic_mode']='unbounded'
    with pytest.raises(ValueError):line_response(project,data,'line_0003')


def test_prompt_envelopes_are_explicit(project):
    from src.motion_director import line_prompt_bundle
    prompt=line_prompt_bundle(project,'line_0003')['prompt']
    assert '顶层 version 必须为 motion-line-response-v1' in prompt
    assert '禁止顶层 seed、visual_language、cues' in prompt
    assert '输入为 null 时仍返回 null' in prompt
    assert '顶层 version 必须为 motion-plan-v1' in llm_prompt(project)


@pytest.mark.parametrize('text,focus,valid',[
    ('你不必 询问意义','不必询问',True),
    ('已经　开过了','已经开过',True),
    ('已经\n开过了','已经 开过',True),
    ('不必询问','不必　询问',True),
    ('New  York','New York',True),
    ('New\nYork','New　York',True),
    ('New York','NewYork',False),
    ('NewYork','New York',False),
    ('中文 AI 世界','中文AI',False),
    ('你不必询问意义','不必意义',False),
    ('山','形状',False),
    ('山','　',False),
])
def test_emphasis_whitespace_language_boundaries(text,focus,valid):
    from src.motion_director import emphasis_matches
    assert emphasis_matches(text,focus) is valid


def test_poster_emphasis_accepts_chinese_spaces_without_rewriting_source():
    from src.motion_director import line_prompt_bundle, line_response
    project={'lines':[{'text':'你不必 询问意义','start':1,'end':4,'words':[]}]}
    data=line_prompt_bundle(project,'line_0001')['response_example']
    data['cue']['poster']['nodes'][0]['emphasis']='不必询问'
    before=copy.deepcopy(data)
    response,_=line_response(project,data,'line_0001')
    assert response.cue.poster.nodes[0].text=='你不必 询问意义'
    assert response.cue.poster.nodes[0].emphasis=='不必询问'
    assert data==before
    data['cue']['poster']['nodes'][0]['emphasis']='不必意义'
    with pytest.raises(ValueError,match='line_0001.*不必意义'):
        line_response(project,data,'line_0001')


def test_experimental_prompt_requires_structure_and_focus_basis(project):
    assert '必须判定并匹配以下五种结构模型之一' in llm_prompt(project)
    assert '首句必须标明结构标签与 Primary 依据' in llm_prompt(project)


def test_single_line_parallel_context_reaches_past_an_explanation_line():
    from src.motion_director import line_prompt_bundle
    lyrics=['山 是山的形状','因为它 长成了山的形状','水 往低处流去','因为它 正在往低处流去']
    project={'lines':[{'text':text,'section':'Verse','start':i*4,'end':i*4+3,'words':[]} for i,text in enumerate(lyrics)]}
    previous=rule_plan(project).model_dump()
    previous['cues'][0]['poster']=line_prompt_bundle(project,'line_0001')['response_example']['cue']['poster']
    previous['cues'][0]['locked']=True
    before=copy.deepcopy(previous)
    bundle=line_prompt_bundle(project,'line_0003',previous)
    mountain=bundle['input']['neighbors'][0]
    assert mountain['line_id']=='line_0001'
    assert mountain['poster_context']['locked'] is True
    assert mountain['poster_context']['nodes'][0]['role']=='primary'
    assert 'word_indices' not in mountain['poster_context']['nodes'][0]
    assert 'words' not in mountain and 'start' not in mountain
    assert previous==before
    assert '邻句仅作上下文' in bundle['prompt']
    assert '首句必须标明结构标签与 Primary 依据' in bundle['prompt']
    assert 'hold 允许 none/drift' in bundle['prompt']
    assert 'schema 外字段' in bundle['prompt']


def test_visual_intensity_round_trip_and_bounded_values(project):
    from src.motion_director import line_prompt_bundle, line_response
    data=line_prompt_bundle(project,'line_0003')['response_example']
    for tier in ('auto','restrained','expanded','peak'):
        data['cue']['poster']['visual_intensity']=tier
        response,_=line_response(project,data,'line_0003')
        assert response.cue.poster.visual_intensity==tier
    data['cue']['poster']['visual_intensity']='unlimited'
    with pytest.raises(ValueError):
        line_response(project,data,'line_0003')


def test_new_direction_allows_breathing_drift(project):
    from src.motion_director import line_prompt_bundle,line_response,director_capabilities
    bundle=line_prompt_bundle(project,'line_0003')
    assert bundle['input']['output_schema']['$defs']['ActivePosterNode']['properties']['hold']['enum']==['none', 'drift']
    assert 'drift' in director_capabilities()['poster_runtime']
    data=bundle['response_example'];data['cue']['poster']['nodes'][0]['hold']='drift'
    assert line_response(project,data,'line_0003')[0].cue.poster.nodes[0].hold=='drift'


@pytest.mark.parametrize('chunks', [
    ['这一秒我变得像山岳般', '巨大'],
    ['别试图呼救', '你的声音本身就是一种', '幻梦'],
    ['下一秒又缩进', '一滴泪水的', '缝隙'],
])
def test_independent_semantic_focus_preserves_complete_alignment(chunks):
    from src.motion_director import line_prompt_bundle, line_response
    text = ''.join(chunks)
    words = [{'word': char, 'start': i * .2, 'end': (i + 1) * .2}
             for i, char in enumerate(text)]
    song = {'duration': len(words) * .2, 'lines': [
        {'text': text, 'start': 0, 'end': len(words) * .2,
         'section': 'Verse', 'words': words}]}
    response = line_prompt_bundle(song, 'line_0001')['response_example']
    nodes, offset = [], 0
    for i, chunk in enumerate(chunks):
        primary = i == len(chunks) - 1
        nodes.append({'text': chunk, 'word_indices': list(range(offset, offset + len(chunk))),
                      'role': 'primary' if primary else 'secondary',
                      'emphasis': chunk if primary else '',
                      'color_role': 'accent' if primary else 'foreground',
                      'entrance': 'scale-in' if primary else 'fade', 'hold': 'none'})
        offset += len(chunk)
    response['cue']['poster']['nodes'] = nodes
    response['cue']['poster']['visual_intensity'] = 'expanded'
    validated, _ = line_response(song, response, 'line_0001')
    assert validated.cue.poster.nodes[-1].text == chunks[-1]
    assert [i for node in validated.cue.poster.nodes for i in node.word_indices] == list(range(len(words)))
    # A semantic split still cannot drop sung text or invent a word boundary.
    response['cue']['poster']['nodes'][0]['word_indices'].pop()
    with pytest.raises(ValueError):
        line_response(song, response, 'line_0001')
