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
