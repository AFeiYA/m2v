const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const esbuild=require('../motion/node_modules/esbuild');

function moduleFor(name,context={}){
 const source=fs.readFileSync(path.join(__dirname,'../motion/src',name),'utf8');
 const sandbox={module:{exports:{}},URLSearchParams,Blob,AbortController,setTimeout,clearTimeout,...context};
 vm.runInNewContext(esbuild.transformSync(source,{loader:'ts',format:'cjs'}).code,sandbox);
 return sandbox.module.exports;
}

test('browser archive sends the actual MP4 and preserves request identity on retry',async()=>{
 const calls=[];let fail=true;
 const api=moduleFor('browser-export.ts',{require:()=>({cloudService:()=>true,
  serviceJson:async(url,options)=>{calls.push({url,options});if(fail)throw new Error('Storage offline');}})});
 const blob=new Blob(['video'],{type:'video/mp4'}),options={projectId:'song',requestId:'same-request',acceptedCost:10,title:'Song',aspect:'9:16'};
 await assert.rejects(api.archiveBrowserVideo(blob,options),/Storage offline/);
 fail=false;await api.archiveBrowserVideo(blob,options);
 assert.equal(calls.length,2);
 assert.equal(calls[0].url,calls[1].url);
 assert.match(calls[0].url,/request_id=same-request/);
 assert.strictEqual(calls[0].options.body,blob);
 assert.equal(calls[0].options.headers['Content-Type'],'video/mp4');
});

test('standalone local export does not create a fake cloud archive',async()=>{
 const api=moduleFor('browser-export.ts',{require:()=>({cloudService:()=>false,serviceJson:()=>{throw new Error('Unexpected cloud call');}})});
 await api.archiveBrowserVideo(new Blob(['video']),{});
});

test('stalled cloud saving has a deadline even when the transport ignores cancellation',async()=>{
 let signal;
 const api=moduleFor('browser-export.ts',{require:()=>({cloudService:()=>true,
  serviceJson:(_,options)=>{signal=options.signal;return new Promise(()=>{});}})});
 await assert.rejects(api.archiveBrowserVideo(new Blob(['video']),{
  projectId:'song',requestId:'same-request',acceptedCost:10,title:'Song',aspect:'9:16',
 },{timeoutMs:10}),/timed out/);
 assert.equal(signal.aborted,true);
});

test('cancel interrupts an active upload and removes its abort listener',async()=>{
 const controller=new AbortController();let signal,removed=0;
 const remove=controller.signal.removeEventListener.bind(controller.signal);
 controller.signal.removeEventListener=(...args)=>{removed++;return remove(...args);};
 const api=moduleFor('browser-export.ts',{require:()=>({cloudService:()=>true,
  serviceJson:(_,options)=>{signal=options.signal;return new Promise(()=>{});}})});
 const waiting=api.archiveBrowserVideo(new Blob(['video']),{
  projectId:'song',requestId:'same-request',acceptedCost:10,title:'Song',aspect:'9:16',
 },{signal:controller.signal});
 controller.abort();
 await assert.rejects(waiting,/Upload cancelled/);
 assert.equal(signal.aborted,true);
 assert.equal(removed,1);
});

test('audio decode failure rejects the export and releases its AudioContext',async()=>{
 let closed=0;
 class Context{async decodeAudioData(){throw new Error('Invalid audio');}async close(){closed++;}}
 const api=moduleFor('export-audio.ts',{window:{AudioEncoder:class{},AudioContext:Context}});
 await assert.rejects(api.decodeExportAudio(new Blob(['audio'])),/Invalid audio/);
 assert.equal(closed,1);
});

test('missing audio encoder fails before downloading song bytes',async()=>{
 const api=moduleFor('export-audio.ts',{window:{},fetch:()=>{throw new Error('Unexpected fetch');}});
 await assert.rejects(api.decodeExportAudio('song.mp3'),/audio encoding is unavailable/);
});
