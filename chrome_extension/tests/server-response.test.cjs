const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = vm.createContext({
  chrome: { runtime: { onMessage: { addListener() {} } } },
});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), context);
const read = context.readServerResponse;
test('HTML gateway error preserves status and does not read response twice', async () => {
  const response = new Response('<html><body>Gateway Timeout</body></html>', { status: 504 });
  await assert.rejects(read(response), /HTTP 504.*Gateway Timeout/);
  assert.equal(response.bodyUsed, true);
});
test('plain text and empty errors remain readable', async () => {
  await assert.rejects(read(new Response('upstream failed', { status: 502 })), /HTTP 502.*upstream failed/);
  await assert.rejects(read(new Response('', { status: 503 })), /HTTP 503/);
});
test('JSON error detail is retained', async () => {
  await assert.rejects(read(new Response(JSON.stringify({ detail: 'no audio' }), { status: 400 })), /HTTP 400.*no audio/);
});
test('successful response returns task ID', async () => {
  const result = await read(new Response(JSON.stringify({ task_id: 'lyric_123' })));
  assert.equal(result.task_id, 'lyric_123');
});
test('invalid successful response reports unexpected format', async () => {
  await assert.rejects(read(new Response('null')), /Unexpected server response/);
  await assert.rejects(read(new Response('<html>login</html>')), /HTTP 200.*login/);
});
