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
  return {api:context.module.exports,calls,tokens};
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
  await assert.rejects(s.api.motionJson('projects'),/非 JSON.*404/);
});
test('missing login prevents anonymous cloud directory access',async()=>{
  const s=setup({token:null});await assert.rejects(s.api.motionJson('projects'),/请先在首页登录/);
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
