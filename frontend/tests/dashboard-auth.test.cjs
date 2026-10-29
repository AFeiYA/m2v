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
      style: {}, handlers: {},
      classList: {
        _classes: new Set(),
        add(c) { this._classes.add(c); },
        remove(c) { this._classes.delete(c); },
        contains(c) { return this._classes.has(c); },
      },
      addEventListener(event, handler) { this.handlers[event] = handler; },
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
    window: {location, addEventListener() {}, m2vAuth: {
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
  assert.match(s.element('#auth-error').textContent, /Unable to load account/);
});

test('email form signs in through Firebase without sending passwords to Python', async () => {
  const s = setup();
  let submitted;
  s.context.window.m2vAuth.loginWithEmail = async (email, password) => {
    submitted = {email, password}; return {idToken: 'email-B'};
  };
  s.run('loadUser = async () => true; showApp = () => {}; initAuth()');
  s.element('#auth-email').value = 'artist@example.com';
  s.element('#auth-password').value = 'long-password';
  s.element('#auth-username').value = '';
  await s.element('#auth-form').handlers.submit({preventDefault() {}});
  assert.deepEqual(submitted, {email: 'artist@example.com', password: 'long-password'});
  assert.equal(s.requests.length, 0);
  assert.equal(s.values.get('m2v_token'), 'email-B');
  assert.equal(s.values.has('m2v_refresh'), false);
});


test('API settings are hidden from ordinary users and available in explicit dev mode', () => {
  const normal = setup();
  normal.run('initApiConfig()');
  assert.equal(normal.element('#api-config-login').style.display, 'none');
  assert.equal(normal.element('#btn-config-api-app').style.display, 'none');
  assert.equal(normal.element('#btn-config-api').handlers.click, undefined);
  for (const query of ['?dev=1', '?debug=1', '?mode=dev']) {
    const dev = setup();
    dev.context.location.search = query;
    dev.run('initApiConfig()');
    assert.equal(dev.element('#api-config-login').style.display, '');
    assert.equal(typeof dev.element('#btn-config-api').handlers.click, 'function');
  }
  const disabled = setup();
  disabled.context.location.search = '?dev=0';
  disabled.run('initApiConfig()');
  assert.equal(disabled.element('#api-config-login').style.display, 'none');
});

test('backend-served sandbox uses its injected API even with a saved production endpoint',()=>{
 const s=setup();
 s.context.window.M2V_API_BASE='https://sandbox.example.test';
 s.values.set('m2v_api_base','https://lucazhou-suno2mv-api.hf.space');
 assert.equal(s.run('resolveApiBase()'),'https://sandbox.example.test');
});

test('import mode tabs and suno import are visible by default, debug controls dev url and links', () => {
  const normal = setup();
  normal.run('initUpload()');
  assert.equal(normal.element('#tab-suno').style.display, '');
  assert.equal(normal.element('#import-mode-tabs').style.display, '');
  assert.equal(normal.element('#wrap-local-suno-url').style.display, 'none');

  const taskHtml = normal.run('renderTask({id: "t1", status: "completed", suno_url: "https://suno.com/song/123", created_at: "2026-01-01T00:00:00Z"})');
  assert.ok(!taskHtml.includes('Original song link'), 'normal user should not see original song link');

  // Toggle debug mode dynamically via toggleDebugMode()
  normal.run('window.toggleDebugMode()');
  assert.equal(normal.element('#tab-suno').style.display, '');
  assert.equal(normal.element('#import-mode-tabs').style.display, '');
  assert.equal(normal.element('#wrap-local-suno-url').style.display, '');

  // Toggle off again
  normal.run('window.toggleDebugMode()');
  assert.equal(normal.element('#tab-suno').style.display, '');
  assert.equal(normal.element('#import-mode-tabs').style.display, '');
  assert.equal(normal.element('#wrap-local-suno-url').style.display, 'none');

  for (const query of ['?dev=1', '?debug=1', '?debug', '?mode=dev']) {
    const dev = setup();
    dev.context.location.search = query;
    dev.run('initUpload()');
    assert.equal(dev.element('#tab-suno').style.display, '');
    assert.equal(dev.element('#import-mode-tabs').style.display, '');
    assert.equal(dev.element('#wrap-local-suno-url').style.display, '');

    const devTaskHtml = dev.run('renderTask({id: "t1", status: "completed", suno_url: "https://suno.com/song/123", created_at: "2026-01-01T00:00:00Z"})');
    assert.ok(devTaskHtml.includes('Original song link'), 'dev mode should see original song link');
  }

  const devLocal = setup();
  devLocal.values.set('suno2mv_dev_mode', 'true');
  devLocal.run('initUpload()');
  assert.equal(devLocal.element('#tab-suno').style.display, '');
  assert.equal(devLocal.element('#import-mode-tabs').style.display, '');
  assert.equal(devLocal.element('#wrap-local-suno-url').style.display, '');

  const disabled = setup();
  disabled.context.location.search = '?debug=0';
  disabled.values.set('suno2mv_dev_mode', 'true');
  disabled.run('initUpload()');
  assert.equal(disabled.element('#tab-suno').style.display, '');
  assert.equal(disabled.element('#import-mode-tabs').style.display, '');
  assert.equal(disabled.element('#wrap-local-suno-url').style.display, 'none');
});

test('upload form supports dual-mode lyrics and dropzone toggles', () => {
  const s = setup();
  s.run('initUpload()');

  const pillPaste = s.element('#pill-lyrics-paste');
  const pillUpload = s.element('#pill-lyrics-upload');
  const wrapPaste = s.element('#wrap-lyrics-paste');
  const wrapUpload = s.element('#wrap-lyrics-upload');

  // Switch to upload file mode
  pillUpload.handlers.click();
  assert.equal(wrapUpload.style.display, '');
  assert.equal(wrapPaste.style.display, 'none');
  assert.equal(pillUpload.classList.contains('active'), true);
  assert.equal(pillPaste.classList.contains('active'), false);

  // Switch back to paste mode
  pillPaste.handlers.click();
  assert.equal(wrapPaste.style.display, '');
  assert.equal(wrapUpload.style.display, 'none');
  assert.equal(pillPaste.classList.contains('active'), true);
  assert.equal(pillUpload.classList.contains('active'), false);
});


test('brand triple click toggles debug without navigating, single click still navigates', () => {
  const s = setup(), timers = new Map(), navigations = [];
  let timerId = 0, prevented = 0;
  s.context.setTimeout = fn => { timers.set(++timerId, fn); return timerId; };
  s.context.clearTimeout = id => timers.delete(id);
  s.context.window.location.assign = url => navigations.push(url);
  const brand = s.element('.workspace-brand');
  brand.href = 'https://mv.fovea.si/';
  brand.closest = () => brand;
  s.run("setupTripleClickDebug(document.querySelector('.workspace-brand'))");
  const click = () => brand.handlers.click({button: 0, preventDefault() { prevented++; }});
  click(); click(); click();
  assert.equal(prevented, 3);
  for (const fn of [...timers.values()]) fn();
  timers.clear();
  assert.equal(s.values.get('suno2mv_debug_mode'), 'true');
  assert.deepEqual(navigations, []);
  click();
  for (const fn of [...timers.values()]) fn();
  assert.deepEqual(navigations, [brand.href]);
  brand.handlers.click({button: 0, metaKey: true, preventDefault() { throw Error('Modified click was intercepted'); }});
});
