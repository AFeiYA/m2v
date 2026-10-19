const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const dashboardSource = fs.readFileSync(path.join(__dirname, '../dashboard.js'), 'utf8');

function createDoc() {
  const elements = new Map();
  function element(sel) {
    if (!elements.has(sel)) elements.set(sel, { style: {}, dataset: {}, addEventListener() {} });
    return elements.get(sel);
  }
  return {
    querySelector: element,
    querySelectorAll: () => [],
    addEventListener() {},
    createElement(tag) {
      return {
        _v: '',
        set textContent(v) { this._v = v; },
        get textContent() { return this._v; },
        get innerHTML() { return this._v.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
      };
    }
  };
}

test('song card with apostrophe does not generate dangerous inline script or broken syntax', () => {
  const loc = { origin: 'https://test.local', hostname: 'test.local', host: 'test.local', pathname: '/', hash: '', search: '' };
  const context = {
    window: { location: loc },
    document: createDoc(),
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    location: loc,
    console: { log() {}, warn() {}, error() {} },
    URLSearchParams,
  };
  vm.createContext(context);
  vm.runInContext(dashboardSource, context);

  const songWithApostrophe = {
    id: 'song-apo-1',
    title: "It's My Life (Don't Stop)",
    artist: "Bon Jovi's Tribute",
    status: 'completed',
    version_count: 1,
    export_count: 0,
    updated_at: new Date().toISOString(),
    current_task_id: "ver-apo-1",
    versions: [
      { id: "ver-apo-1", title: "It's My Life", status: "completed", editable: true, updated_at: new Date().toISOString(), export_count: 0 }
    ]
  };

  const html = context.renderSong(songWithApostrophe);
  // Must NOT have onclick with unescaped single quotes
  assert.equal(html.includes("onclick=\"window.openLyricStudio"), false);
  // Must use data-action="open-studio"
  assert.equal(html.includes('data-action="open-studio"'), true);
  assert.equal(html.includes('data-studio="lyric"'), true);
});

test('logout cleans up studio iframes and active song context', async () => {
  const doc = createDoc();
  const lyricFrame = { style: {}, dataset: { loadedSongId: 'test-song' }, src: '/lyric-editor/test-song', addEventListener() {} };
  const motionFrame = { style: {}, dataset: { loadedSongId: 'test-song' }, src: '/motion-studio?project=test-song', addEventListener() {} };
  const origQuery = doc.querySelector;
  doc.querySelector = sel => {
    if (sel === '#iframe-lyric-editor') return lyricFrame;
    if (sel === '#iframe-motion-studio') return motionFrame;
    return origQuery(sel);
  };
  const sessionStore = new Map([['m2v_active_song', JSON.stringify({ id: 'test-song', title: 'Test Song' })]]);
  const loc = { origin: 'https://test.local', hostname: 'test.local', host: 'test.local', pathname: '/', hash: '', search: '' };
  const context = {
    window: {
      location: loc,
      m2vActiveSong: { id: 'test-song', title: 'Test Song' },
      m2vAuth: { logout: async () => {} }
    },
    document: doc,
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    sessionStorage: { getItem: k => sessionStore.get(k), removeItem: k => sessionStore.delete(k) },
    location: loc,
    console: { log() {}, warn() {}, error() {} },
    URLSearchParams,
  };
  vm.createContext(context);
  vm.runInContext(dashboardSource, context);

  await context.logout();
  assert.equal(context.window.m2vActiveSong, null);
  assert.equal(sessionStore.has('m2v_active_song'), false);
  assert.equal(lyricFrame.src, 'about:blank');
  assert.equal(motionFrame.src, 'about:blank');
  assert.equal(lyricFrame.dataset.loadedSongId, undefined);
  assert.equal(motionFrame.dataset.loadedSongId, undefined);
});
