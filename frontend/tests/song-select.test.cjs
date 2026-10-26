const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function setup(){
 const values={m2v_user:'alice'},window={};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../local/song-select.js'),'utf8'),{window,localStorage:{getItem:key=>values[key]||null}});
 return {load:window.m2vSongSelect.load,values};
}
test('native dropdown loads beyond the first 50 songs using latest available lyrics',async()=>{
 const {load}=setup(),calls=[];
 const songs=await load(async url=>{
  calls.push(url);
  return url.endsWith('page=1')?{songs:Array.from({length:50},(_,i)=>({current_task_id:'latest-'+i,title:'Song '+i})),total:52}
   :{songs:[{current_task_id:'latest-50',title:'Last song'},{current_task_id:null,title:'Pending'}],total:52};
 });
 assert.equal(calls.length,2);assert.equal(songs.length,51);assert.equal(songs[50].current_task_id,'latest-50');
});
test('duplicate tasks across changing library pages appear only once',async()=>{
 const {load}=setup();let page=0;
 const songs=await load(async()=>({songs:[{current_task_id:'same'}],total:++page===1?51:51}));
 assert.equal(songs.length,1);assert.equal(page,2);
});
test('account changes discard the entire pending dropdown list',async()=>{
 const {load,values}=setup();
 await assert.rejects(load(async()=>{values.m2v_user='bob';return {songs:[{current_task_id:'private'}],total:1};}),/Account changed/);
});
test('library errors propagate instead of silently showing a partial list',async()=>{
 const {load}=setup();let page=0;
 await assert.rejects(load(async()=>{if(++page===2)throw Error('Offline');return {songs:[{current_task_id:'first'}],total:51};}),/Offline/);
});
test('editors keep visible native dropdowns and their unsaved-change guards',()=>{
 for(const name of ['index.html','motion_studio_director.html','motion_studio.html']){
  const html=fs.readFileSync(path.join(__dirname,'../local',name),'utf8');
  assert.doesNotMatch(html,/song-picker\.(js|css)/);assert.match(html,/song-select\.js/);
 }
 const common=fs.readFileSync(path.join(__dirname,'../local/common.js'),'utf8');
 assert.match(common,/Switch songs and discard unsaved lyric changes/);
 assert.match(common,/dom.songSelect.value=String\(state.allFiles.indexOf\(state.currentFile\)\)/);
 const studio=fs.readFileSync(path.join(__dirname,'../motion/src/studio.ts'),'utf8');
 assert.match(studio,/Switch songs and discard unsaved preview changes/);
 assert.doesNotMatch(studio,/m2vSongPicker/);
});
