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
const measure=(text:string,size:number,weight:number=400)=>({width:Array.from(text).length*size,ascent:size*.85,descent:size*.15});
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

test('phrases with punctuation fit single lines in landscape and never orphan trailing punctuation',()=>{
 const line={id:'punc',text:'还没有变成声音。',start:0,end:4,words:[{word:'还没有变成声音。',start:0,end:4}]};
 const cue={line_id:line.id,template:'phrase-rise' as const,layout:'center' as const,palette:'impact' as const,intensity:.6,emphasis:'',locked:false,poster:{
  version:'motion-poster-direction-v1' as const,status:'draft' as const,layout:'center-stack' as const,intent:'测试',background:'#121316',accent:'#F5C518',motif:'none' as const,visibility:'cumulative' as const,final_hold:'available-tail' as const,transition_out:'fade' as const,transition_note:'',nodes:[{
   text:'还没有变成声音。',word_indices:[0],role:'primary' as const,emphasis:'',color_role:'accent' as const,entrance:'fade' as const,settle_fraction:.25
  }]
 }};
 const landscape=compilePoster(line,cue,1280,720,measure);
 assert.deepEqual(landscape.nodes[0].rows.map(r=>r.text),['还没有变成声音。']);
 const portrait=compilePoster(line,cue,720,1280,measure);
 assert.ok(portrait.nodes[0].rows.length<=2);
 assert.ok(portrait.nodes[0].rows.every(r=>!/^[，。！？、；：”’）》〉】｝〕…—~～,.!?;:)\]}"']/u.test(r.text)));
 assert.ok(portrait.nodes[0].rows.every(r=>/[\p{Script=Han}\p{Script=Latin}\p{N}]/u.test(r.text)));
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

test('short lines with four or fewer characters stay on one line without stacking',()=>{
 for(const W of [1280, 720]){
  const H = W === 1280 ? 720 : 1280;
  for(const text of ['本来挺亮', '绝不妥协', '巨大', '一']){
   const line={id:'short',text,start:1,end:4,words:[{word:text,start:1,end:4}]};
   const poster=automaticPoster(line);
   assert.equal(poster.nodes.length, 1);
   const cue={line_id:line.id,template:'phrase-rise' as const,layout:'center' as const,palette:'impact' as const,intensity:.5,emphasis:'',locked:false,poster};
   const p=compilePoster(line,cue,W,H,measure);
   assert.equal(p.nodes.length, 1);
   assert.equal(p.nodes[0].rows.length, 1);
   assert.equal(p.nodes[0].rows[0].text, text);
   assert.ok(measure(p.nodes[0].rows[0].text, p.nodes[0].fontSize).width <= p.nodes[0].width + 1e-6);
  }
 }
});

test('intro title compiles to a single line and animates smoothly during intro gap',async()=>{
 const {compileIntroTitle, introTitleState}=await import('./poster-layout.ts');
 const project=normalizeProject({
  title:'观察者效应',
  lines:[{text:'第一句歌词',start:5.0,end:8.0,words:[{word:'第一句歌词',start:5.0,end:8.0}]}],
  duration:60
 });
 for(const [W,H] of [[1280,720],[720,1280]]){
  const intro=compileIntroTitle(project, W, H, measure);
  assert.ok(intro !== null);
  assert.equal(intro.text, '观察者效应');
  assert.equal(intro.start, 0);
  assert.equal(intro.end, 5.0);
  assert.ok(intro.settled > 0 && intro.settled < intro.exitStart);
  assert.ok(intro.exitStart < intro.end);
  const textWidth=measure(intro.text, intro.fontSize, intro.weight).width;
  assert.ok(textWidth <= W * 0.82 + 1e-6);

  const atStart = introTitleState(intro, 0, H);
  assert.equal(atStart.alpha, 0);

  const atMid = introTitleState(intro, 2.5, H);
  assert.equal(atMid.alpha, 1);
  assert.equal(atMid.scale, 1);

  const atExit = introTitleState(intro, 4.9, H);
  assert.ok(atExit.alpha > 0 && atExit.alpha < 1);

  const atAfter = introTitleState(intro, 5.0, H);
  assert.equal(atAfter.alpha, 0);
 }

 const immediateProject=normalizeProject({
  title:'测试歌曲',
  lines:[{text:'第一句歌词',start:0.1,end:3.0,words:[{word:'第一句歌词',start:0.1,end:3.0}]}],
  duration:60
 });
 assert.equal(compileIntroTitle(immediateProject, 1280, 720, measure), null);
});

test('automaticPoster generates 5 default non-LLM layout presets with anti-orphan phrasing', () => {
  const frenchLine = {
    id: 'line_fr',
    text: 'Reste encore un peu avec moi',
    start: 1,
    end: 4,
    words: ['Reste ', 'encore ', 'un ', 'peu ', 'avec ', 'moi'].map((w, i) => ({ word: w, start: 1 + i * 0.5, end: 1.5 + i * 0.5 }))
  };

  // 1. smart preset for French
  const smartFr = automaticPoster(frenchLine, 'impact', 'smart');
  assert.equal(smartFr.nodes.length, 2);
  assert.equal(smartFr.nodes[0].text, 'Reste encore ');
  assert.equal(smartFr.nodes[1].text, 'un peu avec moi');
  assert.equal(smartFr.nodes[0].role, 'secondary');
  assert.equal(smartFr.nodes[1].role, 'primary');
  assert.equal(smartFr.nodes[1].color_role, 'accent');

  // 2. single preset
  const singleFr = automaticPoster(frenchLine, 'impact', 'single');
  assert.equal(singleFr.nodes.length, 1);
  assert.equal(singleFr.nodes[0].text, 'Reste encore un peu avec moi');
  assert.equal(singleFr.nodes[0].role, 'primary');
  assert.equal(singleFr.layout, 'center-stack');

  // 3. two-stack preset
  const twoStackFr = automaticPoster(frenchLine, 'impact', 'two-stack');
  assert.equal(twoStackFr.nodes.length, 2);
  assert.equal(twoStackFr.nodes.map(n => n.text).join(''), 'Reste encore un peu avec moi');
  assert.equal(twoStackFr.nodes[1].role, 'primary');

  // 4. three-stack preset
  const threeStackFr = automaticPoster(frenchLine, 'impact', 'three-stack');
  assert.equal(threeStackFr.nodes.length, 3);
  assert.equal(threeStackFr.nodes.map(n => n.text).join(''), 'Reste encore un peu avec moi');
  assert.equal(threeStackFr.nodes[2].role, 'primary');
  assert.equal(threeStackFr.nodes[1].role, 'support');

  // 5. word-by-word preset
  const wordByWordFr = automaticPoster(frenchLine, 'impact', 'word-by-word');
  assert.equal(wordByWordFr.nodes.length, 6);
  assert.equal(wordByWordFr.nodes.filter(n => n.role === 'primary').length, 1);

  // Short English line: 3 words -> single line
  const shortEnLine = {
    id: 'line_en_short',
    text: 'Wherever we land',
    start: 0,
    end: 2,
    words: ['Wherever ', 'we ', 'land'].map((w, i) => ({ word: w, start: i * 0.6, end: (i + 1) * 0.6 }))
  };
  const smartEnShort = automaticPoster(shortEnLine, 'impact', 'smart');
  assert.equal(smartEnShort.nodes.length, 1);
  assert.equal(smartEnShort.nodes[0].text, 'Wherever we land');

  // Chinese lines: short, long
  const zhShort = {
    id: 'zh_1',
    text: '本来挺亮',
    start: 0,
    end: 2,
    words: ['本来挺亮'].map(w => ({ word: w, start: 0, end: 2 }))
  };
  assert.equal(automaticPoster(zhShort, 'impact', 'smart').nodes.length, 1);

  const zhLong = {
    id: 'zh_2',
    text: '在这场永不谢幕的社交博弈',
    start: 0,
    end: 4,
    words: ['在这场', '永不谢幕的', '社交博弈'].map((w, i) => ({ word: w, start: i, end: i + 1 }))
  };
  assert.equal(automaticPoster(zhLong, 'impact', 'smart').nodes.length, 3);

  // Chinese word-by-word strike: never single sentence, correctly segments into rhythmic words
  const zhMoonLine = {
    id: 'zh_moon',
    text: '月亮在云层里像一枚褪色的银币',
    start: 0,
    end: 4,
    words: '月亮在云层里像一枚褪色的银币'.split('').map((ch, i) => ({ word: ch, start: i * 0.25, end: (i + 1) * 0.25 }))
  };
  const wordByWordZh = automaticPoster(zhMoonLine, 'impact', 'word-by-word');
  assert.ok(wordByWordZh.nodes.length >= 4 && wordByWordZh.nodes.length <= 8, `Expected 4-8 blocks for Chinese word-by-word, got ${wordByWordZh.nodes.length}`);
  assert.equal(wordByWordZh.nodes.map(n => n.text).join(''), '月亮在云层里像一枚褪色的银币');
  assert.deepEqual(wordByWordZh.nodes.flatMap(n => n.word_indices), Array.from({ length: 14 }, (_, i) => i));
  assert.equal(wordByWordZh.nodes.filter(n => n.role === 'primary').length, 1);

  const zhIfLine = {
    id: 'zh_if',
    text: '因为如果你没在听',
    start: 0,
    end: 3,
    words: '因为如果你没在听'.split('').map((ch, i) => ({ word: ch, start: i * 0.3, end: (i + 1) * 0.3 }))
  };
  const wordByWordIf = automaticPoster(zhIfLine, 'impact', 'word-by-word');
  assert.ok(wordByWordIf.nodes.length >= 4 && wordByWordIf.nodes.length <= 8);
  assert.equal(wordByWordIf.nodes.map(n => n.text).join(''), '因为如果你没在听');
});

test('theme palettes provide distinct colors and dark/light tones', () => {
  const line = {
    id: 'test_theme',
    text: '秋日市集',
    start: 0,
    end: 2,
    words: [{ word: '秋日', start: 0, end: 1 }, { word: '市集', start: 1, end: 2 }]
  };

  const sunset = automaticPoster(line, 'sunset', 'smart');
  assert.equal(sunset.accent, '#ff5028');
  assert.equal(sunset.background, '#140907');

  const amberLight = automaticPoster(line, 'amber', 'smart', 'light');
  assert.equal(amberLight.accent, '#8a5500');
  assert.equal(amberLight.background, '#faf5ea');

  const violetDark = automaticPoster(line, 'violet', 'smart', 'dark');
  assert.equal(violetDark.accent, '#c084fc');
  assert.equal(violetDark.background, '#100818');

  const sakura = automaticPoster(line, 'sakura', 'smart');
  assert.equal(sakura.accent, '#ff5c8a');

  const mono = automaticPoster(line, 'monochrome', 'smart');
  assert.equal(mono.accent, '#ffffff');

  const randomPoster = automaticPoster(line, 'random', 'smart');
  assert.ok(/^#[0-9a-fA-F]{6}$/.test(randomPoster.accent));
  assert.ok(/^#[0-9a-fA-F]{6}$/.test(randomPoster.background));
});

test('random layout preset produces valid posters with complete coverage and varied alignments', () => {
  const line = {
    id: 'rand_line',
    text: 'Every road a story told',
    start: 0,
    end: 3,
    words: ['Every ', 'road ', 'a ', 'story ', 'told'].map((w, i) => ({ word: w, start: i * 0.6, end: (i + 1) * 0.6 }))
  };

  const seenLayouts = new Set<string>();
  for (let i = 0; i < 30; i++) {
    const poster = automaticPoster(line, 'impact', 'random');
    assert.ok(poster.nodes.length >= 1 && poster.nodes.length <= 5);
    assert.equal(poster.nodes.filter(n => n.role === 'primary').length, 1);
    const covered = poster.nodes.flatMap(n => n.word_indices);
    assert.deepEqual(covered, [0, 1, 2, 3, 4]);
    seenLayouts.add(poster.layout);
  }
  // Across 30 random generations, multiple alignments must be sampled
  assert.ok(seenLayouts.size >= 2, `Expected at least 2 distinct layout alignments, saw ${Array.from(seenLayouts).join(', ')}`);
});

test('stack layouts correctly position rows across center, left, right, and staggered alignments', () => {
  const line = {
    id: 'align_test',
    text: 'Night call',
    start: 0,
    end: 2,
    words: [{ word: 'Night ', start: 0, end: 1 }, { word: 'call', start: 1, end: 2 }]
  };
  const mockMeasure = (text: string, size: number) => ({
    width: text.trim().length * size * 0.6,
    ascent: size * 0.8,
    descent: size * 0.2
  });

  // 1. Hero stack (left-aligned)
  const leftPoster = compilePoster(line, {
    line_id: line.id, template: 'phrase-rise', layout: 'left', palette: 'impact', intensity: 0.5, emphasis: '', locked: false,
    poster: { ...automaticPoster(line, 'impact', 'two-stack', 'dark', 'hero-stack'), layout: 'hero-stack' }
  }, 1280, 720, mockMeasure);
  assert.equal(leftPoster.layout, 'hero-stack');
  // In hero-stack, all rows start at the same left coordinate
  assert.equal(leftPoster.nodes[0].rows[0].x, leftPoster.nodes[1].rows[0].x);

  // 2. Right stack (right-aligned)
  const rightPoster = compilePoster(line, {
    line_id: line.id, template: 'phrase-rise', layout: 'left', palette: 'impact', intensity: 0.5, emphasis: '', locked: false,
    poster: { ...automaticPoster(line, 'impact', 'two-stack', 'dark', 'right-stack'), layout: 'right-stack' }
  }, 1280, 720, mockMeasure);
  assert.equal(rightPoster.layout, 'right-stack');
  // In right-stack, the right edges of the rows must align
  const r0Right = rightPoster.nodes[0].rows[0].x + mockMeasure(rightPoster.nodes[0].rows[0].text, rightPoster.nodes[0].fontSize).width;
  const r1Right = rightPoster.nodes[1].rows[0].x + mockMeasure(rightPoster.nodes[1].rows[0].text, rightPoster.nodes[1].fontSize).width;
  assert.ok(Math.abs(r0Right - r1Right) < 1, `Expected aligned right edges: ${r0Right} vs ${r1Right}`);

  // 3. Staggered
  const stagPoster = compilePoster(line, {
    line_id: line.id, template: 'phrase-rise', layout: 'left', palette: 'impact', intensity: 0.5, emphasis: '', locked: false,
    poster: { ...automaticPoster(line, 'impact', 'two-stack', 'dark', 'staggered'), layout: 'staggered' }
  }, 1280, 720, mockMeasure);
  assert.equal(stagPoster.layout, 'staggered');
  // Node 0 should be left-aligned and Node 1 should be right-aligned
  assert.ok(stagPoster.nodes[0].rows[0].x !== stagPoster.nodes[1].rows[0].x);
});

test('song identity uses measured cover and respects original lyric timeline',async()=>{
 const {compileSongLayout,songLayoutAt}=await import('./song-layout.ts');
 const project=normalizeProject({title:'旧名',duration:15,song_identity:{version:'motion-song-identity-v1',title:'兔子洞',artist:'Luca',style:'editorial',show_intro:true,show_signature:true,show_section:true,show_outro:true},lines:[{text:'欢迎来到',start:3,end:10,words:[],section:'VERSE'}]});
 assert.equal(project.title,'兔子洞');
 const measure=(text:string,size:number)=>({width:Array.from(text).length*size,ascent:size*.8,descent:size*.2});
 for(const [W,H] of [[1280,720],[720,1280]]){
  const layout=compileSongLayout(project,W,H,measure)!;
  assert.equal(songLayoutAt(layout,1).cover,true);
  assert.equal(songLayoutAt(layout,3).cover,false);
  assert.equal(songLayoutAt(layout,3).section,'VERSE');
  assert.equal(songLayoutAt(layout,12).cover,true);
  assert.equal(songLayoutAt(layout,15).cover,false);
  for(const text of [...layout.cover,...layout.header]){
   const w=measure(text.text,text.fontSize).width;
   const left=text.anchor==='middle'?text.x-w/2:text.anchor==='end'?text.x-w:text.x;
   assert.ok(left>=W*.06&&left+w<=W*.94);
  }
 }
 project.song_identity!.style='none';assert.equal(compileSongLayout(project,720,1280,measure),null);
 project.song_identity!.style='minimal';project.lines[0].start=0;project.lines[0].end=15;
 const short=compileSongLayout(project,720,1280,measure)!;
 assert.equal(short.introEnd,0);assert.equal(short.outroStart,15);
});

test('long multilingual song credits fit both formats without fabricated author',async()=>{
 const {compileSongLayout}=await import('./song-layout.ts');
 const measure=(text:string,size:number)=>({width:Array.from(text).length*size,ascent:size*.8,descent:size*.2});
 for(const title of ['所有的真理都被漆成了金色的借口','Welcome to my rabbit hole and a world beyond reality'])for(const [W,H] of [[1280,720],[720,1280]]){
  const p=normalizeProject({title,duration:15,song_identity:{version:'motion-song-identity-v1',title,artist:'',style:'editorial',show_intro:true,show_signature:true,show_section:false,show_outro:true},lines:[{text:'test',start:3,end:12,words:[]}]});
  const layout=compileSongLayout(p,W,H,measure)!;
  assert.ok(layout.cover.length<=2);
  assert.equal(layout.header.length,1);
  for(const row of layout.cover)assert.ok(measure(row.text,row.fontSize).width<=W*.82+.01);
 }
});

test('artwork crop covers each frame and cover composition leaves room for title',async()=>{
 const {compileSongLayout,coverPlacement,coverOpacityAt}=await import('./song-layout.ts');
 const p=normalizeProject({duration:20,song_identity:{title:'兔子洞',artist:'Luca',style:'editorial',show_intro:true,show_signature:true,show_section:true,show_outro:true,cover_mode:'background',cover_x:0,cover_y:100,cover_zoom:1.5},song_cover:{data_url:'data:image/jpeg;base64,test',width:500,height:1000,source:'suno'},lines:[{text:'欢迎',start:4,end:12,words:[]}]});
 const measure=(text:string,size:number)=>({width:text.length*size,ascent:size*.8,descent:size*.2});
 for(const [W,H] of [[1280,720],[720,1280]]){
  const layout=compileSongLayout(p,W,H,measure)!;
  assert.ok(layout.artwork);
  const image=coverPlacement(p,{x:0,y:0,width:W,height:H})!;
  assert.ok(image.x<=0&&image.y<=0&&image.x+image.width>=W&&image.y+image.height>=H);
  const card=layout.artwork!;
  assert.ok(card.x>=0&&card.y>=0&&card.x+card.width<=W&&card.y+card.height<=H);
  if(H>W)assert.ok(layout.cover[0].y-layout.cover[0].fontSize>card.y+card.height);
  else assert.ok(layout.cover[0].x-measure(layout.cover[0].text,layout.cover[0].fontSize).width/2>card.x+card.width);
  assert.ok(coverOpacityAt(layout,2)>coverOpacityAt(layout,7));
  assert.equal(coverOpacityAt(layout,7),.14);
 }
 p.song_identity!.cover_mode='none';assert.equal(coverPlacement(p,{x:0,y:0,width:720,height:1280}),null);
 assert.equal(compileSongLayout(p,720,1280,measure)!.artwork,undefined);
});
