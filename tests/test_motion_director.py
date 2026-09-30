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
