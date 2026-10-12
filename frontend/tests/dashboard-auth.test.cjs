const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../dashboard.js'), 'utf8');

function setup({firebaseUser = true, failRefresh = false, provider = null} = {}) {
  const values = new Map([['m2v_token', 'expired-B'], ['m2v_refresh', 'refresh-A']]);
  if (provider) values.set('m2v_auth_provider', provider);
  const requests = [], alerts = [], elements = new Map();
  let sdkCalls = 0, downloads = 0, logoutCalls = 0;
  function element(selector) {
    if (!elements.has(selector)) elements.set(selector, {
      style: {}, handlers: {}, addEventListener(event, handler) { this.handlers[event] = handler; },
    });
    return elements.get(selector);
  }
  const location = {hostname: 'mv.fovea.si', host: 'mv.fovea.si', origin: 'https://mv.fovea.si', search: ''};
  const user = {getIdToken: async () => {
    sdkCalls++;
    if (failRefresh) throw new Error('SDK unavailable');
    return 'fresh-B';
  }};
  const context = {
    window: {location, m2vAuth: {
      logout: async () => {logoutCalls++;},
      loginWithGoogle: async () => ({user, idToken: 'google-B'}),
      getIdToken: async () => values.get('m2v_token'),
    }}, location,
    firebase: {auth: () => ({currentUser: firebaseUser ? user : null})},
    localStorage: {getItem: k => values.get(k) || null, setItem: (k,v) => values.set(k,v), removeItem: k => values.delete(k)},
    document: {querySelector: element, querySelectorAll: () => [], addEventListener() {},
      createElement: () => ({click() {downloads++;}, remove() {}}), body: {appendChild() {}}},
    console: {log() {}, warn() {}, error() {}},
    URL: {createObjectURL: () => 'blob:test', revokeObjectURL() {}}, URLSearchParams,
    setTimeout() {}, clearInterval() {}, alert: msg => alerts.push(msg),
    fetch: async (url, options = {}) => {
      requests.push({url, authorization: options.headers?.Authorization});
      if (url.endsWith('/api/auth/refresh')) return {ok: true, json: async () => ({access_token: 'access-A', refresh_token: 'new-refresh-A'})};
      const status = requests.length === 1 ? 401 : 200;
      return {status, ok: status === 200, headers: {get: () => 'application/json'}, json: async () => ({detail: 'expired'}), blob: async () => ({})};
    },
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return {context, requests, alerts, values, elements, element,
    run: code => vm.runInContext(code, context),
    stats: () => ({sdkCalls, downloads, logoutCalls})};
}

test('Firebase refresh retries with the same Firebase account', async () => {
  const s = setup();
  await s.run("api('/api/auth/me')");
  assert.equal(s.requests.length, 2);
  assert.equal(s.requests[1].authorization, 'Bearer fresh-B');
});

test('failed Firebase refresh never uses a retained local account token', async () => {
  const s = setup({failRefresh: true});
  await s.run("api('/api/auth/me')");
  assert.equal(s.requests.length, 1);
  assert.equal(s.values.has('m2v_refresh'), false);
  assert.equal(s.stats().logoutCalls, 1);
});

test('missing Firebase session cannot refresh using cached expired token or local account', async () => {
  const s = setup({firebaseUser: false, provider: 'firebase'});
  await s.run("api('/api/auth/me')");
  assert.equal(s.requests.length, 1);
  assert.equal(s.values.has('m2v_refresh'), false);
});

test('local accounts still refresh using local refresh tokens', async () => {
  const s = setup({firebaseUser: false, provider: 'local'});
  await s.run("api('/api/auth/me')");
  assert.equal(s.requests.length, 3);
  assert.equal(s.requests[2].authorization, 'Bearer access-A');
});

test('Google login removes previous local refresh credentials', async () => {
  const s = setup();
  s.run('loadUser = async () => true; showApp = () => {}; initAuth()');
  await s.element('#btn-google-login').handlers.click();
  assert.equal(s.values.has('m2v_refresh'), false);
  assert.equal(s.values.get('m2v_auth_provider'), 'firebase');
});

test('downloads refresh expired access tokens and never put credentials in URLs', async () => {
  const s = setup();
  await s.run("handleTaskAction({currentTarget: {textContent: 'Download', dataset: {action: 'download', task: 'test', type: 'mp3'}}})");
  assert.equal(s.requests.length, 2);
  assert.equal(s.requests[1].authorization, 'Bearer fresh-B');
  assert.ok(s.requests.every(r => !r.url.includes('token=')));
  assert.equal(s.stats().downloads, 1);
  assert.deepEqual(s.alerts, []);
});

test('backend failure is reported as a server error instead of invalid identity', async () => {
  const s = setup();
  s.context.fetch = async () => ({status: 500, ok: false, headers: {get: () => 'text/plain'}});
  s.run('initAuth()');
  await s.element('#btn-google-login').handlers.click();
  assert.match(s.element('#auth-error').textContent, /HTTP 500/);
  assert.match(s.element('#auth-error').textContent, /后端读取账户信息失败/);
});
