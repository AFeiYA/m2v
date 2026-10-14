const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const esbuild=require('../motion/node_modules/esbuild');
const source=fs.readFileSync(path.join(__dirname,'../motion/src/studio.ts'),'utf8')+'\nexport {load,refreshSourceInfo};';
const code=esbuild.transformSync(source,{loader:'ts',format:'cjs',target:'es2022'}).code;
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function setup(){
 const nodes=new Map(),pending=new Map();
 const node=()=>({value:'',style:{},dataset:{},checked:false,hidden:false,children:[],textContent:'',
  addEventListener(){},replaceChildren(){this.children=[];},append(v){this.children.push(v);},
  querySelectorAll(){return [];},getContext(){return {};},classList:{toggle(){return false;}}});
 const document={getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},createElement:node,body:node()};
 class Audio{currentTime=0;src='';pause(){}load(){}addEventListener(){}}
 class RemotionPreview{renderAt(){}dispose(){}}
 const service={cloudService:()=>false,motionJson:async name=>{
  if(name==='projects'||name.startsWith('exports?'))return [];
  if(name==='director/config')return {configured:false};
  if(name==='source/refresh')return {identity:{title:'Fresh title',artist:'Fresh artist',source:'suno-cache'},cover:{data_url:'fresh-cover',source:'suno'}};
  if(name.startsWith('project?'))return pending.get(new URLSearchParams(name.split('?')[1]).get('project_id')).promise;
  throw Error(name);
 }};
 const requireStub=name=>name.includes('service-api')?service:name.includes('remotion-preview')?{RemotionPreview}:name.includes('/model')?{defaults:{},normalizeProject:p=>p,renderSize:()=>({width:720,height:1280})}:{};
 const context={module:{exports:{}},require:requireStub,document,window:{addEventListener(){}},Audio,
  URL,URLSearchParams,Blob,FormData,setTimeout,requestAnimationFrame(){},console,location:{search:''}};
 vm.createContext(context);vm.runInContext(code,context);
 function request(id){const d=deferred();pending.set(id,d);return d;}
 function result(title){return {project:{title,duration:2,lines:[],analysis:{energy_curve:[],beats:[]}},plan:null,audio_url:title+'.mp3'};}
 return {api:context.module.exports,nodes,request,result};
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
