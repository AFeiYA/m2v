const {test}=require('node:test'),assert=require('node:assert/strict');
const esbuild=require('../motion/node_modules/esbuild'),path=require('node:path');
const result=esbuild.buildSync({entryPoints:[path.join(__dirname,'../motion/src/marketing-demo.ts')],bundle:true,platform:'node',format:'cjs',write:false});
const moduleValue={exports:{}};new Function('module','exports',result.outputFiles[0].text)(moduleValue,moduleValue.exports);
const {demoScene}=moduleValue.exports;
test('public samples use real studio formats, complete word timings and no private media',()=>{
 for(const [mode,visual,width,height] of [['apple','apple',720,1280],['karaoke','tv',1280,720],['poster','kinetic',720,1280]]){
  const scene=demoScene(mode),p=scene.project;
  assert.equal(scene.options.visualMode,visual);assert.equal(scene.width,width);assert.equal(scene.height,height);
  assert.equal(p.song_cover,undefined);assert.deepEqual(p.analysis.beats,[]);
  for(const line of p.lines){
   assert.equal(line.words.map(w=>w.word).join(' '),line.text);
   assert.ok(line.words.every(w=>w.start>=line.start&&w.end<=line.end&&w.end>w.start));
   const cue=p.motion_plan.cues.find(c=>c.line_id===line.id);
   assert.deepEqual(cue.poster.nodes.flatMap(n=>n.word_indices),line.words.map((_,i)=>i));
  }
 }
});
