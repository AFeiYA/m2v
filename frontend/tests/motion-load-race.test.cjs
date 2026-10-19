const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const esbuild=require('../motion/node_modules/esbuild');
const source=fs.readFileSync(path.join(__dirname,'../motion/src/studio.ts'),'utf8')+'\nexport {load,refreshSourceInfo,rules,previewPalette,saveAll,editIdentity,exportVideo}; export const getDraft=()=>plan;';
const code=esbuild.transformSync(source,{loader:'ts',format:'cjs',target:'es2022'}).code;
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function setup(){
 const writes=[],saves=[],renders=[];
 const nodes=new Map(),pending=new Map();
 const node=()=>({value:'',style:{},dataset:{},checked:false,hidden:false,children:[],textContent:'',
  setAttribute(k,v){this[k]=v;},addEventListener(name,handler){this[name]=handler;},replaceChildren(){this.children=[];},append(v){this.children.push(v);},
  querySelectorAll(){return [];},getContext(){return {};},classList:{toggle(){return false;}}});
 const document={getElementById(id){if(!nodes.has(id)){const n=node();n.value=({preset:'impact','theme-bg':'auto','default-layout-preset':'smart',aspect:'16:9',resolution:'720',bloom:'.7',shake:'.65'})[id]||'';nodes.set(id,n);}return nodes.get(id);},querySelectorAll(){return [];},createElement:node,body:node()};
 class Audio{currentTime=0;src='';pause(){}load(){}addEventListener(){}}
 class RemotionPreview{renderAt(){}dispose(){}}
 const service={cloudService:()=>false,motionUrl:p=>'/'+p,downloadService:url=>url,motionJson:async (name,method,body)=>{
  if(method==='PUT'){writes.push({name,body});const d=deferred();saves.push(d);return d.promise;}
  if(name==='projects'||name.startsWith('exports?'))return [];
  if(name==='director/config')return {configured:false};
  if(name==='source/refresh')return {identity:{title:'Fresh title',artist:'Fresh artist',source:'suno-cache'},cover:{data_url:'fresh-cover',source:'suno'}};
  if(name.startsWith('project?'))return pending.get(new URLSearchParams(name.split('?')[1]).get('project_id')).promise;
  if(name==='render'&&method==='POST'){renders.push(body);return {id:`job-${renders.length}`};}
  if(name.startsWith('render/job-'))return {id:name.split('/')[1],status:'done',frames:100,total:100,error:''};
  throw Error(name);
 }};
 const compiled=esbuild.buildSync({entryPoints:[path.join(__dirname,'../motion/src/local-design.ts')],bundle:true,platform:'node',format:'cjs',write:false}).outputFiles[0].text;
 const design={exports:{}};new Function('module','exports',compiled)(design,design.exports);
 const requireStub=name=>name.includes('local-design')?design.exports:name.includes('service-api')?service:name.includes('remotion-preview')?{RemotionPreview}:name.includes('/model')?{defaults:{},normalizeProject:p=>p,renderSize:()=>({width:720,height:1280}),buildExportClips:()=>[{id:'full',title:'Full song',available:true,start_time:0,end_time:null},{id:'chorus',title:'Chorus',available:true,start_time:20,end_time:35}]}:{};
 const context={module:{exports:{}},require:requireStub,document,window:{addEventListener(){},confirm:()=>false},MutationObserver:class{observe(){}},Audio,structuredClone,
  URL,URLSearchParams,Blob,FormData,setTimeout,requestAnimationFrame(){},console,location:{search:''}};
 vm.createContext(context);vm.runInContext(code,context);
 function request(id){const d=deferred();pending.set(id,d);return d;}
 function result(title){return {project:{title,duration:2,lines:[],analysis:{energy_curve:[],beats:[]}},plan:null,audio_url:title+'.mp3'};}
 return {api:context.module.exports,nodes,request,result,writes,saves,renders,context,design:design.exports};
}
test('a late previous song response cannot replace current credits or artwork',async()=>{
 const s=setup(),old=s.request('old'),current=s.request('current');
 const a=s.api.load('old'),b=s.api.load('current');
 current.resolve(s.result('Current title'));await b;
 await s.api.refreshSourceInfo();
 old.resolve(s.result('Old title'));await a;
 assert.equal(s.nodes.get('track-name').textContent,'Fresh title');
 assert.equal(s.nodes.get('song-artist').value,'Fresh artist');
 assert.equal(s.nodes.get('song-cover-preview').src,'fresh-cover');
});
test('failure of an obsolete request does not overwrite a newer successful load',async()=>{
 const s=setup(),old=s.request('old'),current=s.request('current');
 const a=s.api.load('old'),b=s.api.load('current');
 current.resolve(s.result('Current title'));await b;
 old.reject(new Error('old request failed'));await a;
 assert.equal(s.nodes.get('track-name').textContent,'Current title');
 assert.doesNotMatch(s.nodes.get('status').textContent,/old request/);
});

async function loaded(){
 const s=setup(),d=s.request('song'),p=s.result('Song');
 p.rule_seed={version:'motion-plan-v1',source_signature:'test',seed:42,cues:[]};
 p.project.song_identity={title:'Song',artist:'Artist',style:'editorial',show_intro:false,show_signature:true,show_section:false,show_outro:false};
 const pending=s.api.load('song');d.resolve(p);await pending;return s;
}
test('local rule generation and themes preview without any write, until Save',async()=>{
 const s=await loaded();s.api.rules();s.nodes.get('preset').value='neon';s.api.previewPalette();
 assert.equal(s.writes.length,0);assert.equal(s.nodes.get('save-state').dataset.dirty,'true');
 const save=s.api.saveAll();assert.deepEqual(s.writes.map(w=>w.name).sort(),['plan','settings']);
 s.saves.forEach((d,i)=>d.resolve(s.writes[i].body.plan||{}));await save;
 assert.equal(s.nodes.get('save-state').dataset.dirty,'false');
});
test('edits during Save remain unsaved and survive the older response',async()=>{
 const s=await loaded();s.api.rules();const first=s.api.saveAll();
 s.nodes.get('preset').value='neon';s.api.previewPalette();s.api.getDraft().seed=77;
 s.saves.forEach((d,i)=>d.resolve(s.writes[i].body.plan||{}));await first;
 assert.equal(s.nodes.get('save-state').dataset.dirty,'true');
 const second=s.api.saveAll();assert.equal(s.writes.length,4);assert.equal(s.writes[2].body.plan.seed,77);assert.equal(s.writes[3].body.settings.palette,'neon');
 s.saves[2].resolve(s.writes[2].body.plan);s.saves[3].resolve({});await second;assert.equal(s.nodes.get('save-state').dataset.dirty,'false');
});
test('a failed save preserves the draft and permits retry',async()=>{
 const s=await loaded();s.api.rules();const first=s.api.saveAll();
 s.saves[0].reject(Error('network unavailable'));s.saves[1].resolve({});
 await assert.rejects(first,/network/);assert.equal(s.nodes.get('save-state').dataset.dirty,'true');
 const retry=s.api.saveAll();assert.equal(s.writes[2].name,'plan');s.saves[2].resolve(s.writes[2].body.plan);await retry;
 assert.equal(s.nodes.get('save-state').dataset.dirty,'false');
});
test('switching and exporting never silently save an unfinished preview',async()=>{
 const s=await loaded();s.api.rules();await s.api.load('other');
 assert.equal(s.nodes.get('project-select').value,'song');
 await assert.rejects(s.api.exportVideo(),/Save/);assert.equal(s.writes.length,0);
});
test('format and signature edits use the same explicit save',async()=>{
 const s=await loaded();s.nodes.get('aspect').value='9:16';s.nodes.get('aspect').input();
 s.nodes.get('song-title').value='New title';s.nodes.get('song-artist').value='New artist';s.api.editIdentity();
 assert.equal(s.writes.length,0);const save=s.api.saveAll();
 assert.deepEqual(s.writes.map(w=>w.name).sort(),['identity','settings']);
 for(let i=0;i<s.saves.length;i++)s.saves[i].resolve(s.writes[i].name==='identity'?{identity:s.writes[i].body.identity}:{});
 await save;assert.equal(s.nodes.get('save-state').dataset.dirty,'false');
});
test('changing theme preserves semantic nodes, animations, seeds and locked cues',()=>{
 const s=setup(),base={seed:9,cues:[{locked:false,palette:'impact',poster:{nodes:[{text:'Meaning',entrance:'fade'}],background:'#000',accent:'#fff'}},{locked:true,palette:'impact'}]};
 const result=s.design.localPalette(base,'neon','dark');
 assert.deepEqual(result.cues[0].poster.nodes,base.cues[0].poster.nodes);assert.equal(result.seed,9);
 assert.deepEqual(result.cues[1],base.cues[1]);assert.equal(base.cues[0].palette,'impact');assert.equal(result.cues[0].palette,'neon');
});

test('Motion Studio exportVideo submits matrix items sequentially and polls until complete', async () => {
 const s = await loaded();
 s.api.rules();
 const save = s.api.saveAll();
 s.saves.forEach((d,i)=>d.resolve(s.writes[i].body.plan||{}));
 await save;

 const box1 = { checked: true, disabled: false, dataset: { clipId: 'full', ratio: '9:16' } };
 const box2 = { checked: true, disabled: false, dataset: { clipId: 'chorus', ratio: '16:9' } };
 s.context.document.querySelectorAll = (sel) => sel === '.matrix-clip-check' ? [box1, box2] : [];

 await s.api.exportVideo();
 assert.equal(s.renders.length, 2);
 assert.equal(s.renders[0].aspect, '9:16');
 assert.equal(s.renders[0].start, 0);
 assert.equal(s.renders[0].length, null);
 assert.equal(s.renders[1].aspect, '16:9');
 assert.equal(s.renders[1].start, 20);
 assert.equal(s.renders[1].length, 15);
});

test('Motion Studio exportVideo supports custom range override', async () => {
 const s = await loaded();
 s.api.rules();
 const save = s.api.saveAll();
 s.saves.forEach((d,i)=>d.resolve(s.writes[i].body.plan||{}));
 await save;

 s.nodes.get('export-custom-range').checked = true;
 s.nodes.get('clip-start').value = '5';
 s.nodes.get('clip-length').value = '12';

 await s.api.exportVideo();
 assert.equal(s.renders.length, 1);
 assert.equal(s.renders[0].start, 5);
 assert.equal(s.renders[0].length, 12);
});
