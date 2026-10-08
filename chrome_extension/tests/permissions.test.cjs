const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const manifest = require('../manifest.json');

test('content scripts without permissions API leave audio permission checks to the worker', async () => {
  const context = vm.createContext({ URL, chrome: {} });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../ui.js'), 'utf8'), context);
  const track = {songId: 'selected', audioUrl: 'https://cdn1.suno.ai/song.mp3'};
  await context.FoveaUI.allowAudio(track);
  assert.equal(track.audioUrl, 'https://cdn1.suno.ai/song.mp3');
});

test('popup denial of extra audio-host access selects server fallback', async () => {
  const context = vm.createContext({ URL, chrome: { permissions: {
    contains: async () => false, request: async () => false,
  } } });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../ui.js'), 'utf8'), context);
  const track = {songId: 'selected', audioUrl: 'https://media.cloudfront.net/song.mp3'};
  await context.FoveaUI.allowAudio(track);
  assert.equal(track.audioUrl, '');
});

test('rights confirmation is song-specific, cancellable and does not claim verification', () => {
  const prompts = [];
  const context = vm.createContext({ confirm: text => { prompts.push(text); return false; } });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../ui.js'), 'utf8'), context);
  assert.equal(context.FoveaUI.confirmRights({title: 'A', is_public: true}), false);
  context.confirm = text => { prompts.push(text); return true; };
  assert.equal(context.FoveaUI.confirmRights({title: 'B', is_public: true}), true);
  assert.match(prompts[0], /Song: A/);
  assert.match(prompts[1], /Song: B/);
  assert.match(prompts[0], /does not verify ownership/);
  assert.match(prompts[0], /approved download channels/);
  assert.throws(() => context.FoveaUI.confirmRights({is_public: false}), /not published/);
  assert.equal(prompts.length, 2);
});

test('default permissions do not include access to every website', () => {
  assert.ok(!manifest.host_permissions.includes('<all_urls>'));
  assert.ok(!manifest.permissions.includes('tabs'));
  assert.ok(!manifest.host_permissions.some(p => /amazonaws|cloudfront/.test(p)));
});

test('custom server uses exact-origin permission and rejects insecure cloud addresses', async () => {
  const requested = [];
  const context = vm.createContext({ URL, chrome: { permissions: {
    contains: async () => false, request: async value => { requested.push(value.origins[0]); return true; },
  } } });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../ui.js'), 'utf8'), context);
  assert.equal(await context.FoveaUI.allowServer('https://custom.example:8443'), 'https://custom.example:8443');
  assert.equal(requested[0], 'https://custom.example:8443/*');
  for (const url of ['http://custom.example', 'https://user:secret@custom.example', 'https://custom.example/api']) {
    await assert.rejects(context.FoveaUI.allowServer(url));
  }
  assert.equal(requested.length, 1);
  assert.equal(context.FoveaUI.serverUrl('http://127.0.0.1:8768'), 'http://127.0.0.1:8768');
  context.chrome.permissions.request = async () => false;
  await assert.rejects(context.FoveaUI.allowServer('https://denied.example'), /not granted/);
});
