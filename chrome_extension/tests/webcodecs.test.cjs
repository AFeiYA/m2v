const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const { webcrypto } = require('node:crypto');

const bundleCode = fs.readFileSync(path.join(__dirname, '../webcodecs_bundle.js'), 'utf8');

test('webcodecs_bundle exports all required tools on FoveaWebCodecs', () => {
  const ctx = vm.createContext({ window: {} });
  vm.runInContext(bundleCode, ctx);
  assert.ok(ctx.FoveaWebCodecs);
  assert.equal(typeof ctx.FoveaWebCodecs.isWebCodecsSupported, 'function');
  assert.equal(typeof ctx.FoveaWebCodecs.normalizeProject, 'function');
  assert.equal(typeof ctx.FoveaWebCodecs.resolveClipRange, 'function');
  assert.equal(typeof ctx.FoveaWebCodecs.resolveVisualMode, 'function');
  assert.equal(typeof ctx.FoveaWebCodecs.exportMotionWebCodecs, 'function');
});

test('resolveClipRange correctly identifies sections and clamps bounds', () => {
  const ctx = vm.createContext({ window: {} });
  vm.runInContext(bundleCode, ctx);
  const { resolveClipRange } = ctx.FoveaWebCodecs;

  const sampleProject = {
    title: 'Test Track',
    duration: 120,
    sections: [
      { name: 'Intro', start: 0, end: 15 },
      { name: 'Verse 1', start: 15, end: 45 },
      { name: 'Chorus', start: 45, end: 75 },
    ],
    lines: [
      { start: 1, end: 10, text: 'Hello intro', section: 'Intro' },
      { start: 16, end: 40, text: 'Verse line', section: 'Verse 1' },
      { start: 46, end: 70, text: 'Sing the chorus', section: 'Chorus' },
    ],
  };

  // 1. Chorus
  const chorus = resolveClipRange(sampleProject, 'chorus', 30);
  assert.equal(chorus.start, 45);
  assert.equal(chorus.length, 30);

  // 2. Verse1
  const verse = resolveClipRange(sampleProject, 'verse1', 30);
  assert.equal(verse.start, 15);
  assert.equal(verse.length, 30);

  // 3. Intro
  const intro = resolveClipRange(sampleProject, 'intro', 30);
  assert.equal(intro.start, 0);
  assert.equal(intro.length, 30);

  // 4. Full song
  const full = resolveClipRange(sampleProject, 'full', 0);
  assert.equal(full.start, 0);
  assert.equal(full.length, 120);

  // 5. Clamping when section exceeds duration
  const clamped = resolveClipRange({ ...sampleProject, duration: 60 }, 'chorus', 30);
  assert.equal(clamped.start, 45);
  assert.equal(clamped.length, 15); // 60 - 45 = 15
});

test('offscreen.js responds to CHECK_WEBCODECS_SUPPORT and dispatches RENDER_WEBCODECS', async () => {
  let messageListener;
  const sentMessages = [];
  const fakeBlob = { size: 1024 * 500, type: 'video/mp4' };

  const ctx = vm.createContext({
    URL: {
      createObjectURL: () => 'blob:chrome-extension://test-id/export.mp4',
    },
    Blob: class MockBlob {
      constructor(parts, opts) {
        this.parts = parts;
        this.type = opts?.type;
        this.size = 1000;
      }
    },
    AbortSignal,
    console,
    chrome: {
      runtime: {
        onMessage: {
          addListener: fn => { messageListener = fn; },
        },
        sendMessage: async msg => {
          sentMessages.push(msg);
          return { status: 'ok' };
        },
      },
    },
    fetch: async url => {
      return {
        ok: true,
        status: 200,
        blob: async () => ({ size: 5000 }),
      };
    },
  });

  // Mock FoveaWebCodecs in context
  ctx.FoveaWebCodecs = {
    isWebCodecsSupported: () => true,
    normalizeProject: p => ({ ...p, lines: [{ start: 0, end: 5, text: 'hi' }] }),
    resolveClipRange: () => ({ start: 0, length: 10, title: 'Chorus' }),
    exportMotionWebCodecs: async ({ onProgress }) => {
      onProgress?.({ frame: 30, totalFrames: 300, pct: 10 });
      onProgress?.({ frame: 300, totalFrames: 300, pct: 100 });
      return fakeBlob;
    },
  };

  const offscreenCode = fs.readFileSync(path.join(__dirname, '../offscreen.js'), 'utf8');
  vm.runInContext(offscreenCode, ctx);

  assert.ok(messageListener, 'offscreen message listener registered');

  // Test CHECK_WEBCODECS_SUPPORT
  let checkResponse;
  messageListener({ target: 'offscreen', action: 'CHECK_WEBCODECS_SUPPORT' }, {}, res => {
    checkResponse = res;
  });
  assert.equal(checkResponse.status, 'ok');
  assert.equal(checkResponse.supported, true);

  // Test RENDER_WEBCODECS
  let renderResponse;
  const handled = messageListener({
    target: 'offscreen',
    action: 'RENDER_WEBCODECS',
    requestId: 'req-123',
    project: { title: 'Test Song', duration: 30 },
    audioUrl: 'https://example.com/audio.mp3',
    section: 'chorus',
    duration: 30,
    title: 'Test Song',
  }, {}, res => {
    renderResponse = res;
  });

  assert.equal(handled, true);
  // Wait for async handler
  await new Promise(r => setTimeout(r, 20));

  assert.equal(renderResponse.status, 'ok');
  assert.equal(renderResponse.data.blobUrl, 'blob:chrome-extension://test-id/export.mp4');
  assert.equal(renderResponse.data.filename, 'Test Song_Chorus_9x16.mp4');
  assert.ok(sentMessages.some(m => m.action === 'WEBCODECS_PROGRESS' && m.pct === 100));
});

test('cloud client uses WebCodecs when chrome.offscreen is available', async () => {
  const state = { authToken: 'alice-token', authUserId: 'alice', authServer: 'https://lucazhou-suno2mv-api.hf.space' };
  const calls = [];
  const files = [];
  const items = [];
  let runtimeListeners = [];

  const ctx = vm.createContext({
    URL,
    FormData,
    AbortSignal,
    AbortController,
    crypto: webcrypto,
    console,
    Date,
    setTimeout: fn => { queueMicrotask(fn); return 1; },
    clearTimeout() {},
    chrome: {
      runtime: {
        getURL: path => `chrome-extension://test-id/${path}`,
        onMessage: {
          addListener(fn) { runtimeListeners.push(fn); },
          removeListener(fn) { runtimeListeners = runtimeListeners.filter(l => l !== fn); },
        },
        sendMessage: async msg => {
          if (msg.target === 'offscreen') {
            if (msg.action === 'CHECK_WEBCODECS_SUPPORT') return { status: 'ok', supported: true };
            if (msg.action === 'RENDER_WEBCODECS') {
              return {
                status: 'ok',
                data: {
                  blobUrl: 'blob:chrome-extension://test-id/webcodecs_video.mp4',
                  filename: 'My song_Chorus_9x16.mp4',
                  size: 5000000,
                  duration: 30,
                },
              };
            }
          }
          return { status: 'ok' };
        },
      },
      offscreen: {
        createDocument: async () => {},
        hasDocument: async () => false,
      },
      storage: {
        local: {
          get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, state[k]])),
          set: async d => Object.assign(state, d),
        },
      },
      tabs: { query: async () => [{ id: 9, url: 'https://mv.fovea.si/' }], sendMessage() {} },
      scripting: { executeScript: async () => [{ result: 'fresh-token' }] },
      downloads: {
        onChanged: { addListener() {} },
        search: async ({ id }) => items.filter(i => i.id === id),
        download: async options => {
          files.push(options);
          const id = files.length;
          items.push({ id, state: 'in_progress' });
          return id;
        },
      },
    },
    fetch: async (url, options = {}) => {
      calls.push({ url, options });
      const route = new URL(url).pathname;
      if (route === '/api/auth/me') return Response.json({ id: 'alice', display_name: 'Alice' });
      if (route === '/api/suno/publish_status') return Response.json({ is_public: true });
      if (route === '/api/tasks/from-suno') return Response.json({ task_id: 'song-task' });
      if (route === '/api/tasks/song-task') return Response.json({ status: 'completed' });
      if (route === '/api/cloud-motion/project') {
        return Response.json({
          project: { title: 'My song', duration: 120, lines: [{ start: 0, end: 10, text: 'lyrics' }] },
        });
      }
      if (route.endsWith('/audio')) return new Response(new Uint8Array([0xff, 0xfb, 0x90, 0x44]));
      if (route === '/api/cloud-motion/unlock') return Response.json({ unlocked: true });
      throw Error('Unexpected ' + url);
    },
  });

  ctx.importScripts = file => vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), ctx);

  const song = { songId: '9559f6d1-f7bb-4e3c-94d8-834f6ea4c7d2', title: 'My song', is_public: true };
  const res = await ctx.exportVideoAndDownload(null, song, 'https://mv.fovea.si', 'chorus', 30);

  assert.equal(res.status, 'ok');
  assert.equal(files.length, 1);
  // Video was downloaded from local blob URL directly!
  assert.equal(files[0].url, 'blob:chrome-extension://test-id/webcodecs_video.mp4');
  assert.equal(files[0].filename, 'My song_Chorus_9x16.mp4');

  // Verify server-side /lyric-video was NOT called because WebCodecs handled it!
  const serverLyricVideoCalls = calls.filter(c => c.url.includes('/lyric-video'));
  assert.equal(serverLyricVideoCalls.length, 0);
});

test('cloud client falls back to cloud FFmpeg when WebCodecs offscreen fails', async () => {
  const state = { authToken: 'alice-token', authUserId: 'alice', authServer: 'https://lucazhou-suno2mv-api.hf.space' };
  const calls = [];
  const files = [];
  const items = [];

  const ctx = vm.createContext({
    URL,
    FormData,
    AbortSignal,
    AbortController,
    crypto: webcrypto,
    console,
    Date,
    setTimeout: fn => { queueMicrotask(fn); return 1; },
    clearTimeout() {},
    chrome: {
      runtime: {
        getURL: path => `chrome-extension://test-id/${path}`,
        onMessage: { addListener() {}, removeListener() {} },
        sendMessage: async () => {
          throw new Error('Offscreen document crashed or GPU hardware acceleration unavailable');
        },
      },
      offscreen: {
        createDocument: async () => {},
        hasDocument: async () => true,
      },
      storage: {
        local: {
          get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, state[k]])),
          set: async d => Object.assign(state, d),
        },
      },
      tabs: { query: async () => [{ id: 9, url: 'https://mv.fovea.si/' }], sendMessage() {} },
      scripting: { executeScript: async () => [{ result: 'fresh-token' }] },
      downloads: {
        onChanged: { addListener() {} },
        search: async ({ id }) => items.filter(i => i.id === id),
        download: async options => {
          files.push(options);
          const id = files.length;
          items.push({ id, state: 'in_progress' });
          return id;
        },
      },
    },
    fetch: async (url, options = {}) => {
      calls.push({ url, options });
      const route = new URL(url).pathname;
      if (route === '/api/auth/me') return Response.json({ id: 'alice', display_name: 'Alice' });
      if (route === '/api/suno/publish_status') return Response.json({ is_public: true });
      if (route === '/api/tasks/from-suno') return Response.json({ task_id: 'song-task' });
      if (route === '/api/tasks/song-task') return Response.json({ status: 'completed' });
      if (route.endsWith('/lyric-video') || route === '/api/cloud-motion/render') return Response.json({ id: 'abc999', task_id: 'abc999' });
      if (route === '/api/cloud-motion/render/abc999' || route === '/api/editor/jobs/abc999') return Response.json({ status: 'done', progress: 100, frames: 100, total: 100 });
      throw Error('Unexpected ' + url);
    },
  });

  ctx.importScripts = file => vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), ctx);

  const song = { songId: '9559f6d1-f7bb-4e3c-94d8-834f6ea4c7d2', title: 'My song', is_public: true };
  const res = await ctx.exportVideoAndDownload(null, song, 'https://mv.fovea.si', 'chorus', 30);

  assert.equal(res.status, 'ok');
  assert.equal(files.length, 1);
  // Downloaded from cloud endpoint via fallback!
  assert.ok(files[0].url.includes('/abc999/download') || files[0].url.includes('/jobs/abc999/video'));
  const cloudRenderCalls = calls.filter(c => c.options.method === 'POST' && (c.url.includes('/cloud-motion/render') || c.url.includes('/lyric-video')));
  assert.equal(cloudRenderCalls.length, 1, 'Fell back to server cloud-motion/render when WebCodecs failed');
});

test('user-saved motion design is directly used without clobbering, while novice song gets default Apple 9:16', async () => {
  const state = { authToken: 'alice-token', authUserId: 'alice', authServer: 'https://mv.fovea.si' };
  const calls = [];
  const files = [];
  let capturedMessage = null;

  const ctx = vm.createContext({
    URL,
    FormData,
    AbortSignal,
    AbortController,
    crypto: webcrypto,
    console,
    Date,
    setTimeout: fn => { queueMicrotask(fn); return 1; },
    clearTimeout() {},
    chrome: {
      runtime: {
        getURL: path => `chrome-extension://test-id/${path}`,
        onMessage: { addListener() {}, removeListener() {} },
        sendMessage: async msg => {
          if (msg.target === 'offscreen' && msg.action === 'CHECK_WEBCODECS_SUPPORT') {
            return { status: 'ok', supported: true };
          }
          if (msg.target === 'offscreen' && msg.action === 'RENDER_WEBCODECS') {
            capturedMessage = msg;
            return {
              status: 'ok',
              data: {
                blobUrl: 'blob:chrome-extension://test-id/webcodecs_video.mp4',
                filename: `${msg.title}_Chorus_${msg.aspect === '16:9' ? '16x9' : '9x16'}.mp4`,
              },
            };
          }
          return null;
        },
      },
      offscreen: {
        createDocument: async () => {},
        hasDocument: async () => true,
      },
      storage: {
        local: {
          get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, state[k]])),
          set: async d => Object.assign(state, d),
        },
      },
      tabs: { query: async () => [{ id: 9, url: 'https://mv.fovea.si/' }], sendMessage() {} },
      scripting: { executeScript: async () => [{ result: 'fresh-token' }] },
      downloads: {
        download: async opt => {
          const id = files.length + 1;
          files.push({ id, ...opt, state: 'complete' });
          return id;
        },
      },
    },
    fetch: async (url, options = {}) => {
      calls.push({ url, options });
      const route = new URL(url).pathname;
      if (route === '/api/auth/me') return Response.json({ id: 'alice', display_name: 'Alice' });
      if (route === '/api/suno/publish_status') return Response.json({ is_public: true });
      if (route === '/api/tasks/from-suno') return Response.json({ task_id: 'saved-song-task' });
      if (route === '/api/tasks/saved-song-task') return Response.json({ status: 'completed' });
      if (route === '/api/cloud-motion/project') {
        return Response.json({
          has_saved_design: true,
          has_saved_identity: true,
          project: {
            title: 'Custom TV Track',
            duration: 120,
            lines: [{ start: 0, end: 10, text: 'lyrics' }],
            motion_design: {
              version: 'motion-design-v1',
              active_mode: 'tv',
              theme: { palette: 'sunset', background: 'dark' },
              modes: { tv: { aspect: '16:9', font_scale: 1.2, preview_seconds: 3.0 } },
            },
            song_identity: {
              title: 'Custom TV Track',
              artist: 'DJ Producer',
              style: 'classic',
              show_signature: false,
              show_intro: false,
              show_outro: false,
              cover_mode: 'card',
            },
          },
        });
      }
      if (route.endsWith('/audio')) return new Response(new Uint8Array([0xff, 0xfb, 0x90, 0x44]));
      if (route === '/api/cloud-motion/unlock') return Response.json({ unlocked: true });
      throw Error('Unexpected ' + url);
    },
  });

  ctx.importScripts = file => vm.runInContext(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), ctx);

  const song = { songId: 'custom-song-uuid', title: 'Custom TV Track', is_public: true };
  const res = await ctx.exportVideoAndDownload(null, song, 'https://mv.fovea.si', 'chorus', 30);

  assert.equal(res.status, 'ok');
  assert.ok(capturedMessage, 'offscreen message captured');
  // 1. Verify user's saved TV mode and 16:9 aspect were preserved, NOT clobbered by Apple mode!
  assert.equal(capturedMessage.visualMode, 'tv');
  assert.equal(capturedMessage.aspect, '16:9');
  assert.equal(capturedMessage.project.motion_design.active_mode, 'tv');
  assert.equal(capturedMessage.project.motion_design.theme.palette, 'sunset');
  assert.equal(capturedMessage.project.song_identity.style, 'classic');
  assert.equal(capturedMessage.project.song_identity.show_signature, false);

  // 2. Verify filename accurately reflects 16x9
  assert.equal(files[0].filename, 'Custom TV Track_Chorus_16x9.mp4');
});
