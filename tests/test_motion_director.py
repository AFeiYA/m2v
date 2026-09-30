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


def test_alignment_edit_invalidates_plan_and_locks_survive_regeneration(project):
    old=rule_plan(project).model_dump();old['seed']=123;old['cues'][0].update(locked=True,palette='neon',intensity=.1)
    regenerated=rule_plan(project,old).model_dump()
    assert regenerated['cues'][0]==old['cues'][0]
    assert regenerated['seed']==123
    project['lines'][1]['words'][0]['start']=1.1
    with pytest.raises(ValueError,match='已经变化'): validate_plan(project,old)


def test_single_line_prompt_uses_only_target_words_and_neighbors(project):
    from src.motion_director import line_prompt_bundle, line_response
    bundle=line_prompt_bundle(project,'line_0003',rule_plan(project).model_dump(),instruction='整句保留，强调这一刻')
    assert bundle['input']['target']['text']=='放大这一刻'
    assert [w['word_index'] for w in bundle['input']['target']['words']]==[0,1]
    assert len(bundle['input']['neighbors'])==2
    assert '最终海报' in bundle['prompt'] and '没有真正的三维' in bundle['prompt']
    response,groups=line_response(project,bundle['response_example'],'line_0003')
    assert groups[0]['start']==5 and groups[0]['end']==8
    assert response.cue.whole_line_visible

@pytest.mark.parametrize('bad',['missing','duplicate','reorder','rewrite','time','empty','hide'])
def test_single_line_phrase_validation(project,bad):
    from src.motion_director import line_prompt_bundle, line_response
    data=line_prompt_bundle(project,'line_0003')['response_example']
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
    assert schema['$defs']['CuePlan']['allOf'][0]['else']['required']==['poster']
    assert 'settle_fraction' in schema['$defs']['PosterNode']['properties']
    assert not {'start','x','y','fontSize','size'} & schema['$defs']['PosterNode']['properties'].keys()
    assert 'poster-layout' in bundle['input']['capabilities']['design_only']
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
