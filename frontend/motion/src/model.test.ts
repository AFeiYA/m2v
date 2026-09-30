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

import {compilePoster,automaticPoster,posterNodeState,posterOpacity} from './poster-layout.ts';
const measure=(text:string,size:number)=>({width:Array.from(text).length*size,ascent:size*.85,descent:size*.15});
test('poster layout fits long Chinese text and many blocks in both aspect ratios',()=>{
  const line={id:'line_1',text:'甲'.repeat(120),start:0,end:12,words:Array.from({length:12},(_,i)=>({word:'甲'.repeat(10),start:i,end:i+1}))};
  const poster=automaticPoster(line);poster.nodes=line.words.map((w,i)=>({text:w.word,word_indices:[i],role:i===3?'primary':'secondary',emphasis:'',color_role:'foreground',entrance:'slide-up',settle_fraction:.25}));
  for(const [W,H] of [[1280,720],[720,1280]])for(const layout of ['hero-stack','center-stack','staggered'] as const){
    poster.layout=layout;const cue={line_id:line.id,template:'phrase-rise' as const,layout:'center' as const,palette:'impact' as const,intensity:.5,emphasis:'',locked:false,poster};
    const result=compilePoster(line,cue,W,H,measure);
    for(const [i,n] of result.nodes.entries()){
      assert.ok(n.fontSize>0);assert.ok(n.x>=W*.05&&n.x+n.width<=W*.95+1e-6);
      assert.ok(n.y>=H*.05&&n.y+n.height<=H*.95+1e-6);
      if(i)assert.ok(result.nodes[i-1].y+result.nodes[i-1].height<=n.y);
      for(const row of n.rows){const m=measure(row.text,n.fontSize);assert.ok(row.x+m.width<=n.x+n.width+1e-6);assert.ok(row.y-m.ascent>=n.y-1e-6&&row.y+m.descent<=n.y+n.height+1e-6);}
    }
  }
});
test('poster blocks enter on alignment anchors and stay at their final positions',()=>{
  const line={id:'line_1',text:'天花板在脚下　地板在云端抽离',start:1,end:5,words:[{word:'天花板在脚下',start:1,end:3},{word:'地板在云端抽离',start:3,end:5}]};
  const result=compilePoster(line,undefined,1280,720,measure);assert.equal(result.nodes.length,2);
  const [first,last]=result.nodes;
  assert.equal(posterNodeState(last,2.99,720).alpha,0);
  assert.equal(posterNodeState(first,first.start,720).alpha,0);
  assert.deepEqual(posterNodeState(first,first.settled,720),{alpha:1,dx:0,dy:0,scale:1});
  assert.deepEqual(posterNodeState(first,4.99,720),{alpha:1,dx:0,dy:0,scale:1});
  assert.deepEqual(posterNodeState(last,last.settled,720),{alpha:1,dx:0,dy:0,scale:1});
  assert.equal(posterOpacity(result,4.99),1);assert.equal(posterOpacity(result,5),0);
  assert.deepEqual(compilePoster(line,undefined,1280,720,measure),result);
});
test('wordless and zero-length final anchors never invent time beyond the line',()=>{
  const line={id:'line_1',text:'余音',start:1,end:2,words:[]};const p=compilePoster(line,undefined,720,1280,measure);
  assert.equal(p.nodes[0].start,1);assert.ok(p.nodes[0].settled<2);
  line.words=[{word:'余音',start:2,end:2}] as never;
  const late=compilePoster(line,undefined,720,1280,measure);assert.equal(late.nodes[0].settled,2);
});
test('dense lyrics suppress movement and hold effects to prioritize reading',()=>{
 const line={id:'line_1',text:'快速演唱测试词组',start:0,end:.5,words:[{word:'快速演唱测试词组',start:0,end:.5}]};
 const poster=automaticPoster(line);poster.nodes[0].entrance='scale-in';poster.nodes[0].hold='drift';poster.nodes[0].beat_reaction='pulse';
 const cue={line_id:line.id,template:'phrase-rise' as const,layout:'center' as const,palette:'impact' as const,intensity:.5,emphasis:'',locked:false,poster};
 const n=compilePoster(line,cue,1280,720,measure).nodes[0];
 assert.equal(n.entrance,'fade');assert.equal(n.hold,'none');assert.equal(n.beat_reaction,'none');
});
