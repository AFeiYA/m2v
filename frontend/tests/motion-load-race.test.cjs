const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const esbuild=require('../motion/node_modules/esbuild');
const source=fs.readFileSync(path.join(__dirname,'../motion/src/studio.ts'),'utf8')+'\nexport {load,refreshSourceInfo,rules,previewPalette,saveAll,editIdentity,exportVideo,refreshMotionPrice,updateMatrixCount,applyVisualTemplate,designSnapshot}; export const getDraft=()=>plan;';
const code=esbuild.transformSync(source,{loader:'ts',format:'cjs',target:'es2022'}).code;
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function setup(){
 const writes=[],saves=[],renders=[],alerts=[];
 const nodes=new Map(),pending=new Map();
 const node=()=>({value:'',style:{},dataset:{},checked:false,hidden:false,children:[],textContent:'',
  focus(){this.focused=true;},setAttribute(k,v){this[k]=v;},addEventListener(name,handler){this[name]=handler;},replaceChildren(){this.children=[];},append(v){this.children.push(v);},
  querySelectorAll(){return [];},getContext(){return {};},classList:{toggle(){return false;}}});
 const document={getElementById(id){if(!nodes.has(id)){const n=node();n.value=({preset:'impact','theme-bg':'auto','default-layout-preset':'smart',aspect:'16:9',resolution:'720',bloom:'.7',shake:'.65'})[id]||'';nodes.set(id,n);}return nodes.get(id);},querySelectorAll(){return [];},createElement:node,body:node()};
 class Audio{currentTime=0;src='';pause(){this.on_pause?.();}load(){}addEventListener(name,handler){this['on_'+name]=handler;}}
 class RemotionPreview{renderAt(){}dispose(){}}
 const service={cloudService:()=>false,isStagingHost:()=>false,motionUrl:p=>'/'+p,downloadService:url=>url,motionJson:async (name,method,body)=>{
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
 const modeCode=esbuild.buildSync({entryPoints:[path.join(__dirname,'../motion/src/motion-design.ts')],bundle:true,platform:'node',format:'cjs',write:false}).outputFiles[0].text;
 const modeModule={exports:{}};new Function('module','exports',modeCode)(modeModule,modeModule.exports);
 const webcodecsModule={isWebCodecsSupported:()=>false,exportMotionWebCodecs:async()=>new Blob()};
 const browserExportModule={archiveBrowserVideo:async()=>{}};
 const requireStub=name=>name.includes('motion-design')?modeModule.exports:name.includes('local-design')?design.exports:name.includes('service-api')?service:name.includes('remotion-preview')?{RemotionPreview}:name.includes('webcodecs-exporter')?webcodecsModule:name.includes('browser-export')?browserExportModule:name.includes('/model')?{defaults:{},normalizeProject:p=>p,renderSize:()=>({width:720,height:1280}),buildExportClips:()=>[{id:'full',title:'Full song',available:true,start_time:0,end_time:null},{id:'chorus',title:'Chorus',available:true,start_time:20,end_time:35}],resolveVisualMode:m=>m||'kinetic'}:{};
 const context={module:{exports:{}},require:requireStub,document,window:{addEventListener(){},confirm:()=>false,alert:message=>alerts.push(message)},MutationObserver:class{observe(){}},Audio,structuredClone,
  URL,URLSearchParams,Blob,FormData,AbortController,setTimeout,requestAnimationFrame(){},console,location:{search:''}};
 vm.createContext(context);vm.runInContext(code,context);
 function request(id){const d=deferred();pending.set(id,d);return d;}
 function result(title){return {project:{title,duration:2,lines:[],analysis:{energy_curve:[],beats:[]}},plan:null,audio_url:title+'.mp3'};}
 return {alerts,api:context.module.exports,nodes,request,result,writes,saves,renders,context,design:design.exports,webcodecsModule,browserExportModule};
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
 const save=s.api.saveAll();assert.deepEqual(s.writes.map(w=>w.name).sort(),['design']);
 s.saves.forEach((d,i)=>d.resolve({design:s.writes[i].body.design}));await save;
 assert.equal(s.nodes.get('save-state').dataset.dirty,'false');
});
test('edits during Save remain unsaved and survive the older response',async()=>{
 const s=await loaded();s.context.window.confirm=()=>true;s.api.rules();const first=s.api.saveAll();
 s.nodes.get('preset').value='neon';s.api.previewPalette();s.api.getDraft().seed=77;
 s.saves.forEach((d,i)=>d.resolve({design:s.writes[i].body.design}));await first;
 assert.equal(s.nodes.get('save-state').dataset.dirty,'true');
 const second=s.api.saveAll();assert.equal(s.writes.length,2);assert.equal(s.writes[1].body.design.modes.kinetic.plan.seed,77);assert.equal(s.writes[1].body.design.modes.kinetic.theme.palette,'neon');
 s.saves[1].resolve({design:s.writes[1].body.design});await second;assert.equal(s.nodes.get('save-state').dataset.dirty,'false');
});
test('a failed save preserves the draft and permits retry',async()=>{
 const s=await loaded();s.context.window.confirm=()=>true;s.api.rules();const first=s.api.saveAll();
 s.saves[0].reject(Error('network unavailable'));
 await assert.rejects(first,/network/);assert.equal(s.nodes.get('save-state').dataset.dirty,'true');
 const retry=s.api.saveAll();assert.equal(s.writes[1].name,'design');s.saves[1].resolve({design:s.writes[1].body.design});await retry;
 assert.equal(s.nodes.get('save-state').dataset.dirty,'false');
});
test('switching and exporting never silently save an unfinished preview',async()=>{
 const s=await loaded();s.api.rules();await s.api.load('other');
 assert.equal(s.nodes.get('project-select').value,'song');
 await assert.rejects(s.api.exportVideo(),/Save/);assert.equal(s.writes.length,0);
 assert.equal(s.renders.length,0);assert.equal(s.alerts.length,1);
 assert.match(s.alerts[0],/no credits have been charged/);
 assert.equal(s.nodes.get('export-status').textContent,s.alerts[0]);
 assert.equal(s.nodes.get('save-design').focused,true);
});
test('format and signature edits use the same explicit save',async()=>{
 const s=await loaded();s.nodes.get('aspect').value='9:16';s.nodes.get('aspect').input();
 s.nodes.get('song-title').value='New title';s.nodes.get('song-artist').value='New artist';s.api.editIdentity();
 assert.equal(s.writes.length,0);const save=s.api.saveAll();
 assert.deepEqual(s.writes.map(w=>w.name).sort(),['design','identity']);
 for(let i=0;i<s.saves.length;i++)s.saves[i].resolve(s.writes[i].name==='identity'?{identity:s.writes[i].body.identity}:{design:s.writes[i].body.design});
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
 s.saves.forEach((d,i)=>d.resolve({design:s.writes[i].body.design}));
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
 s.saves.forEach((d,i)=>d.resolve({design:s.writes[i].body.design}));
 await save;

 s.nodes.get('export-custom-range').checked = true;
 s.nodes.get('clip-start').value = '5';
 s.nodes.get('clip-length').value = '12';

 await s.api.exportVideo();
 assert.equal(s.renders.length, 1);
 assert.equal(s.renders[0].start, 5);
 assert.equal(s.renders[0].length, 12);
});

async function savedMotion(){
 const s=await loaded();s.api.rules();const save=s.api.saveAll();s.saves.forEach((d,i)=>d.resolve({design:s.writes[i].body.design}));await save;return s;
}
function selectFull(s){s.context.document.querySelectorAll=()=>[{checked:true,disabled:false,dataset:{clipId:'full',ratio:'9:16'}}];}
function paidService(s,cost=2){
 const service=s.context.require('./service-api');service.cloudService=()=>true;
 service.serviceJson=async()=>({pricing:{motion_export:cost}});
 s.context.window.crypto=require('node:crypto').webcrypto;s.context.TextEncoder=TextEncoder;
 const values=new Map();s.context.localStorage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
 return service;
}
test('paid matrix sends accepted price and preserves request id after ambiguous submission',async()=>{
 const s=await savedMotion();selectFull(s);const service=paidService(s);await s.api.refreshMotionPrice();
 const original=service.motionJson,bodies=[];
 service.motionJson=async(name,method,body)=>{if(name==='render'&&method==='POST'){bodies.push(body);throw Error('Network lost after acceptance');}return original(name,method,body);};
 await assert.rejects(s.api.exportVideo(),/Network/);await assert.rejects(s.api.exportVideo(),/Network/);
 assert.equal(bodies[0].accepted_cost,2);assert.equal(bodies[0].request_id,bodies[1].request_id);
 assert.match(bodies[0].request_id,/^[0-9a-f-]{36}$/);
 assert.match(s.nodes.get('motion-credit-price').textContent,/2 credits total/);
});
test('price changes require renewed confirmation before any paid render',async()=>{
 const s=await savedMotion();selectFull(s);const service=paidService(s);await s.api.refreshMotionPrice();
 service.serviceJson=async()=>({pricing:{motion_export:3}});
 await assert.rejects(s.api.exportVideo(),/price updated/);assert.equal(s.renders.length,0);
 await s.api.exportVideo();assert.equal(s.renders[0].accepted_cost,3);
});
test('matrix selections do not dirty the saved design',async()=>{
 const s=await savedMotion();const grid=s.nodes.get('matrix-candidates-list');
 const checkbox=grid.children[4].children[0];checkbox.checked=true;checkbox.change();selectFull(s);
 await s.api.exportVideo();assert.equal(s.renders.length,1);
 assert.equal(s.nodes.get('save-state').dataset.dirty,'false');
});
test('export queue keeps its source song and cannot switch projects mid-submit',async()=>{
 const s=await savedMotion();selectFull(s);const service=s.context.require('./service-api'),original=service.motionJson;
 service.motionJson=async(name,method,body)=>{if(name==='render'&&method==='POST')await s.api.load('other');return original(name,method,body);};
 await s.api.exportVideo();assert.equal(s.renders[0].project_id,'song');
 assert.equal(s.nodes.get('project-select').value,'song');
});
test('cancel during submission also cancels the newly accepted render',async()=>{
 const s=await savedMotion();selectFull(s);const service=s.context.require('./service-api'),original=service.motionJson,accepted=deferred(),calls=[];
 service.motionJson=async(name,method,body)=>{calls.push(name);return name==='render'&&method==='POST'?accepted.promise:original(name,method,body);};
 const exporting=s.api.exportVideo();await Promise.resolve();await Promise.resolve();
 await s.nodes.get('cancel').onclick();accepted.resolve({id:'job-accepted'});await exporting;
 assert.ok(calls.includes('render/job-accepted/cancel'));
});
test('retrying a partially submitted batch reuses completed item identities',async()=>{
 const s=await savedMotion();
 s.context.document.querySelectorAll=()=>[{checked:true,dataset:{clipId:'full',ratio:'9:16'}},{checked:true,dataset:{clipId:'chorus',ratio:'16:9'}}];
 const service=paidService(s);await s.api.refreshMotionPrice();const original=service.motionJson,bodies=[];let fails=true;
 service.motionJson=async(name,method,body)=>{
  if(name==='render'&&method==='POST'){bodies.push(body);if(body.start===20&&fails){fails=false;throw Error('Network interrupted during batch');}}
  return original(name,method,body);
 };
 await assert.rejects(s.api.exportVideo(),/Network/);await s.api.exportVideo();
 assert.equal(bodies[0].request_id,bodies[2].request_id);
 assert.equal(bodies[1].request_id,bodies[3].request_id);
});

test('workspace pause reaches Motion audio and resets the playback button',()=>{
 const s=setup();
 const audio=s.context.document.body.children.find(child=>child.id==='motion-audio');
 assert.ok(audio,'Motion audio must be attached for shared playback controls');
 s.nodes.get('play').textContent='Ⅱ';
 audio.pause();
 assert.equal(s.nodes.get('play').textContent,'▶');
});

test('mode switching, explicit save and reload preserve custom posters and per-mode preferences',async()=>{
 const s=await loaded();s.api.rules();
 s.api.getDraft().cues.push({line_id:'custom',locked:true,template:'phrase-rise',layout:'left',palette:'violet',intensity:.4,emphasis:'',poster:{layout:'staggered',highlight:'none',nodes:[{text:'My design',entrance:'slide-left'}]}});
 const poster=JSON.stringify(s.api.getDraft());
 for(const mode of ['apple','tv','kinetic']){
  s.nodes.get('visual-template-select').value=mode;s.api.applyVisualTemplate();
  assert.equal(JSON.stringify(s.api.getDraft()),poster);
  if(mode==='apple'){
   s.nodes.get('aspect').value='16:9';s.nodes.get('aspect').input();
   assert.equal(s.api.designSnapshot().active_mode,'apple');
   s.nodes.get('preset').value='neon';s.api.previewPalette();
  }
 }
 s.nodes.get('visual-template-select').value='apple';s.api.applyVisualTemplate();
 assert.equal(s.nodes.get('aspect').value,'16:9');assert.equal(s.nodes.get('preset').value,'neon');
 const save=s.api.saveAll();s.saves[0].resolve({design:s.writes[0].body.design});await save;
 assert.equal(s.writes.length,1);assert.equal(s.writes[0].name,'design');
 const response=s.result('Song');response.design=structuredClone(s.writes[0].body.design);
 const request=s.request('song'),reload=s.api.load('song');request.resolve(response);await reload;
 assert.equal(s.nodes.get('visual-template-select').value,'apple');assert.equal(s.nodes.get('aspect').value,'16:9');
 assert.equal(JSON.stringify(s.api.getDraft()),poster);
 const other=s.request('other'),loading=s.api.load('other');other.resolve(s.result('Other'));await loading;
 assert.equal(s.nodes.get('visual-template-select').value,'kinetic');assert.equal(s.api.getDraft(),null);
});

test('export credit units follow the selected locale',async()=>{
 const s=await loaded();s.context.require('./service-api').cloudService=()=>true;
 s.context.require('./service-api').serviceJson=async()=>({pricing:{motion_export:10,motion_webcodecs:10}});
 await s.api.refreshMotionPrice();
 s.context.document.getElementById('export-custom-range').checked=true;
 for(const locale of ['en','zh']){
  s.context.window.currentLocale=locale;s.api.updateMatrixCount();
  assert.match(s.nodes.get('export').textContent,locale==='zh'?/积分/:/credits/);
  if(locale==='en')assert.doesNotMatch(s.nodes.get('export').textContent,/积分/);
 }
});

test('local WebCodecs export unlocks song via lightweight request and downloads directly without uploading video',async()=>{
 const s=await savedMotion();selectFull(s);
 s.webcodecsModule.isWebCodecsSupported=()=>true;
 s.webcodecsModule.exportMotionWebCodecs=async()=>new s.context.Blob(['mock mp4'],{type:'video/mp4'});
 const service=paidService(s);
 await s.api.refreshMotionPrice();
 let unlockCalled=0;
 const originalServiceJson = service.serviceJson;
 service.serviceJson=async(url,options)=>{
  if(url.includes('/unlock')){
   unlockCalled++;
   return {unlocked:true,cost:10};
  }
  return originalServiceJson(url,options);
 };
 await s.api.exportVideo();
 const dl=s.nodes.get('download');
 assert.equal(dl.hidden,false,'Download button must be visible for completed local export');
 assert.ok(dl.href,'Download button must have blob link');
 assert.match(dl.download,/\.mp4$/,'Download button must set mp4 filename');
 assert.equal(unlockCalled,1,'Song was unlocked via lightweight unlock request');
});
