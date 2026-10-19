const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../local/lyric_editor.js'), 'utf8');

function setup(saveOk = true) {
  const elements = new Map(), calls = [], notices = [];
  let poll;
  function element(selector) {
    if (!elements.has(selector)) elements.set(selector, {
      style: {}, dataset: {}, handlers: {}, value: '',
      addEventListener(event, fn) {this.handlers[event] = fn;},
      pause() {}, load() {}, play: async () => {},
    });
    return elements.get(selector);
  }
  element('#export-start-time').value = '0:05';
  element('#export-end-time').value = '0:15';
  const context = {
    window: {addEventListener() {}}, document: {querySelector: () => null, addEventListener() {}},
    $: element, $$: () => [], state: {currentFile: {task_id: 'song', is_saas: true}, dirty: true},
    saveAlignment: async () => {calls.push({saved: true}); return saveOk;},
    status: m => notices.push(m), alert: m => notices.push(m),
    setInterval(fn) {poll = fn; return 1;}, clearInterval() {}, console,
    URL: {createObjectURL: () => 'blob:video', revokeObjectURL() {}},
  };
  context.window.apiFetch = async (url, options = {}) => {
    calls.push({url, body: options.body && JSON.parse(options.body)});
    if (url.startsWith('/api/credits')) return {ok:true,json:async()=>({available:5,pricing:{lyric_export:0}})};
    if (url.endsWith('/lyric-video')) return {ok: true, json: async () => ({task_id: 'job'})};
    if (url.includes('/access?')) return {ok: true, json: async () => ({url: 'https://files.invalid/video.mp4', filename:'lyric_video.mp4'})};
    return {ok: true, json: async () => ({status: 'completed', progress: 100, result: {video_url: '/api/editor/jobs/job/video'}})};
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  vm.runInContext('initLyricExportModal()', context);
  return {context, elements, calls, notices, start: () => element('#btn-start-lyric-export').handlers.click(), poll: () => poll()};
}

test('cloud modal shows completed export immediately and loads preview only on demand', async () => {
  const s = setup();
  await s.start();
  assert.equal(s.calls[0].saved, true);
  assert.equal(s.calls[1].url, '/api/credits?page_size=1');
  const render=s.calls.find(c=>c.url?.endsWith('/lyric-video'));
  assert.equal(render.body.start_time,5);assert.equal(render.body.end_time,15);
  assert.equal(render.body.accepted_cost,0);assert.match(render.body.request_id,/^[0-9a-f-]{36}$/);
  assert.equal('json_path' in render.body,false);
  await s.poll();
  assert.deepEqual(s.calls.slice(3).map(c => c.url), ['/api/editor/jobs/job']);
  assert.equal(s.elements.get('#lyric-modal-video').src, undefined);
  assert.equal(s.elements.get('#lyric-result-box').style.display, 'flex');
  await s.elements.get('#btn-preview-lyric-mp4').onclick();
  assert.equal(s.calls.at(-1).url, '/api/exports/job/access?preview=true');
  assert.equal(s.elements.get('#lyric-modal-video').src, 'https://files.invalid/video.mp4');
  assert.equal(s.elements.get('#btn-download-lyric-mp4').download, 'lyric_video.mp4');
});

test('failed alignment save prevents rendering stale lyrics', async () => {
  const s = setup(false);
  await s.start();
  assert.equal(s.calls.length, 1);
  assert.equal(s.elements.get('#btn-start-lyric-export').disabled, false);
  assert.ok(s.notices.some(m => m.includes('保存失败')));
});

test('ambiguous network failures reuse the same export request until source or options change', async () => {
  const s=setup(), original=s.context.window.apiFetch, bodies=[];
  s.context.window.apiFetch=async(url,options)=>{
    if(url.endsWith('/lyric-video')) {bodies.push(JSON.parse(options.body));throw Error('Network timeout after submission');}
    return original(url,options);
  };
  await s.start();await s.start();
  assert.equal(bodies[0].request_id,bodies[1].request_id);
  s.context.state.alignment={lines:[{text:'Changed lyrics',start:0,end:1}]};
  await s.start();assert.notEqual(bodies[1].request_id,bodies[2].request_id);
});

test('closing the export dialog during preview lookup keeps media stopped',async()=>{
 const s=setup();let resolve;
 const original=s.context.window.apiFetch;
 s.context.window.apiFetch=(url,options)=>url.includes('/access?')?new Promise(r=>resolve=r):original(url,options);
 await s.start();await s.poll();
 const pending=s.elements.get('#btn-preview-lyric-mp4').onclick();
 s.elements.get('#btn-close-lyric-modal').handlers.click();
 resolve({ok:true,json:async()=>({url:'https://files.invalid/late.mp4'})});
 await pending;
 assert.equal(s.elements.get('#lyric-modal-video').src,undefined);
 assert.equal(s.elements.get('#lyric-export-modal').style.display,'none');
});

test('formats select only Apple portrait and dual-line karaoke landscape', async()=>{
 const s=setup();
 s.context.document.querySelector=selector=>selector.includes('export-ratio')?{value:'16:9'}:null;
 await s.start();
 assert.equal(s.calls.find(c=>c.url?.endsWith('/lyric-video')).body.template,'tv');
});

test('clip matrix uses section boundaries and never treats pre-chorus as chorus',()=>{
 const s=setup();
 const clips=s.context.buildExportClips({duration:100,sections:[{name:'Pre-Chorus',start:0,end:10},{name:'Verse 1',start:10,end:20},{name:'Chorus',start:20,end:35}],lines:[{text:'pre',start:0,end:8},{text:'verse',start:11,end:19},{text:'chorus',start:21,end:34}]});
 assert.equal(clips.find(c=>c.id==='verse').start_time,11);
 assert.equal(clips.find(c=>c.id==='chorus').start_time,21);
 assert.equal(clips.find(c=>c.id==='chorus').end_time,34);
 assert.equal(s.context.buildExportClips({lines:[{text:'x',start:0,end:4}]}).find(c=>c.id==='verse').available,false);
});

test('multiple selected clips submit separate jobs with independent retry ids',async()=>{
 const s=setup();
 s.context.document.createElement=()=>({appendChild(){},textContent:''});
 s.elements.get('#lyric-batch-results').appendChild=()=>{};
 s.context.$$=selector=>selector==='.export-clip-check'?[{checked:true,dataset:{clipId:'full'}},{checked:true,dataset:{clipId:'chorus'}}]:[];
 s.context.state.alignment={sections:[{name:'Chorus',start:20,end:35}],lines:[{text:'hook',start:21,end:34}]};
 await s.start();
 let jobs=s.calls.filter(c=>c.url?.endsWith('/lyric-video'));
 assert.equal(jobs.length,2);assert.equal(jobs[0].body.start_time,0);assert.equal(jobs[0].body.end_time,null);
 assert.equal(jobs[1].body.start_time,21);assert.equal(jobs[1].body.end_time,34);
 assert.notEqual(jobs[0].body.request_id,jobs[1].body.request_id);
 await s.start();jobs=s.calls.filter(c=>c.url?.endsWith('/lyric-video'));
 assert.equal(jobs[0].body.request_id,jobs[2].body.request_id);
 assert.equal(jobs[1].body.request_id,jobs[3].body.request_id);
});

test('same clip in both formats becomes Apple portrait and Karaoke landscape',async()=>{
 const s=setup();
 // Batch progress rows use DOM elements in the browser.
 s.context.document.createElement=()=>({appendChild(){},textContent:''});
 s.elements.get('#lyric-batch-results').appendChild=()=>{};
 s.context.$$=selector=>selector==='.export-clip-check'?[{checked:true,dataset:{clipId:'full',ratio:'9:16'}},{checked:true,dataset:{clipId:'full',ratio:'16:9'}}]:[];
 await s.start();const jobs=s.calls.filter(c=>c.url?.endsWith('/lyric-video'));
 assert.equal(jobs.length,2);assert.equal(jobs[0].body.template,'apple');assert.equal(jobs[0].body.aspect_ratio,'9:16');
 assert.equal(jobs[1].body.template,'tv');assert.equal(jobs[1].body.aspect_ratio,'16:9');
});

test('matrix export works with a browser NodeList that lacks Array.prototype.filter',async()=>{
 const s=setup();
 s.context.document.createElement=()=>({appendChild(){},textContent:''});
 s.elements.get('#lyric-batch-results').appendChild=()=>{};
 const mockNodeList = (items) => ({
   length: items.length,
   forEach(fn) { items.forEach(fn); },
   [Symbol.iterator]() { return items[Symbol.iterator](); },
   item(i) { return items[i]; }
 });
 s.context.$$=selector=>selector==='.export-clip-check'?mockNodeList([{checked:true,dataset:{clipId:'full',ratio:'9:16'}}]):mockNodeList([]);
 await s.start();
 const jobs=s.calls.filter(c=>c.url?.endsWith('/lyric-video'));
 assert.equal(jobs.length,1);
 assert.equal(jobs[0].body.aspect_ratio,'9:16');
});

test('matrix export gracefully waits for render slots on HTTP 429 instead of crashing',async()=>{
 const s=setup();
 const rows=[];
 s.context.document.createElement=()=>({appendChild(){},set textContent(t){rows.push(t);},get textContent(){return rows.at(-1);}});
 s.elements.get('#lyric-batch-results').appendChild=()=>{};
 let callCount=0, original=s.context.window.apiFetch;
 s.context.window.apiFetch=async(url,options)=>{
   if(url.endsWith('/lyric-video')){
     callCount++;
     s.calls.push({url,body:options.body&&JSON.parse(options.body)});
     if(callCount>2){
       return {ok:false,status:429,json:async()=>({detail:'Your render slots are full. Wait for an existing video to finish.'})};
     }
     return {ok:true,status:200,json:async()=>({task_id:`job-${callCount}`})};
   }
   return original(url,options);
 };
 s.context.$$=selector=>selector==='.export-clip-check'?[
   {checked:true,dataset:{clipId:'full',ratio:'9:16'}},
   {checked:true,dataset:{clipId:'full',ratio:'16:9'}},
   {checked:true,dataset:{clipId:'chorus',ratio:'9:16'}}
 ]:[];
 s.context.state.alignment={sections:[{name:'Chorus',start:20,end:35}],lines:[{text:'hook',start:21,end:34}]};
 await s.start();
 const jobs=s.calls.filter(c=>c.url?.endsWith('/lyric-video'));
 assert.equal(jobs.length,3);
 assert.ok(rows.some(r=>r.includes('Waiting for available render slot')));
});

