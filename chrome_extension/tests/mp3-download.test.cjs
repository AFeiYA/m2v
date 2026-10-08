const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function background(bytes, { status = 206, downloadError = null } = {}) {
  const downloads = [];
  let listener;
  let fetchCount = 0;
  const runtime = { lastError: null, onMessage: { addListener(fn) { listener = fn; } } };
  const context = vm.createContext({
    URL, AbortController, setTimeout, clearTimeout, setInterval, clearInterval, console,
    chrome: { runtime, downloads: { download(options, callback) {
      downloads.push(options);
      runtime.lastError = downloadError;
      callback(downloadError ? undefined : 123);
      runtime.lastError = null;
    } } },
    fetch: async () => {
      fetchCount++;
      let consumed = false;
      return { ok: status < 400, status, body: { getReader() { return {
        read: async () => consumed ? { done: true } : (consumed = true, { done: false, value: Uint8Array.from(bytes) }),
        cancel: async () => {},
      }; } } };
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), context);
  return { downloads, get fetchCount() { return fetchCount; }, send: track => new Promise(resolve => {
    assert.equal(listener({ action: 'DOWNLOAD_TRACK_MP3', track }, {}, resolve), true);
  }) };
}
const track = { title: '兔子洞 / Rabbit Hole', audioUrl: 'https://cdn1.suno.ai/song.mp3', is_public: true };

test('worker refuses an ungranted audio host before fetching', async () => {
  let fetched = false;
  const context = vm.createContext({ URL, console,
    chrome: { runtime: {onMessage: {addListener() {}}}, permissions: {contains: async () => false} },
    fetch: async () => { fetched = true; },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), context);
  await assert.rejects(context.downloadOriginalMp3(track), /Audio-host access is not granted/);
  assert.equal(fetched, false);
});

test('unpublished MP3 fails before any audio fetch or download', async () => {
  const bg = background([73, 68, 51]);
  assert.match((await bg.send({ ...track, is_public: false })).message, /not published/);
  assert.equal(bg.fetchCount, 0);
  assert.equal(bg.downloads.length, 0);
});

test('downloads ID3 MP3 with safe filename and without any render API', async () => {
  const bg = background([73, 68, 51, 4, 0, 0, 0, 0, 0, 0]);
  const response = await bg.send(track);
  assert.equal(response.status, 'ok');
  assert.equal(bg.downloads[0].filename, '兔子洞 _ Rabbit Hole.mp3');
  assert.equal(bg.downloads[0].conflictAction, 'uniquify');
  assert.equal(bg.fetchCount, 1);
});
test('accepts MP3 frame header without ID3', async () => {
  assert.equal((await background([255, 251, 144, 0]).send(track)).status, 'ok');
});
test('rejects MP4, HTML, AAC and empty responses without downloading', async () => {
  for (const bytes of [[0, 0, 0, 24, 102, 116, 121, 112], [60, 104, 116, 109, 108], [255, 241, 80, 0], []]) {
    const bg = background(bytes);
    assert.equal((await bg.send(track)).status, 'error');
    assert.equal(bg.downloads.length, 0);
  }
});
test('rejects missing, insecure and unrelated media URLs before fetching', async () => {
  for (const audioUrl of ['', 'blob:example', 'http://cdn1.suno.ai/song.mp3', 'https://suno.ai.evil.example/song.mp3']) {
    const bg = background([73, 68, 51]);
    assert.equal((await bg.send({ ...track, audioUrl })).status, 'error');
    assert.equal(bg.fetchCount, 0);
  }
});
test('reports CDN denial and Chrome download errors', async () => {
  const denied = background([], { status: 403 });
  assert.match((await denied.send(track)).message, /403/);
  const failed = background([73, 68, 51], { downloadError: { message: 'disk error' } });
  assert.match((await failed.send(track)).message, /disk error/);
});

function queryTrack({ songId = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', clip, source = '', metadata = null }) {
  let handler;
  let reported;
  const audio = { currentSrc: source, paused: false, currentTime: 1 };
  const context = vm.createContext({
    Blob, File: class {}, URL: { createObjectURL() {} }, navigator: { mediaSession: { metadata } },
    console, setTimeout,
    document: {
      title: 'Song | Suno', addEventListener() {}, querySelector() { return null; },
      querySelectorAll(selector) { return selector === 'audio' ? [audio] : []; },
    },
    window: {
      location: { pathname: `/song/${songId}` }, __FOVEA_CLIPS__: clip ? { [songId]: clip } : {},
      fetch: async () => {}, addEventListener(_, fn) { handler = fn; },
      postMessage(data) { reported = data; },
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../inject.js'), 'utf8'), context);
  handler({ source: context.window, data: { type: 'FOVEA_QUERY_TRACK_INFO' } });
  return reported.track;
}
test('uses current clip audio URL instead of a stale player source', () => {
  const result = queryTrack({ clip: { title: 'Current', audio_url: track.audioUrl }, source: 'https://cdn1.suno.ai/other.mp3' });
  assert.equal(result.audioUrl, track.audioUrl);
  assert.equal(result.title, 'Current');
});
test('player fallback must match the selected song UUID', () => {
  const id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
  assert.equal(queryTrack({ source: `https://cdn1.suno.ai/${id}.mp3` }).audioUrl, `https://cdn1.suno.ai/${id}.mp3`);
  assert.equal(queryTrack({ source: 'https://cdn1.suno.ai/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.mp3' }).audioUrl, '');
  assert.equal(queryTrack({ source: 'blob:old-song' }).audioUrl, '');
});

test('missing MP3, CDN 403 and MP4 source use existing download-only route', async () => {
  for (const source of ['missing', 'denied', 'mp4', 'uuid']) {
    const calls = [];
    const downloads = [];
    const context = vm.createContext({
      URL, FormData, AbortController, AbortSignal, Date, setTimeout, clearTimeout, console,
      chrome: { runtime: { onMessage: { addListener() {} } }, downloads: { download(options, cb) { downloads.push(options); cb(42); } } },
      fetch: async (url, options = {}) => {
        calls.push({ url, options });
        if (url.includes('/publish_status')) return new Response(JSON.stringify({ is_public: true }));
        if (options.headers?.Range) return source === 'denied' ? new Response('', { status: 403 }) :
          new Response(Uint8Array.from([0, 0, 0, 24, 102, 116, 121, 112]), { status: 206 });
        throw new Error('fallback must be a Chrome download, not a new export task');
      },
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), context);
    const songId = source === 'uuid' ? 'ddb1252a-3347-4d6a-8b2b-63d05c915a87' : 'selected-song';
    const result = await context.downloadTrackMp3({ title: 'Song', songId, is_public: true,
      audioUrl: ['missing', 'uuid'].includes(source) ? '' : 'https://cdn1.suno.ai/source.mp4' }, 'http://127.0.0.1:8000');
    assert.equal(result.filename, 'Song.mp3');
    const downloadUrl = new URL(downloads[0].url);
    assert.equal(downloadUrl.origin, 'http://127.0.0.1:8000');
    assert.equal(downloadUrl.pathname, '/api/suno/download_mp3');
    assert.equal(downloadUrl.searchParams.get('url'), `https://suno.com/${source === 'uuid' ? 'song' : 's'}/${songId}`);
    assert.equal(calls.length, ['missing', 'uuid'].includes(source) ? 1 : 2);
    assert.equal(downloads[0].filename, 'Song.mp3');
  }
});

test('unknown publication is verified and private song never starts a download', async () => {
  const downloads = [];
  const calls = [];
  const context = vm.createContext({
    URL, AbortController, setTimeout, clearTimeout, console,
    chrome: { runtime: { onMessage: { addListener() {} } }, downloads: { download(options) { downloads.push(options); } } },
    fetch: async url => {
      calls.push(url);
      return new Response(JSON.stringify({ detail: 'Song is not published. Use Publish in Suno first.' }), { status: 400 });
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), context);
  await assert.rejects(context.downloadTrackMp3({ ...track, is_public: null, songId: 'selected-song' }, 'http://127.0.0.1:8000'), /not published/);
  assert.equal(calls.length, 1);
  assert.match(calls[0], /publish_status/);
  assert.equal(downloads.length, 0);
});
