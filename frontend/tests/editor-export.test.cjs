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
    if (url.endsWith('/lyric-video')) return {ok: true, json: async () => ({task_id: 'job'})};
    if (url.endsWith('/video')) return {ok: true, blob: async () => ({})};
    return {ok: true, json: async () => ({status: 'completed', progress: 100, result: {video_url: '/api/editor/jobs/job/video'}})};
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  vm.runInContext('initLyricExportModal()', context);
  return {elements, calls, notices, start: () => element('#btn-start-lyric-export').handlers.click(), poll: () => poll()};
}

test('cloud modal saves edits then exports a selected segment and downloads through owned jobs', async () => {
  const s = setup();
  await s.start();
  assert.equal(s.calls[0].saved, true);
  assert.equal(s.calls[1].url, '/api/editor/tasks/song/lyric-video');
  assert.equal(s.calls[1].body.start_time, 5);
  assert.equal(s.calls[1].body.end_time, 15);
  assert.equal('json_path' in s.calls[1].body, false);
  await s.poll();
  assert.deepEqual(s.calls.slice(2).map(c => c.url), ['/api/editor/jobs/job', '/api/editor/jobs/job/video']);
  assert.equal(s.elements.get('#lyric-modal-video').src, 'blob:video');
  assert.equal(s.elements.get('#btn-download-lyric-mp4').download, 'lyric_video.mp4');
});

test('failed alignment save prevents rendering stale lyrics', async () => {
  const s = setup(false);
  await s.start();
  assert.equal(s.calls.length, 1);
  assert.equal(s.elements.get('#btn-start-lyric-export').disabled, false);
  assert.ok(s.notices.some(m => m.includes('保存失败')));
});
