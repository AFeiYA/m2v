const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const esbuild = require('../motion/node_modules/esbuild');
const code = esbuild.transformSync(fs.readFileSync(path.join(__dirname,'../motion/src/service-api.ts'),'utf8'),
  {loader:'ts',format:'cjs',target:'es2022'}).code;
function setup({host='mv.fovea.si',token='valid-token',responses=[Response.json([])]}={}) {
  const calls=[],tokens=[];
  const context={module:{exports:{}},Headers,URL,Response,Promise,setTimeout,
    location:{hostname:host,origin:'https://'+host},
    window:{m2vAuth:{ready:Promise.resolve(),getIdToken:async force=>{tokens.push(force);return token;}}},
    fetch:async(url,options)=>{calls.push({url,authorization:options.headers.get('Authorization')});return responses.shift();}};
  vm.createContext(context);vm.runInContext(code,context);
  return {api:context.module.exports,calls,tokens,context};
}
test('Pages studio lists cloud tasks through the authenticated HF backend',async()=>{
  const s=setup();await s.api.motionJson('projects');
  assert.equal(s.calls[0].url,'https://lucazhou-suno2mv-api.hf.space/api/cloud-motion/projects');
  assert.equal(s.calls[0].authorization,'Bearer valid-token');
  assert.deepEqual(s.tokens,[false]);
});
test('expired Firebase tokens refresh once before retrying',async()=>{
  const s=setup({responses:[Response.json({detail:'expired'},{status:401}),Response.json([])]});
  await s.api.motionJson('projects');assert.deepEqual(s.tokens,[false,true]);assert.equal(s.calls.length,2);
});
test('HTML service errors do not become JSON SyntaxError',async()=>{
  const s=setup({responses:[new Response('<!doctype html>',{status:404,headers:{'Content-Type':'text/html'}})]});
  await assert.rejects(s.api.motionJson('projects'),/non-JSON.*404/);
});
test('missing login prevents anonymous cloud directory access',async()=>{
  const s=setup({token:null});await assert.rejects(s.api.motionJson('projects'),/Sign in on the home page/);
  assert.equal(s.calls.length,0);
});
test('external media never receives the account credential',async()=>{
  const s=setup();await s.api.serviceFetch('https://cdn.example/song.mp3');
  assert.equal(s.calls[0].authorization,null);assert.deepEqual(s.tokens,[]);
});
test('local studio retains its existing local project API',async()=>{
  const s=setup({host:'localhost'});await s.api.motionJson('projects');
  assert.equal(s.calls[0].url,'https://localhost/api/motion/projects');assert.equal(s.calls[0].authorization,null);
});

function audioSetup(uid='alice'){
 const calls=[],entries=new Map();let user=uid;
 const token=()=> 'header.'+Buffer.from(JSON.stringify({sub:user})).toString('base64url')+'.signature';
 const cache={getMedia:async(u,t,k,v)=>entries.get(`${u}:${t}:${k}:${v}`)||null,
  saveMedia:async(u,t,k,b,v)=>entries.set(`${u}:${t}:${k}:${v}`,b)};
 const context={module:{exports:{}},Headers,URL,Response,Promise,Blob,atob,setTimeout,
  location:{hostname:'mv.fovea.si',origin:'https://mv.fovea.si'},
  window:{m2vCache:cache,m2vAuth:{ready:Promise.resolve(),getIdToken:async()=>user?token():null}},
  fetch:async(url,options)=>{calls.push({url,options});return new Response(new Blob(['original-audio'],{type:'audio/mpeg'}));}};
 vm.createContext(context);vm.runInContext(code,context);
 return {api:context.module.exports,calls,entries,cache,switchUser:value=>{user=value;}};
}
test('Motion audio persists across calls and invalidates by audio version, not lyric timing',async()=>{
 const s=audioSetup(),identity={uid:'alice',version:'immutable-audio-v1'};
 const first=await s.api.serviceAudio('/api/editor/tasks/a/audio','a',identity);
 const second=await s.api.serviceAudio('/api/editor/tasks/a/audio','a',identity);
 assert.equal(first.cached,false);assert.equal(second.cached,true);assert.equal(s.calls.length,1);
 await s.api.serviceAudio('/api/editor/tasks/a/audio','a',{...identity,version:'new-source'});
 assert.equal(s.calls.length,2);
});
test('cached Motion audio is unavailable after logout or switching users',async()=>{
 const s=audioSetup();await s.api.serviceAudio('/api/editor/tasks/a/audio','a',{uid:'alice',version:'v1'});
 s.switchUser('bob');
 await assert.rejects(s.api.serviceAudio('/api/editor/tasks/a/audio','a',{uid:'alice',version:'v1'}),/Account changed/);
 s.switchUser(null);
 await assert.rejects(s.api.serviceAudio('/api/editor/tasks/a/audio','a',{uid:'alice',version:'v1'}),/Sign in/);
 assert.equal(s.calls.length,1);
});
test('Bob cannot hit Alice audio cache even with an identical task and version',async()=>{
 const s=audioSetup();await s.api.serviceAudio('/api/editor/tasks/a/audio','a',{uid:'alice',version:'v1'});
 s.switchUser('bob');const result=await s.api.serviceAudio('/api/editor/tasks/a/audio','a',{uid:'bob',version:'v1'});
 assert.equal(result.cached,false);assert.equal(s.calls.length,2);
});

function downloadSetup(options={}){
 const s=setup(options),clicks=[];
 // Reuse the actual compiled module with a document available at invocation.
 // setup exposes its context so deferred account changes can be tested too.
 s.context.document={body:{appendChild(){}},createElement:()=>({click(){clicks.push({url:this.href,name:this.download});},remove(){}})};
 return {...s,clicks};
}
test('cloud Motion downloads a scoped media URL without reading MP4 bytes',async()=>{
 const id='a'.repeat(32),s=downloadSetup({responses:[Response.json({url:'https://media.invalid/signed',filename:'My song.mp4'})]});
 await s.api.downloadService('/api/cloud-motion/render/'+id+'/download');
 assert.equal(s.calls.length,1);assert.match(s.calls[0].url,/api\/exports\/a+\/access\?preview=false$/);
 assert.deepEqual(s.clicks,[{url:'https://media.invalid/signed',name:'My song.mp4'}]);
});
test('missing cloud export never falls back to loading the full MP4',async()=>{
 const s=downloadSetup({responses:[Response.json({detail:'Export not found'},{status:404})]});
 await assert.rejects(s.api.downloadService('/api/cloud-motion/render/'+'b'.repeat(32)+'/download'),/Export not found/);
 assert.equal(s.calls.length,1);assert.equal(s.clicks.length,0);
});
test('local Motion uses native download without fetching the video first',async()=>{
 const s=downloadSetup({host:'localhost'});
 await s.api.downloadService('/api/motion/render/local/download');
 assert.equal(s.calls.length,0);assert.equal(s.clicks[0].url,'https://localhost/api/motion/render/local/download');
});
test('signing out during access lookup does not start a download',async()=>{
 const s=downloadSetup({responses:[Response.json({url:'https://media.invalid/signed'})]});
 let reads=0;s.context.window.m2vAuth.getIdToken=async()=>++reads<3?'alice':null;
 await assert.rejects(s.api.downloadService('/api/cloud-motion/render/'+'c'.repeat(32)+'/download'),/Account changed/);
 assert.equal(s.clicks.length,0);
});
