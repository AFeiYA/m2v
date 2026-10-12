const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../local/common.js'), 'utf8').split('\nconst state =')[0];

function setup({provider = 'firebase', user = true, fail = false} = {}) {
  const values = new Map([['m2v_token', 'expired-B'], ['m2v_refresh', 'refresh-A'], ['m2v_auth_provider', provider]]);
  const calls = [], loads = [];
  const context = {
    window: {M2V_API_BASE: 'https://api.example', location: {hostname: 'mv.fovea.si'}, m2vAuth: {
      loginWithGoogle: async () => {values.set('m2v_token', 'google-B'); return {};},
    }},
    localStorage: {getItem: k => values.get(k) || null, setItem: (k,v) => values.set(k,v), removeItem: k => values.delete(k)},
    firebase: {auth: () => ({currentUser: user ? {getIdToken: async () => {
      if (fail) throw Error('refresh failed');
      return 'fresh-B';
    }} : null})},
    Headers, URL: {createObjectURL: () => 'blob:audio'},
    fetch: async (url, options) => {
      calls.push({url, token: options.headers?.get ? options.headers.get('Authorization') : null});
      if (url.endsWith('/api/auth/refresh')) return {ok: true, json: async () => ({access_token: 'fresh-A', refresh_token: 'next-A'})};
      const status = calls.length === 1 ? 401 : 200;
      return {status, ok: status === 200, blob: async () => ({})};
    },
    player: {load: async url => loads.push(url)},
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return {calls, values, loads, run: code => vm.runInContext(code, context)};
}

test('editor audio refreshes Google authentication and loads an authenticated blob', async () => {
  const s = setup();
  await s.run("loadEditorAudio(player, '/api/editor/tasks/song/audio')");
  assert.deepEqual(s.calls.map(c => c.token), ['Bearer expired-B', 'Bearer fresh-B']);
  assert.equal(s.calls.some(c => c.url.includes('token=')), false);
  assert.deepEqual(s.loads, ['blob:audio']);
});

for (const options of [{fail: true}, {user: false}]) {
  test(`editor never refreshes a Google session as another local account ${JSON.stringify(options)}`, async () => {
    const s = setup(options);
    const r = await s.run("apiFetch('/api/editor/songs')");
    assert.equal(r.status, 401);
    assert.equal(s.calls.length, 1);
  });
}

test('editor local-account sessions can refresh', async () => {
  const s = setup({provider: 'local', user: false});
  const r = await s.run("apiFetch('/api/editor/songs')");
  assert.equal(r.status, 200);
  assert.equal(s.calls[2].token, 'Bearer fresh-A');
});

test('editor Google login discards a previous local refresh token', async () => {
  const s = setup({provider: 'local', user: false});
  await s.run('editorLogin()');
  assert.equal(s.values.has('m2v_refresh'), false);
  assert.equal(s.values.get('m2v_auth_provider'), 'firebase');
});
