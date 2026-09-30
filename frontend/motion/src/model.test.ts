import test from 'node:test';
import assert from 'node:assert/strict';
import { beatPhase, featuresAt, normalizeProject } from './model.ts';

test('the visual beat follows detected phase rather than zero-based BPM', () => {
  const beats=[0.23,0.73,1.23,1.73];
  assert.equal(beatPhase(0,beats,120),1);
  assert.equal(beatPhase(0.23,beats,120),0);
  assert.ok(Math.abs(beatPhase(0.48,beats,120)-0.5)<1e-6);
  assert.equal(beatPhase(0.73,beats,120),0);
});

test('a project preserves Chinese lines, words, sections and audible hits', () => {
  const p=normalizeProject({title:'测试歌曲',lines:[{text:'听见你',start:1,end:2,section:'Chorus',words:[
    {word:'听',start:1,end:1.3},{word:'见',start:1.3,end:1.6},{word:'你',start:1.6,end:2}
  ]}],analysis:{bpm:120,beats:[0.23,0.73,1.23],drum_hits:[{time:1.3,type:'kick'}],energy_curve:[{time:1,energy:.2},{time:2,energy:.8}]}});
  assert.equal(p.lines[0].text,'听见你');
  assert.equal(p.lines[0].section,'Chorus');
  assert.deepEqual(p.lines[0].words.map(w=>w.word),['听','见','你']);
  assert.ok(featuresAt(p,1.3).kick>.9);
  assert.ok(Math.abs(featuresAt(p,1.5).energy-.5)<.01);
});

test('bad timing fails clearly instead of silently rendering the wrong lyric', () => {
  assert.throws(()=>normalizeProject({lines:[{text:'错',start:2,end:1}]}),/起止时间无效/);
});

test('silence and missing beats never generate a fallback pulse',()=>{
  assert.equal(beatPhase(1,[],120),1);
  const p=normalizeProject({lines:[{text:'静',start:0,end:2}],analysis:{bpm:0,beats:[]}});
  assert.equal(p.analysis.bpm,0);assert.equal(featuresAt(p,1).impact,0);
});

test('zero-length annotations keep following line IDs stable',()=>{
  const p=normalizeProject({lines:[{text:'标记',start:0,end:0},{text:'歌词',start:1,end:2}]});
  assert.equal(p.lines.length,1);assert.equal(p.lines[0].id,'line_0002');
  assert.equal(normalizeProject(p).lines[0].id,'line_0002');
});

test('phrase motion boundaries come only from alignment',async()=>{
  const {groupAt}=await import('./model.ts');
  const p=normalizeProject({lines:[{text:'听见你',start:1,end:3,words:[{word:'听',start:1,end:1.4},{word:'见',start:1.4,end:2},{word:'你',start:2,end:3}]}]});
  const cue={line_id:p.lines[0].id,template:'phrase-rise' as const,layout:'center' as const,palette:'impact' as const,intensity:.5,emphasis:'',locked:false,groups:[{text:'听见',word_indices:[0,1],action:'reveal' as const,intensity:.5,emphasis:''},{text:'你',word_indices:[2],action:'hold' as const,intensity:.5,emphasis:''}]};
  assert.equal(groupAt(p.lines[0],cue,.9),undefined);
  assert.equal(groupAt(p.lines[0],cue,1.4)?.text,'听见');
  assert.equal(groupAt(p.lines[0],cue,2)?.text,'你');
  assert.equal(groupAt(p.lines[0],cue,3),undefined);
});
