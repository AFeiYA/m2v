const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../dashboard.js'), 'utf8');
function setup() {
 const nodes = new Map(), calls = [], clicks = [];
 function element(id) {if(!nodes.has(id)) nodes.set(id, {style:{}, handlers:{}, textContent:'',
  addEventListener(k,v){this.handlers[k]=v;}, pause(){},load(){},removeAttribute(k){delete this[k];},play:async()=>{}});return nodes.get(id);}
 const document = {cookie:'',querySelector:element,querySelectorAll:()=>[],addEventListener(){},
  body:{appendChild(){}},createElement:()=>({textContent:'',get innerHTML(){return this.textContent.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');},click(){clicks.push(this.href);},remove(){}})};
 const context = {window:{},location:{hostname:'localhost',origin:'http://localhost',host:'localhost',search:''},document,
  localStorage:{getItem:()=>null,setItem(){},removeItem(){}},URL,URLSearchParams,console:{log(){},warn(){},error(){}},
  setTimeout(){},clearInterval(){},confirm:()=>true,
  fetch:async(url,options={})=>{calls.push({url,method:options.method});return {ok:true,headers:{get:()=> 'application/json'},json:async()=>url.includes('/access?')?{url:'https://private.invalid/signed',filename:'song.mp4'}:{exports:[{id:'a',title:'<song>',kind:'lyric',created_at:'2026-10-15T00:00:00Z',details:{size_bytes:1048576}}],total:1}};},
 };
 context.window.location=context.location;
 vm.createContext(context);vm.runInContext(source,context);vm.runInContext('currentUser={id:"alice"};',context);
 return {context,nodes,calls,clicks,run:s=>vm.runInContext(s,context)};
}
test('opening My Exports loads metadata only and escapes song titles',async()=>{
 const s=setup();await s.run('loadExports()');
 assert.equal(s.calls.length,1);assert.match(s.calls[0].url,/api\/exports\?page=1/);
 assert.ok(s.nodes.get('#exports-list').innerHTML.includes('&lt;song>'));
 assert.equal(s.nodes.get('#export-preview-video'),undefined);
});
test('download requests a fresh scoped link without fetching video into memory',async()=>{
 const s=setup();await s.run('handleExportAction({dataset:{export:"a",exportAction:"download"}})');
 assert.equal(s.calls.length,1);assert.match(s.calls[0].url,/access\?preview=false/);
 assert.deepEqual(s.clicks,['https://private.invalid/signed']);
});
test('preview is requested explicitly and closing releases its source',async()=>{
 const s=setup();await s.run('handleExportAction({dataset:{export:"a",exportAction:"preview"}})');
 assert.match(s.calls[0].url,/preview=true/);assert.equal(s.nodes.get('#export-preview-video').src,'https://private.invalid/signed');
 s.run('closeExportPreview()');assert.equal(s.nodes.get('#export-preview-video').src,undefined);
});
test('cancelled deletion does not issue any server request',async()=>{
 const s=setup();s.context.confirm=()=>false;
 await s.run('handleExportAction({dataset:{export:"a",exportAction:"delete"}})');assert.equal(s.calls.length,0);
});

test('reused import video completion refreshes My Exports without importing again',async()=>{
 const s=setup();
 s.context.fetch=async(url)=>{
  s.calls.push({url});
  return {ok:true,headers:{get:()=> 'application/json'},json:async()=>url.includes('/jobs/')?{status:'completed'}:{exports:[],total:0}};
 };
 await s.run('trackImportedVideo("render-job")');
 assert.equal(s.calls.length,2);
 assert.match(s.calls[0].url,/api\/editor\/jobs\/render-job$/);
 assert.match(s.calls[1].url,/api\/exports\?page=1/);
 assert.equal(s.calls.some(c=>c.url.includes('from-suno')),false);
});

test('render requests restore queued and failed progress without starting inference',async()=>{
 const s=setup();s.context.fetch=async(url)=>{
  s.calls.push({url});return {ok:true,headers:{get:()=> 'application/json'},json:async()=>({jobs:[
   {id:'queued',title:'<Pending>',status:'queued',progress:0,attempt:1},
   {id:'failed',title:'Song',status:'failed',progress:45,error:'<failed>',attempt:2}
  ]})};
 };
 await s.run('loadRenderJobs()');
 const html=s.nodes.get('#render-jobs-list').innerHTML;
 assert.match(html,/Queued/);assert.match(html,/Retry rendering/);assert.match(html,/Attempt 2/);
 assert.match(html,/&lt;Pending>/);assert.match(html,/&lt;failed>/);
 assert.equal(s.calls.length,1);assert.match(s.calls[0].url,/api\/editor\/render-jobs$/);
});

test('retry invokes only the owned render retry endpoint',async()=>{
 const s=setup();s.context.fetch=async(url,options={})=>{
  s.calls.push({url,method:options.method});return {ok:true,headers:{get:()=> 'application/json'},json:async()=>url.includes('/render-jobs')?{jobs:[]}:url.includes('/api/exports')?{exports:[],total:0}:{task_id:'failed',status:'queued'}};
 };
 await s.run('handleRenderAction({dataset:{renderJob:"failed",renderAction:"retry"}})');
 assert.match(s.calls[0].url,/api\/editor\/jobs\/failed\/retry$/);assert.equal(s.calls[0].method,'POST');
 assert.equal(s.calls.some(c=>c.url.includes('from-suno') || c.url.includes('analyze')),false);
});

test('credit history shows available and reserved balances and escapes descriptions',async()=>{
 const s=setup();s.context.fetch=async(url)=>{
  s.calls.push({url});return {ok:true,headers:{get:()=> 'application/json'},json:async()=>({available:3,reserved:2,total:2,pricing:{alignment:1,lyric_export:2},entries:[{created_at:'2026-10-16T00:00:00Z',event:'reserve',amount:-2,balance_after:3,description:'<export>'}]})};
 };
 await s.run('loadCredits()');
 assert.match(s.nodes.get('#credit-summary').textContent,/3 available · 2 reserved/);
 assert.match(s.nodes.get('#credit-pricing').textContent,/Lyric video export: 2 credits/);
 assert.match(s.nodes.get('#credit-history').innerHTML,/&lt;export>/);
 assert.equal(s.nodes.get('#suno-opt-render-video').disabled,true);
 assert.equal(s.nodes.get('#opt-ass-only').checked,true);
});
