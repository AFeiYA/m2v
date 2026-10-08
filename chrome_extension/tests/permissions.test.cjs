const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const manifest = require('../manifest.json');

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
