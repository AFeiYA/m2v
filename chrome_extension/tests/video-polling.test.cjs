const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
function environment(fetch) {
  const context = vm.createContext({ fetch, AbortSignal, Date, URL, console, setTimeout,
    chrome: { runtime: { onMessage: { addListener() {} } } } });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), context);
  return context;
}
const json = value => new Response(JSON.stringify(value));
test('502 and network interruption recover without submitting another job', async () => {
  const responses = [new Response('Bad gateway', { status: 502 }), new Error('offline'),
    json({ status: 'running', progress: 60, message: 'aligning' }),
    json({ status: 'completed', result: { download_url: '/download.mp4' } })];
  let calls = 0;
  const progress = [];
  const context = environment(async url => {
    assert.match(url, /task_status\?task_id=lyric_abc$/);
    const response = responses[calls++];
    if (response instanceof Error) throw response;
    return response;
  });
  const result = await context.pollLyricVideoTask('https://server', 'lyric_abc', t => progress.push(t), { sleep: async () => {} });
  assert.equal(result.download_url, '/download.mp4');
  assert.equal(calls, 4);
  assert.ok(progress.some(t => t.message === 'aligning'));
});
test('backend failure is not swallowed and retried as a network failure', async () => {
  const context = environment(async () => json({ status: 'failed', error: 'alignment failed' }));
  await assert.rejects(context.pollLyricVideoTask('https://server', 'job'), /alignment failed/);
});
test('lost task after restart provides ID and does not loop forever', async () => {
  const context = environment(async () => new Response('{}', { status: 404 }));
  await assert.rejects(context.pollLyricVideoTask('https://server', 'job'), /server may have restarted.*job/);
});
test('waiting deadline is not described as backend cancellation', async () => {
  const context = environment(async () => { throw new Error('must not fetch'); });
  await assert.rejects(context.pollLyricVideoTask('https://server', 'job', () => {}, { timeoutMs: 0 }), /job was not cancelled.*Resume last video.*job/);
});
test('resuming and simultaneous queries download once without another POST', async () => {
  const context = environment(async (url, options) => {
    assert.match(url, /task_status/);
    assert.equal(options.method, undefined);
    return json({ status: 'completed', result: { download_url: '/video.mp4' } });
  });
  let downloads = 0;
  let removed = 0;
  context.chrome.downloads = { download: (options, callback) => {
    downloads++;
    assert.equal(options.url, 'https://server/video.mp4');
    callback(123);
  } };
  context.chrome.storage = { local: {
    get: async () => ({ pendingVideoJob: { taskId: 'job' } }),
    remove: async () => { removed++; },
  } };
  const job = { targetServer: 'https://server', taskId: 'job', title: 'song', section: 'chorus' };
  const results = await Promise.all([context.finishVideoJob(job), context.finishVideoJob(job)]);
  assert.equal(downloads, 1);
  assert.equal(removed, 1);
  assert.equal(results[0].filename, 'song_Chorus_9x16.mp4');
});
