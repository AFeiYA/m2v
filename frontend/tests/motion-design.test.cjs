const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const esbuild=require('../motion/node_modules/esbuild');
const code=esbuild.buildSync({stdin:{contents:"export * from './motion-design'; export * from './render-plan'; export {normalizeProject,resolveVisualMode} from './model'; export {automaticPoster} from './poster-layout';",resolveDir:path.join(__dirname,'../motion/src')},bundle:true,platform:'node',format:'cjs',write:false}).outputFiles[0].text;
const entry={exports:{}};new Function('module','exports',code)(entry,entry.exports);
const {createMotionDesign,selectMode,changeTheme,modeTheme,modeOptions,compileRenderPlan,normalizeProject,resolveVisualMode,automaticPoster}=entry.exports;
function fixture(){
 const project=normalizeProject({title:'Song',duration:20,lines:[{text:'Never could',start:2,end:6,words:[{word:'Never',start:2,end:4},{word:'could',start:4,end:6}]},{text:'Find my way',start:9,end:12,words:[]}]});
 const design=createMotionDesign();design.modes.kinetic.plan={version:'motion-plan-v1',source_signature:'test',seed:17,cues:project.lines.map(line=>({line_id:line.id,palette:'impact',locked:false,template:'phrase-rise',layout:'center',intensity:.5,emphasis:'',poster:automaticPoster(line)}))};
 design.modes.kinetic.plan.cues[0].poster.highlight='none';design.modes.kinetic.plan.cues[0].poster.layout='staggered';
 project.motion_design=design;
 return {project,design};
}
const measure=(text,size)=>({width:text.length*size*.5,advance:text.length*size*.5,ascent:size*.8,descent:size*.2});
test('switching modes and aspect ratios preserves the authored plan and shared sources',()=>{
 const {project,design}=fixture(),before=JSON.stringify(design),source=JSON.stringify(project);
 let selected=structuredClone(selectMode(design,'apple'));selected.modes.apple.aspect='16:9';selected=selectMode(selected,'tv');selected=selectMode(selected,'kinetic');
 assert.equal(JSON.stringify(selected.modes.kinetic),JSON.stringify(design.modes.kinetic));
 assert.equal(selected.modes.apple.aspect,'16:9');assert.equal(resolveVisualMode('apple','16:9'),'apple');assert.equal(resolveVisualMode('tv','9:16'),'tv');
 // Selection only changes the active mode; it does not regenerate lyrics or posters.
 assert.equal(JSON.stringify(project),source);
 assert.equal(JSON.parse(before).modes.kinetic.plan.cues[0].poster.highlight,'none');
});
test('mode theme overrides remain local and an explicit all-mode theme clears overrides',()=>{
 const {design}=fixture();let next=changeTheme(selectMode(design,'apple'),{palette:'neon',background:'light'},'mode');
 assert.equal(modeTheme(next,'apple').palette,'neon');assert.equal(modeTheme(next,'tv').palette,'impact');
 assert.equal(design.modes.apple.theme,null);assert.equal(JSON.stringify(next.modes.kinetic.plan),JSON.stringify(design.modes.kinetic.plan));
 next=changeTheme(next,{palette:'sunset',background:'dark'},'all');
 for(const mode of ['kinetic','apple','tv'])assert.equal(modeTheme(next,mode).palette,'sunset');
});
test('one compiler resolves per-mode themes for preview and every export surface',()=>{
 const {project,design}=fixture();design.modes.apple.theme={palette:'neon',background:'light'};design.modes.tv.theme={palette:'sunset',background:'dark'};
 const before=JSON.stringify(project);
 for(const mode of ['kinetic','apple','tv'])for(const [width,height] of [[1280,720],[720,1280]]){
  const options=modeOptions(design,mode),preview=compileRenderPlan(project,options,width,height,measure);
  const exported=compileRenderPlan(JSON.parse(JSON.stringify(project)),{visualMode:mode},width,height,measure);
  assert.deepEqual(exported,preview);assert.equal(preview.mode,mode);
  if(mode==='kinetic')assert.equal(preview.layouts.length,2);
  if(mode==='apple')assert.ok(preview.appleLayout.palette.background);
  if(mode==='tv')assert.ok(preview.ktvLayout);
 }
 assert.equal(JSON.stringify(project),before);
});
test('stream settings survive JSON round trips and change only their own layout',()=>{
 const {project,design}=fixture();const base=compileRenderPlan(project,{visualMode:'tv'},1280,720,measure);
 design.modes.tv.preview_seconds=1;design.modes.apple.focus_y=.5;design.modes.apple.font_scale=1.2;
 project.motion_design=JSON.parse(JSON.stringify(design));
 const changed=compileRenderPlan(project,{visualMode:'tv'},1280,720,measure);
 assert.notEqual(changed.ktvLayout.lines[0].previewStart,base.ktvLayout.lines[0].previewStart);
 assert.equal(compileRenderPlan(project,{visualMode:'apple'},720,1280,measure).appleLayout.focusY,.5);
 assert.equal(project.motion_design.modes.kinetic.plan.cues[0].poster.layout,'staggered');
});
