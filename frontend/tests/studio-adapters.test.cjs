const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../studio-adapters.js'),'utf8');
function setup(){
 const loads=[],messages=[],timers=new Map(),nodes=new Map(),states=[];let counter=0;
 const frame=id=>({dataset:{},contentWindow:{postMessage:data=>messages.push(data)},setAttribute(){},
  get src(){return this.url||'about:blank';},set src(value){this.url=value;loads.push({id,url:value});}});
 nodes.set('iframe-lyric-editor',frame('lyric'));nodes.set('iframe-motion-studio',frame('motion'));
 const node=id=>{if(!nodes.has(id))nodes.set(id,{hidden:true,dataset:{}});return nodes.get(id);};
 const window={location:{origin:'https://app.example'},addEventListener(){},m2vStore:{setEditorState:(name,state)=>states.push({name,...state})}};
 const context={window,document:{getElementById:node},module:{exports:{}},Date,
  setTimeout:fn=>{timers.set(++counter,fn);return counter;},clearTimeout:id=>timers.delete(id)};
 vm.runInNewContext(source,context);
 const studios=window.m2vStudios;
 function send(name,type,extra={}){const adapter=studios[name];return adapter.receive({origin:window.location.origin,source:adapter.frame().contentWindow,
  data:{type,studio:name,requestId:adapter.requestId,songId:adapter.currentSongId,...extra}});}
 return {studios,loads,messages,timers,nodes,node,window,send,states};
}
for(const name of ['lyric','motion'])test(`${name}: returning to the same song never reloads or sends another load command`,async()=>{
 const s=setup(),editor=s.studios[name];await editor.mount(null,{songId:'song'});
 await editor.activate({songId:'song'});await editor.activate({songId:'song'});
 assert.equal(s.loads.length,1);assert.equal(s.messages.length,0);
 assert.ok(new URL(s.loads[0].url,'https://app.example').searchParams.get('_workspace'));
 s.send(name,'M2V_STUDIO_READY');assert.equal(editor.phase,'loading');
 s.send(name,'M2V_STUDIO_LOADED');assert.equal(editor.phase,'ready');
 await editor.activate({songId:'song'});assert.equal(s.loads.length,1);
 editor.pause();assert.equal(s.messages.at(-1).type,'M2V_STUDIO_PAUSE');
 editor.destroy();assert.equal(editor.frame().src,'about:blank');assert.equal(s.timers.size,0);
});
test('foreign origins, sibling frames and old request IDs cannot report successful loading',async()=>{
 const s=setup(),editor=s.studios.motion;await editor.activate({songId:'a'});const old=editor.requestId;
 await editor.activate({songId:'b'});
 const valid={origin:s.window.location.origin,source:editor.frame().contentWindow,data:{type:'M2V_STUDIO_LOADED',studio:'motion',requestId:editor.requestId,songId:'b'}};
 assert.equal(editor.receive({...valid,origin:'https://other.example'}),false);
 assert.equal(editor.receive({...valid,source:s.studios.lyric.frame().contentWindow}),false);
 assert.equal(editor.receive({...valid,data:{...valid.data,requestId:old,songId:'a'}}),false);
 assert.equal(editor.phase,'loading');assert.equal(editor.currentSongId,'b');
 assert.equal(editor.receive(valid),true);assert.equal(editor.phase,'ready');
});
test('timeout and failed-page states provide an explicit retry with a fresh request',async()=>{
 const s=setup(),editor=s.studios.motion;await editor.activate({songId:'song'});
 const old=editor.requestId;[...s.timers.values()][0]();
 assert.equal(editor.phase,'error');assert.equal(s.node('studio-retry-motion').hidden,false);
 await s.node('studio-retry-motion').onclick();
 assert.notEqual(editor.requestId,old);assert.equal(s.loads.length,2);
 s.send('motion','M2V_STUDIO_ERROR',{message:'Alignment not available'});
 assert.match(s.node('studio-status-text-motion').textContent,/Alignment not available/);
});
test('saved lyrics invalidate Motion only once and dirty design prevents destructive refresh',async()=>{
 const s=setup();await s.studios.lyric.activate({songId:'song'});s.send('lyric','M2V_STUDIO_LOADED');
 await s.studios.motion.activate({songId:'song'});s.send('motion','M2V_STUDIO_LOADED');
 s.send('motion','M2V_STUDIO_STATE',{dirty:true});
 s.send('lyric','M2V_STUDIO_SAVED',{dirty:false});
 assert.equal(await s.studios.motion.activate({songId:'song'}),false);assert.equal(s.loads.length,2);
 s.send('motion','M2V_STUDIO_STATE',{dirty:false});
 await s.studios.motion.activate({songId:'song'});assert.equal(s.loads.length,3);
 s.send('motion','M2V_STUDIO_LOADED');await s.studios.motion.activate({songId:'song'});
 assert.equal(s.loads.length,3);
});
test('unsaved lyrics block Motion and switching songs while Library remains available',async()=>{
 const s=setup();await s.studios.lyric.activate({songId:'song'});s.send('lyric','M2V_STUDIO_LOADED',{dirty:true});
 assert.equal(s.window.m2vCanOpenStudio('motion','song'),false);
 assert.equal(s.window.m2vCanOpenStudio('lyric','other'),false);
 assert.equal(s.window.m2vCanOpenStudio('lyric','song'),true);
 s.send('lyric','M2V_STUDIO_STATE',{dirty:false});
 assert.equal(s.window.m2vCanOpenStudio('motion','song'),true);
});
test('completed Motion exports refresh account credits without overwriting editor state',async()=>{
 const s=setup();let refreshed=0;s.window.m2vRefreshExportState=()=>refreshed++;
 const editor=s.studios.motion;await editor.activate({songId:'song'});
 s.send('motion','M2V_STUDIO_LOADED');s.send('motion','M2V_STUDIO_STATE',{dirty:true});
 assert.equal(s.send('motion','M2V_STUDIO_EXPORTED'),true);assert.equal(refreshed,1);assert.equal(editor.dirty,true);
 assert.equal(s.send('motion','M2V_STUDIO_EXPORTED',{requestId:'stale'}),false);
 assert.equal(s.send('motion','M2V_STUDIO_EXPORTED',{songId:'other'}),false);assert.equal(refreshed,1);
 await s.studios.lyric.activate({songId:'song'});assert.equal(s.send('lyric','M2V_STUDIO_EXPORTED'),false);assert.equal(refreshed,1);
});
