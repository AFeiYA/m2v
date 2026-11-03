const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

test('Cloudflare Pages middleware redirects marketing pages on www and mv to fovea.si', async () => {
  const middlewarePath = path.join(__dirname, '../functions/_middleware.js');
  const { onRequest } = await import('file://' + middlewarePath);

  // Test 1: www.fovea.si/pricing -> 301 to fovea.si/pricing
  let nextCalled = false;
  const res1 = await onRequest({
    request: { url: 'https://www.fovea.si/pricing' },
    next: async () => { nextCalled = true; return new Response('next'); }
  });
  assert.equal(res1.status, 301);
  assert.equal(res1.headers.get('location'), 'https://fovea.si/pricing');
  assert.equal(nextCalled, false);

  // Test 2: mv.fovea.si/ -> 301 to fovea.si/
  const res2 = await onRequest({
    request: { url: 'https://mv.fovea.si/' },
    next: async () => { nextCalled = true; return new Response('next'); }
  });
  assert.equal(res2.status, 301);
  assert.equal(res2.headers.get('location'), 'https://fovea.si/');

  // Test 3: mv.fovea.si/karaoke -> 301 to fovea.si/karaoke
  const res3 = await onRequest({
    request: { url: 'https://mv.fovea.si/karaoke' },
    next: async () => { nextCalled = true; return new Response('next'); }
  });
  assert.equal(res3.status, 301);
  assert.equal(res3.headers.get('location'), 'https://fovea.si/karaoke');

  // Test 4: mv.fovea.si/app -> stays on mv, calls next()
  nextCalled = false;
  const res4 = await onRequest({
    request: { url: 'https://mv.fovea.si/app' },
    next: async () => { nextCalled = true; return new Response('app-page'); }
  });
  assert.equal(nextCalled, true);
  assert.equal(await res4.text(), 'app-page');

  // Test 5: mv.fovea.si/lyric-editor -> stays on mv, calls next()
  nextCalled = false;
  const res5 = await onRequest({
    request: { url: 'https://mv.fovea.si/lyric-editor/123' },
    next: async () => { nextCalled = true; return new Response('editor'); }
  });
  assert.equal(nextCalled, true);
  assert.equal(await res5.text(), 'editor');

  // Test 6: fovea.si/pricing -> stays on fovea.si, calls next()
  nextCalled = false;
  const res6 = await onRequest({
    request: { url: 'https://fovea.si/pricing' },
    next: async () => { nextCalled = true; return new Response('pricing-page'); }
  });
  assert.equal(nextCalled, true);
  assert.equal(await res6.text(), 'pricing-page');
});
