const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const esbuild=require('../motion/node_modules/esbuild');
function load(file){const code=esbuild.buildSync({entryPoints:[path.join(__dirname,'../motion/src',file)],bundle:true,platform:'node',format:'cjs',write:false}).outputFiles[0].text;const m={exports:{}};new Function('module','exports',code)(m,m.exports);return m.exports;}
const {compileHighlightSpans,highlightState}=load('karaoke.ts');
const {segmentWordByWord,compilePoster}=load('poster-layout.ts');
const measure=(text,size)=>({width:text.length*size,advance:text.length*size,ascent:size*.8,descent:size*.2});
test('merging many English words keeps spaces, punctuation, original indices and all text',()=>{
 const tokens=['One','two','three','four','five','six','seven','eight','nine','ten','eleven.'];
 const line={text:tokens.join(' '),words:tokens.map((word,i)=>({word,start:i,end:i+1})),start:0,end:11};
 const blocks=segmentWordByWord(line,3);
 assert.equal(blocks.map(b=>b.text).join(' '),line.text);
 assert.deepEqual(blocks.flatMap(b=>b.word_indices),tokens.map((_,i)=>i));
});
test('word spans preserve apostrophes, punctuation and measured positions after wrapping',()=>{
 const words=[{word:"Don't",start:1,end:2},{word:'stop',start:3,end:4},{word:'now',start:4,end:5}];
 const rows=[{text:"Don't stop,",x:10,y:20},{text:'now!',x:30,y:40}];
 const spans=compileHighlightSpans(words,[0,1,2],rows,10,400,measure);
 assert.equal(spans.length,3);assert.equal(spans[1].x,70);assert.equal(spans[2].row,1);assert.equal(spans[2].x,30);
 assert.deepEqual(highlightState(spans[0],.9,'sweep'),{progress:0,active:false});
 assert.equal(highlightState(spans[0],1.5,'sweep').progress,.5);
 assert.deepEqual(highlightState(spans[0],2.5,'sweep'),{progress:1,active:false});
 assert.equal(highlightState(spans[1],2.5,'sweep').progress,0);
 assert.equal(highlightState(spans[1],3.01,'word').progress,1);
});
test('a compound Chinese word wrapping over two rows wipes in reading order',()=>{
 const spans=compileHighlightSpans([{word:'世界',start:1,end:3}],[0],[{text:'世',x:0,y:10},{text:'界',x:0,y:30}],10,400,measure);
 assert.equal(spans.length,2);
 assert.equal(highlightState(spans[0],1.5,'sweep').progress,.5);
 assert.equal(highlightState(spans[1],1.5,'sweep').progress,0);
 assert.equal(highlightState(spans[0],2.5,'sweep').progress,1);
 assert.equal(highlightState(spans[1],2.5,'sweep').progress,.5);
});
test('mismatched text and RTL fall back without inventing timing or highlighting another word',()=>{
 assert.deepEqual(compileHighlightSpans([{word:'one',start:0,end:1}],[0],[{text:'other',x:0,y:10}],10,400,measure),[]);
 assert.deepEqual(compileHighlightSpans([{word:'سلام',start:0,end:1}],[0],[{text:'سلام',x:0,y:10}],10,400,measure),[]);
});
test('karaoke keeps geometry and timing, removes entrance movement and pulse in both formats',()=>{
 const line={id:'l',text:'Never could I forget',start:1,end:6,words:['Never','could','I','forget'].map((word,i)=>({word,start:1+i,end:2+i}))};
 const base={palette:'impact',poster:{version:'motion-poster-direction-v1',status:'draft',intent:'One sentence',layout:'center-stack',background:'#0d120a',accent:'#c8ff00',motif:'none',visibility:'cumulative',final_hold:'available-tail',transition_out:'cut',transition_note:'',nodes:[{text:line.text,word_indices:[0,1,2,3],role:'primary',emphasis:'',color_role:'accent',entrance:'slide-up',settle_fraction:.25,beat_reaction:'pulse'}]}};
 for(const [w,h] of [[1280,720],[720,1280]]){
  const original=compilePoster(line,base,w,h,measure);
  const highlighted=compilePoster(line,{...base,poster:{...base.poster,highlight:'sweep'}},w,h,measure);
  assert.deepEqual(highlighted.nodes.map(n=>n.rows),original.nodes.map(n=>n.rows));
  const n=highlighted.nodes[0];assert.equal(n.start,line.start);assert.equal(n.settled,line.start);assert.equal(n.entrance,'none');assert.equal(n.beat_reaction,'none');
  assert.deepEqual(n.highlight.spans.map(s=>s.start),line.words.map(word=>word.start));
  assert.equal(n.highlight.foreground,n.color);assert.equal(n.highlight.foreground,base.poster.accent);
  const supporting=compilePoster(line,{...base,poster:{...base.poster,highlight:'sweep',nodes:base.poster.nodes.map(n=>({...n,color_role:'muted'}))}},w,h,measure).nodes[0];
  assert.equal(supporting.highlight.foreground,supporting.color);assert.notEqual(supporting.highlight.foreground,base.poster.accent);
  assert.equal(base.poster.highlight,undefined);
 }
});
test('zero-duration words and reverse seeking have deterministic finite state',()=>{
 const span={start:2,end:2};assert.deepEqual(highlightState(span,2,'sweep'),{progress:1,active:false});
 assert.equal(highlightState(span,1,'sweep').progress,0);assert.equal(highlightState(span,4,'sweep').progress,1);
});

test('AI redesign preserves the independently selected highlight and locked cues',()=>{
 const {preserveHighlight}=load('local-design.ts');
 const before={cues:[{line_id:'a',poster:{highlight:'sweep'}}]};
 const incoming={cues:[{line_id:'a',poster:{highlight:'none'}},{line_id:'b',locked:true,poster:{highlight:'none'}}]};
 const updated=preserveHighlight(incoming,before,'word');
 assert.equal(updated.cues[0].poster.highlight,'sweep');assert.equal(updated.cues[1].poster.highlight,'none');
 assert.equal(incoming.cues[0].poster.highlight,'none');
});
