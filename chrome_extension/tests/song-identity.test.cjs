const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

test('playing A then opening B submits B by ID, not A media session or stale Blob', async () => {
  const a = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
  const b = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
  let handler, report;
  const context = vm.createContext({ console, setTimeout,
    navigator: { mediaSession: { metadata: { title: 'Song A', artist: 'Artist A' } } },
    document: { title: 'Song B | Suno', addEventListener() {}, querySelector() { return null; },
      querySelectorAll(selector) { return selector === 'audio' ? [{ currentSrc: `https://cdn1.suno.ai/${a}.mp3`, paused: false, currentTime: 1 }] : []; } },
    window: { location: { pathname: `/song/${b}` }, __FOVEA_LAST_BLOB__: { stale: true },
      __FOVEA_CLIPS__: { [b]: { id: b, title: 'Song B', audio_url: `https://cdn1.suno.ai/${b}.mp3` } },
      fetch: async () => {}, addEventListener(_, fn) { handler = fn; }, postMessage(message) { report = message; } },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../inject.js'), 'utf8'), context);
  await handler({ source: context.window, data: { type: 'FOVEA_CAPTURE_REQUEST', section: 'chorus', duration: 30 } });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(report.type, 'FOVEA_CAPTURE_BY_SONG_ID');
  assert.equal(report.track.songId, b);
  assert.equal(report.track.title, 'Song B');
  assert.equal(report.dataUrl, undefined);
});
