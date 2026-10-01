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

test('compact stacks keep the primary anchor and enforce typographic hierarchy',()=>{
 const line={id:'line_1',text:'欢迎来到 我的兔子洞 这里没有 所谓的成功',start:0,end:8,words:['欢迎来到','我的兔子洞','这里没有','所谓的成功'].map((word,i)=>({word,start:i*2,end:i*2+2}))};
 for(const [W,H] of [[1280,720],[720,1280]])for(const primary of [0,1,2,3]){
  const poster=automaticPoster(line);poster.nodes.forEach((n,i)=>n.role=i===primary?'primary':'secondary');
  const cue={line_id:line.id,template:'phrase-rise' as const,layout:'center' as const,palette:'impact' as const,intensity:.5,emphasis:'',locked:false,poster};
  const p=compilePoster(line,cue,W,H,measure),hero=p.nodes[primary];
  assert.ok(Math.abs(hero.y+hero.height/2-H*.5)<=H*.2);
  assert.ok(p.nodes.at(-1)!.y+p.nodes.at(-1)!.height-p.nodes[0].y<=H*(H>W?.44:.56)+1e-6);
  for(const [i,n] of p.nodes.entries())if(i!==primary)assert.ok(n.fontSize<=hero.fontSize*.55+1e-6);
 }
});

test('song stage persists across gaps and repeated posters retain composition without changing source',async()=>{
 const {compileSongPosters,stageAt}=await import('./poster-layout.ts');
 const p=normalizeProject({lines:[{text:'失重 失重',start:1,end:3,words:[{word:'失重',start:1,end:2},{word:'失重',start:2,end:3}]},{text:'失重 失重',start:5,end:7,words:[{word:'失重',start:5,end:6},{word:'失重',start:6,end:7}]}]});
 p.motion_plan={version:'motion-plan-v1',source_signature:'test',seed:1,cues:p.lines.map((line,i)=>{
  const poster=automaticPoster(line);poster.background=i?'#ffffff':'#111111';poster.layout=i?'staggered':'hero-stack';
  return {line_id:line.id,template:'phrase-rise',layout:'center',palette:'impact',intensity:.5,emphasis:'',locked:false,poster};
 })};
 const original=JSON.stringify(p),layouts=compileSongPosters(p,1280,720,measure);
 assert.equal(JSON.stringify(p),original);
 assert.equal(layouts[0].background,layouts[1].background);
 assert.equal(layouts[0].layout,layouts[1].layout);
 assert.deepEqual(layouts[0].nodes.map(n=>n.rows),layouts[1].nodes.map(n=>n.rows));
 assert.equal(layouts[1].nodes[0].start,5);
 assert.equal(stageAt(layouts,4),layouts[0]);assert.equal(stageAt(layouts,0),layouts[0]);
 assert.equal(posterOpacity(stageAt(layouts,4)!,4),1);assert.equal(posterOpacity(stageAt(layouts,4.3)!,4.3),0);
});


test('handover holds the poster then retires support before primary without changing alignment',async()=>{
 const {bindHandover,posterExitOpacity,visiblePosterAt}=await import('./poster-layout.ts');
 const line={id:'line_1',text:'引导 核心',start:1,end:3,words:[{word:'引导',start:1,end:2},{word:'核心',start:2,end:3}]};
 const poster=automaticPoster(line);poster.transition_out='fade';poster.nodes[0].role='secondary';poster.nodes[1].role='primary';
 const cue={line_id:line.id,template:'phrase-rise' as const,layout:'center' as const,palette:'impact' as const,intensity:.5,emphasis:'',locked:false,poster};
 const p=compilePoster(line,cue,1280,720,measure);bindHandover(p,4,8);
 assert.equal(p.end,3);assert.equal(p.handover?.visible_end,4);
 assert.equal(posterExitOpacity(p,p.nodes[0],3.2),1);
 const t=p.handover!.exit_start+.05;
 assert.ok(posterExitOpacity(p,p.nodes[0],t)<posterExitOpacity(p,p.nodes[1],t));
 assert.equal(visiblePosterAt([p],3.5),p);assert.equal(visiblePosterAt([p],4),undefined);
 bindHandover(p,3,8);assert.equal(p.handover?.mode,'cut');assert.equal(posterOpacity(p,2.99),1);
 bindHandover(p,12,15);assert.ok(p.handover!.visible_end<=4.2);
 bindHandover(p,null,3);assert.equal(p.handover?.visible_end,3);
 bindHandover(p,2.8,8);assert.equal(p.handover?.visible_end,2.8);
});


test('portrait uses readable short rows and an upper reading field with quiet edge decoration',async()=>{
 const {posterRings}=await import('./poster-layout.ts');
 const line={id:'line_1',text:'别试图呼救你的声音 本身就是一种 幻梦',start:1,end:9,words:['别试图呼救你的声音','本身就是一种','幻梦'].map((word,i)=>({word,start:1+i*2,end:3+i*2}))};
 const poster=automaticPoster(line);poster.nodes.forEach((n,i)=>n.role=i===2?'primary':i===0?'secondary':'support');
 const cue={line_id:line.id,template:'phrase-rise' as const,layout:'center' as const,palette:'impact' as const,intensity:.5,emphasis:'',locked:false,poster};
 const p=compilePoster(line,cue,720,1280,measure),hero=p.nodes[2];
 assert.ok(Math.abs(hero.y+hero.height/2-1280*.42)<1e-6);
 assert.ok(hero.rows.length===1);assert.ok(p.nodes[0].fontSize>=720*.06);
 assert.ok(p.nodes.every(n=>n.y>=1280*.16&&n.y+n.height<=1280*.74));
 assert.ok(posterRings(720,1280).every(r=>r.opacity<=.25&&r.cx>720*.9&&r.rx===r.ry));
});


test('portrait titles fit four/five characters on one line and avoid orphan endings',()=>{
 for(const W of [360,720])for(const text of ['兔子洞','都像泡沫','所谓的成功','常识碎成琉璃','五彩斑斓废气']){
  const line={id:'title',text,start:1,end:6,words:[{word:text,start:1,end:6}]};
  const poster=automaticPoster(line);if(text==='五彩斑斓废气')poster.nodes[0].emphasis='五彩斑斓';
  const cue={line_id:line.id,template:'phrase-rise' as const,layout:'center' as const,palette:'impact' as const,intensity:.5,emphasis:'',locked:false,poster};
  const n=compilePoster(line,cue,W,W*16/9,measure).nodes[0];
  assert.equal(n.rows.map(r=>r.text).join(''),text);
  if(Array.from(text).length<=5)assert.equal(n.rows.length,1);
  else assert.ok(n.rows.every(r=>Array.from(r.text).length>=2));
  assert.ok(n.fontSize>=W*.13);
  for(const r of n.rows)assert.ok(measure(r.text,n.fontSize).width<=n.width+1e-6);
  if(text==='五彩斑斓废气')assert.deepEqual(n.rows.map(r=>r.text),['五彩斑斓','废气']);
 }
});

test('semantic arrangement changes hierarchy hints and motion without mutating lyrics or timing',async()=>{
 const {resolveSemanticDirection}=await import('./poster-layout.ts');
 const line={id:'semantic',text:'欢迎来到 兔子洞 这里没有 成功',start:1,end:9,words:['欢迎来到','兔子洞','这里没有','成功'].map((word,i)=>({word,start:1+i*2,end:3+i*2}))};
 const poster=automaticPoster(line);poster.nodes.forEach((n,i)=>n.role=i===1?'primary':'secondary');
 poster.relations=[{kind:'guidance',node_indices:[0,1],intent:'邀请进入兔子洞'},{kind:'negation',node_indices:[2,3],intent:'否定成功'}];
 const original=JSON.stringify(poster),resolved=resolveSemanticDirection(poster);
 assert.equal(JSON.stringify(poster),original);assert.equal(resolved.design.nodes[0].entrance,'fade');assert.equal(resolved.design.nodes[1].entrance,'scale-in');
 assert.equal(resolved.design.nodes[2].color_role,'muted');assert.equal(resolved.design.nodes[3].color_role,'foreground');
 const cue={line_id:line.id,template:'phrase-rise' as const,layout:'center' as const,palette:'impact' as const,intensity:.5,emphasis:'',locked:false,poster};
 for(const [W,H] of [[1280,720],[720,1280]]){
  const p=compilePoster(line,cue,W,H,measure);assert.deepEqual(p.nodes.map(n=>n.start),line.words.map(w=>w.start));
  assert.deepEqual(p.nodes.map(n=>n.text),poster.nodes.map(n=>n.text));assert.equal(p.nodes.filter(n=>n.role==='primary').length,1);
  assert.ok(p.semantic_arrangement.every(a=>a.status==='applied'));
  for(const n of p.nodes){assert.ok(n.x>=W*.05&&n.x+n.width<=W*.95);assert.ok(n.y>=0&&n.y+n.height<=H);}
 }
 poster.semantic_mode='off';assert.deepEqual(resolveSemanticDirection(poster).design.nodes,poster.nodes);
 assert.ok(resolveSemanticDirection(poster).applications.every(a=>a.status==='disabled'));
});

test('contrast spatial and repeated motions are bounded and dense vocals still win',async()=>{
 const {resolveSemanticDirection}=await import('./poster-layout.ts');
 const line={id:'semantic',text:'失重 失重',start:1,end:1.5,words:[{word:'失重',start:1,end:1.2},{word:'失重',start:1.2,end:1.5}]};
 const poster=automaticPoster(line);poster.nodes[0].entrance='scale-in';poster.nodes[1].entrance='slide-left';
 poster.relations=[{kind:'spatial',node_indices:[0,1],intent:'失重空间'},{kind:'contrast',node_indices:[0,1],intent:'对照'},{kind:'repetition',node_indices:[0,1],intent:'重复'}];
 const resolved=resolveSemanticDirection(poster);assert.equal(resolved.design.nodes[0].entrance,resolved.design.nodes[1].entrance);
 assert.ok(resolved.hints.every(h=>Math.abs(h.offset)<=.018&&h.scale<=1.15));
 const cue={line_id:line.id,template:'phrase-rise' as const,layout:'center' as const,palette:'impact' as const,intensity:.5,emphasis:'',locked:false,poster};
 const p=compilePoster(line,cue,720,1280,measure);assert.ok(p.nodes.every(n=>n.entrance==='fade'&&n.hold==='none'));
 poster.relations=[{kind:'repetition',node_indices:[0],intent:'块内部重复'}];assert.equal(resolveSemanticDirection(poster).applications[0].status,'limited');
});

import {checkImportScope} from './import-scope.ts';
test('import scope rejects mismatched envelopes before applying any plan',()=>{
  assert.doesNotThrow(()=>checkImportScope({version:'motion-plan-v1'},'song'));
  assert.doesNotThrow(()=>checkImportScope({version:'motion-line-response-v1'},'line'));
  assert.throws(()=>checkImportScope({version:'motion-plan-v1'},'line'),/收到的是整曲方案/);
  assert.throws(()=>checkImportScope({version:'motion-line-response-v1'},'song'),/收到的是单句方案/);
  assert.throws(()=>checkImportScope([], 'line'),/完整的导演 JSON/);
  assert.throws(()=>checkImportScope({version:'wrong'},'song'),/不支持/);
});


import {displayText} from './poster-layout.ts';
test('Chinese display spacing is optional while English and mixed word boundaries stay visible',()=>{
 assert.equal(displayText('并不是　 为了吹向你'),'并不是为了吹向你');
 assert.equal(displayText('New　 York'), 'New York');
 assert.equal(displayText('中文　 AI　 世界'), '中文 AI 世界');
 for(const text of ['并不是 为了吹向你','是山的形状','New York never stops dreaming','中文 AI 世界','Supercalifragilisticexpialidocious']){
  const line={id:'line_1',text,start:1,end:8,words:[{word:text,start:1,end:8}]};
  const before=JSON.stringify(line);
  for(const [W,H] of [[1280,720],[720,1280]]){
   const p=compilePoster(line,undefined,W,H,measure),n=p.nodes[0];
   assert.equal(n.text,text);
   assert.equal(n.start,1);
   assert.equal(n.rows.map(r=>r.text).join('').replace(/\s/g,''),text.replace(/\s/g,''));
   for(const row of n.rows)assert.ok(measure(row.text,n.fontSize).width<=W*.782+1e-6);
   if(text==='并不是 为了吹向你'||text==='是山的形状')assert.ok(n.rows.every(r=>Array.from(r.text).length>1));
   if(text==='New York never stops dreaming')for(const word of text.split(' '))assert.ok(n.rows.some(r=>r.text.includes(word)));
  }
  assert.equal(JSON.stringify(line),before);
 }
});


test('the saved water lyric never leaves a lone final character in either aspect',()=>{
 const line={id:'line_1',text:'水 往低处流去',start:0,end:4,words:['水','往','低','处','流','去'].map((word,i)=>({word,start:i*.5,end:i*.5+.5}))};
 const poster=automaticPoster(line);poster.layout='staggered';poster.nodes[1].emphasis='低处流去';
 for(const [W,H] of [[1280,720],[720,1280]]){
  const p=compilePoster(line,{poster} as any,W,H,measure);
  assert.deepEqual(p.nodes[1].rows.map(r=>r.text),['往低处流去']);
 }
});

test('visual tiers fit both formats, preserve anchors and respect known sections',()=>{
 const line={id:'tier',text:'幻梦',section:'Verse',start:1,end:7,words:[{word:'幻梦',start:1,end:7}]},poster=automaticPoster(line);
 poster.nodes[0].entrance='slide-up';
 const cue={line_id:line.id,template:'phrase-rise' as const,layout:'center' as const,palette:'impact' as const,intensity:.5,emphasis:'',locked:false,poster};
 for(const [W,H] of [[1280,720],[720,1280]]){
  const results=(['restrained','expanded','peak'] as const).map(tier=>{poster.visual_intensity=tier;return compilePoster(line,cue,W,H,measure);});
  assert.ok(results[0].nodes[0].fontSize<results[1].nodes[0].fontSize&&results[1].nodes[0].fontSize<results[2].nodes[0].fontSize);
  assert.ok(posterNodeState(results[0].nodes[0],1,H).dy<posterNodeState(results[2].nodes[0],1,H).dy);
  for(const p of results){const n=p.nodes[0];assert.equal(n.start,1);assert.equal(n.settled,results[0].nodes[0].settled);assert.ok(n.y>=H*.12&&n.y+n.height<=H*.88);for(const row of n.rows)assert.ok(row.x>=0&&row.x+measure(row.text,n.fontSize).width<=W);}
 }
 poster.visual_intensity='auto';assert.equal(compilePoster(line,cue,1280,720,measure).visual_intensity,'restrained');
 assert.equal(compilePoster({...line,section:'Chorus'},cue,1280,720,measure).visual_intensity,'expanded');
 assert.equal(compilePoster({...line,section:''},cue,1280,720,measure).visual_intensity,'expanded');
 poster.visual_intensity='peak';const dense=compilePoster({...line,end:1.2,words:[{word:'幻梦',start:1,end:1.2}]},cue,1280,720,measure);
 assert.equal(dense.visual_intensity,'expanded');assert.equal(dense.nodes[0].entrance,'fade');
});

test('legacy breathing is disabled in compiled and old nodes at every frame',async()=>{
 const {posterHoldState}=await import('./poster-layout.ts');
 const line={id:'breath',text:'幻梦',start:0,end:10,words:[{word:'幻梦',start:0,end:10}]},poster=automaticPoster(line);
 poster.nodes[0].hold='drift';
 const cue={line_id:line.id,template:'phrase-rise' as const,layout:'center' as const,palette:'impact' as const,intensity:.5,emphasis:'',locked:false,poster};
 for(const [W,H] of [[1280,720],[720,1280]]){
  const n=compilePoster(line,cue,W,H,measure).nodes[0],complete=n.settled;assert.equal(n.hold,'none');n.hold='drift';
  assert.equal(posterHoldState(n,complete-.1,complete,W,H).drift,0);assert.equal(posterHoldState(n,complete,complete,W,H).drift,0);
  for(let i=0;i<600;i++){const t=complete+i/60,state=posterHoldState(n,t,complete,W,H);assert.equal(state.drift,0);assert.deepEqual(posterHoldState(n,t,complete,W,H),state);assert.equal(state.pulse,1);}
 }
});
