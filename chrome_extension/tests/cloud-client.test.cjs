const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const {webcrypto}=require('node:crypto');
function setup(){
 const state={authToken:'alice-token',authUserId:'alice',authServer:'https://lucazhou-suno2mv-api.hf.space'};
 const calls=[],files=[],items=[];let messages;
 const ctx=vm.createContext({URL,FormData,AbortSignal,AbortController,crypto:webcrypto,console,Date,
  setTimeout:fn=>{queueMicrotask(fn);return 1;},clearTimeout(){},
  chrome:{runtime:{onMessage:{addListener(fn){messages=fn;}}},
   storage:{local:{get:async keys=>Object.fromEntries((Array.isArray(keys)?keys:[keys]).map(k=>[k,state[k]])),set:async d=>Object.assign(state,d)}},
   tabs:{query:async()=>[{id:9,url:'https://mv.fovea.si/'}],sendMessage(){}},
   scripting:{executeScript:async()=>[{result:'fresh-token'}]},
   downloads:{onChanged:{addListener(){}},search:async({id})=>items.filter(i=>i.id===id),download:async options=>{
    files.push(options);const id=files.length;items.push({id,state:'in_progress'});return id;}}},
  fetch:async(url,options={})=>{
   calls.push({url,options});
   const route=new URL(url).pathname;
   if(route==='/api/auth/me')return Response.json({id:ctx.nextUser||'alice',display_name:'Alice'});
   if(route==='/api/suno/publish_status')return Response.json({is_public:true});
   if(route==='/api/tasks/from-suno')return Response.json({task_id:'song-task'});
   if(route==='/api/tasks/song-task')return Response.json({status:'completed'});
   if(route.endsWith('/lyric-video')){if(ctx.dropExportResponse){ctx.dropExportResponse=false;throw Error('network lost');}return Response.json({task_id:'abc123'});}
   if(route==='/api/editor/jobs/abc123')return Response.json({status:'completed',progress:100});
   throw Error('Unexpected '+url);
  }});
 ctx.importScripts=file=>vm.runInContext(fs.readFileSync(path.join(__dirname,'..',file),'utf8'),ctx);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../background.js'),'utf8'),ctx);
 return {ctx,state,calls,files,items,messages:()=>messages};
}
const song={songId:'9559f6d1-f7bb-4e3c-94d8-834f6ea4c7d2',title:'My song',is_public:true};
test('official cloud imports once, exports owned clip and downloads using headers',async()=>{
 const t=setup();
 await t.ctx.exportVideoAndDownload(null,song,'https://mv.fovea.si','chorus',30);
 const posts=t.calls.filter(c=>c.options.method==='POST');
 assert.equal(posts.length,2);
 assert.equal(posts[0].url,'https://lucazhou-suno2mv-api.hf.space/api/tasks/from-suno');
 const options=JSON.parse(posts[1].options.body);assert.equal(options.section_name,'chorus');assert.equal(options.duration_limit,30);
 assert.equal(t.files.length,1);
 assert.equal(t.files[0].url,'https://lucazhou-suno2mv-api.hf.space/api/editor/jobs/abc123/video');
 assert.equal(t.files[0].headers[0].value,'Bearer alice-token');
 assert.ok(t.calls.every(c=>!c.url.includes('token=')));
 assert.ok(!t.files[0].url.includes('token='));
 await t.ctx.FoveaCloud.finish(t.state.videoJobs[0]);
 assert.equal(t.files.length,1);
 assert.equal(t.state.downloads[0].ownerUid,'alice');
});
test('lost export response resumes with identical request id and existing import',async()=>{
 const t=setup();t.ctx.dropExportResponse=true;
 await t.ctx.exportVideoAndDownload(null,song,'https://mv.fovea.si','intro',30);
 const imports=t.calls.filter(c=>c.url.endsWith('/api/tasks/from-suno'));
 const exports=t.calls.filter(c=>c.url.endsWith('/lyric-video'));
 assert.equal(imports.length,1);assert.equal(exports.length,2);
 assert.equal(JSON.parse(exports[0].options.body).request_id,JSON.parse(exports[1].options.body).request_id);
});
test('switching accounts cannot resume or download another account job',async()=>{
 const t=setup();t.state.authUserId='bob';
 await assert.rejects(t.ctx.FoveaCloud.finish({kind:'cloud',ownerUid:'alice',requestId:'owned',songTaskId:'song-task'}),/another account/);
 assert.equal(t.calls.length,0);assert.equal(t.files.length,0);
});
test('website sync validates identity and refuses silent refresh into a different account',async()=>{
 const t=setup();t.ctx.nextUser='bob';
 await assert.rejects(t.ctx.FoveaCloud.sync('alice'),/account changed/);
 assert.equal(t.state.authToken,'alice-token');
 await t.ctx.FoveaCloud.sync();assert.equal(t.state.authUserId,'bob');assert.equal(t.state.authToken,'fresh-token');
});
test('private MP3 fallback uses current backend without putting token into URL',async()=>{
 const t=setup();
 await t.ctx.downloadTrackMp3({songId:song.songId,title:'Song',is_public:true},'https://mv.fovea.si');
 assert.equal(t.files.length,1);assert.match(t.files[0].url,/hf.space\/api\/suno\/download_mp3\?url=/);
 assert.ok(!t.files[0].url.includes('token='));assert.ok(t.files[0].headers.some(h=>h.name==='Authorization'));
});

test('disconnect stops background jobs from silently reconnecting to website',async()=>{
 const t=setup();t.state.cloudDisconnected=true;delete t.state.authToken;
 await assert.rejects(t.ctx.FoveaCloud.token('alice'),/Disconnected/);
 assert.equal(t.calls.length,0);
 await t.ctx.FoveaCloud.sync('alice');assert.equal(t.state.cloudDisconnected,false);
});
test('a 401 refreshes only the existing job account',async()=>{
 const t=setup(),original=t.ctx.fetch;let expired=true;
 t.ctx.fetch=async(url,options)=>{
  if(expired&&new URL(url).pathname==='/api/tasks/song-task'){expired=false;return Response.json({detail:'expired'},{status:401});}
  return original(url,options);
 };
 await t.ctx.FoveaCloud.request('/api/tasks/song-task',{},'alice');
 assert.equal(t.state.authToken,'fresh-token');
 assert.equal(t.state.authUserId,'alice');
});

test('switching to a custom or local server never forwards official account credentials',async()=>{
 const t=setup();
 assert.equal(await t.ctx.serverToken('https://custom.example'),undefined);
 assert.equal(await t.ctx.serverToken('http://127.0.0.1:8000'),undefined);
 assert.equal(await t.ctx.serverToken('https://lucazhou-suno2mv-api.hf.space'),'alice-token');
});
