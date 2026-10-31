const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../dashboard.js'), 'utf8');
const context = {
  window: {}, location: { hostname: 'localhost', host: 'localhost', origin: 'http://localhost' },
  document: { addEventListener() {} }, localStorage: { getItem: () => null }, console,
};
vm.createContext(context);
vm.runInContext(source, context);

test('upload errors show safe server details and preserve HTTP status for non-JSON responses', async () => {
  assert.equal(await context.uploadResponseError({ status: 503, json: async () => ({ detail: 'File storage is unavailable.' }) }), 'File storage is unavailable.');
  assert.match(await context.uploadResponseError({ status: 502, json: async () => { throw new SyntaxError(); } }), /HTTP 502/);
  assert.match(await context.uploadResponseError({ status: 422, json: async () => ({ detail: [{ loc: ['body'] }] }) }), /HTTP 422/);
});

test('transport failure does not claim a specific server cause and warns about retrying', () => {
  assert.match(context.uploadRequestError(new TypeError('Failed to fetch')), /project list before retrying/);
  assert.match(context.uploadRequestError({ status: 503 }), /HTTP 503/);
});
