const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const { webcrypto } = require('node:crypto');

function runtime(state = {}, items = [], fetcher) {
  let listener, changed;
  const counts = { posts: 0, downloads: 0, ids: [] };
  const context = vm.createContext({ URL, FormData, AbortSignal, AbortController, crypto: webcrypto,
    Date, console, setTimeout, clearTimeout,
    fetch: async (url, options = {}) => {
      if (options.method === 'POST') { counts.posts++; counts.ids.push(options.body.get('request_id')); }
      if (fetcher) return fetcher(url, options, counts);
      return new Response(JSON.stringify(options.method === 'POST' ? { task_id: `job_${counts.posts}`, status: 'pending' } :
        { status: 'completed', result: { download_url: '/file.mp4' } }));
    },
    chrome: {
      runtime: { onMessage: { addListener(fn) { listener = fn; } } },
      storage: { local: {
        get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, state[k]])),
        set: async data => Object.assign(state, data),
        remove: async key => { delete state[key]; },
      } },
      tabs: { sendMessage() {} },
      downloads: {
        onChanged: { addListener(fn) { changed = fn; } },
        search: async ({ id }) => items.filter(i => i.id === id),
        resume: async id => { items.find(i => i.id === id).state = 'in_progress'; },
        download(options, callback) {
          const id = ++counts.downloads + items.length;
          items.push({ id, url: options.url, state: 'in_progress' });
          callback?.(id);
          return Promise.resolve(id);
        },
      },
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), context);
  return { context, counts, state, items, listener: () => listener, changed: () => changed };
}
const track = { songId: 'song-a', title: 'A', is_public: true };

test('simultaneous submissions and worker restart do not render or download twice', async () => {
  const env = runtime();
  await Promise.all([env.context.exportVideoAndDownload(null, track, 'https://server', 'chorus', 30),
    env.context.exportVideoAndDownload(null, track, 'https://server', 'chorus', 30)]);
  assert.equal(env.counts.posts, 1);
  assert.equal(env.counts.downloads, 1);
  const fresh = runtime(env.state, env.items, () => { throw new Error('must reuse existing download'); });
  await fresh.context.finishVideoJob(env.state.videoJobs[0]);
  assert.equal(fresh.counts.downloads, 0);
  await fresh.context.updateDownload(env.items[0].id, 'complete');
  assert.equal(env.state.videoJobs[0].status, 'downloaded');
  assert.equal(env.state.downloads[0].state, 'complete');
});

test('two songs keep separate task records', async () => {
  const env = runtime();
  await env.context.exportVideoAndDownload(null, track, 'https://server', 'chorus', 30);
  await env.context.exportVideoAndDownload(null, { ...track, songId: 'song-b', title: 'B' }, 'https://server', 'verse1', 30);
  assert.equal(env.state.videoJobs.length, 2);
  assert.equal(env.counts.posts, 2);
  assert.equal(new Set(env.counts.ids).size, 2);
});

test('lost submission response retries with the same idempotency key', async () => {
  const env = runtime({}, [], (url, options, counts) => {
    if (options.method === 'POST' && counts.posts === 1) throw new Error('network lost after acceptance');
    return new Response(JSON.stringify(options.method === 'POST' ? { task_id: 'same_job', status: 'pending' } :
      { status: 'completed', result: { download_url: '/file.mp4' } }));
  });
  await assert.rejects(env.context.exportVideoAndDownload(null, track, 'https://server', 'chorus', 30), /Resume/);
  await env.context.exportVideoAndDownload(null, track, 'https://server', 'chorus', 30);
  assert.equal(env.counts.ids[0], env.counts.ids[1]);
  assert.equal(env.state.videoJobs.length, 1);
});

test('server interruption is terminal and does not trigger automatic regeneration', async () => {
  const env = runtime({}, [], (url, options) => new Response(JSON.stringify(options.method === 'POST' ?
    { task_id: 'job', status: 'pending' } : { status: 'interrupted', error: 'Server restarted. Rendering was interrupted.' })));
  await assert.rejects(env.context.exportVideoAndDownload(null, track, 'https://server', 'chorus', 30), /interrupted/);
  assert.equal(env.state.videoJobs[0].status, 'interrupted');
  assert.equal(env.counts.posts, 1);
  assert.equal(env.counts.downloads, 0);
});

test('download interruption remains visible and retry resumes the existing file', async () => {
  const env = runtime();
  await env.context.trackDownload(42, 'A.mp3', 'MP3');
  env.items.push({ id: 42, url: 'https://cdn1.suno.ai/a.mp3', state: 'interrupted' });
  await env.context.updateDownload(42, 'interrupted', 'NETWORK_FAILED');
  assert.equal(env.state.downloads[0].state, 'interrupted');
  const response = await new Promise(resolve => env.listener()({ action: 'RETRY_DOWNLOAD', downloadId: 42 }, {}, resolve));
  assert.equal(response.status, 'ok');
  assert.equal(env.items[0].state, 'in_progress');
  assert.equal(env.counts.downloads, 0);
});
