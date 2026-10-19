const assert = require('node:assert/strict');
const { test } = require('node:test');
const { MediaArbiter } = require('../media-arbiter.js');

test('MediaArbiter enforces mutual exclusion between lyric and motion studios', () => {
  const arbiter = new MediaArbiter();
  let lyricPaused = false;
  let motionPaused = false;

  // Mock global window and m2vStudios
  global.window = {
    m2vStudios: {
      lyric: { pause: () => { lyricPaused = true; } },
      motion: { pause: () => { motionPaused = true; } },
    },
    location: { origin: 'http://localhost:8000' },
  };

  const events = [];
  arbiter.subscribe((ev, data) => events.push({ ev, data }));

  // Lyric plays
  arbiter.requestPlay('lyric');
  assert.equal(arbiter.activeSource, 'lyric');
  assert.equal(lyricPaused, false);
  assert.equal(motionPaused, false);

  // Motion requests play -> lyric must be paused!
  arbiter.requestPlay('motion');
  assert.equal(arbiter.activeSource, 'motion');
  assert.equal(lyricPaused, true);

  // Lyric requests play -> motion must be paused!
  arbiter.requestPlay('lyric');
  assert.equal(arbiter.activeSource, 'lyric');
  assert.equal(motionPaused, true);

  // pauseAll() resets activeSource and triggers pause for both
  lyricPaused = false;
  motionPaused = false;
  arbiter.pauseAll();
  assert.equal(arbiter.activeSource, null);
  assert.equal(lyricPaused, true);
  assert.equal(motionPaused, true);

  delete global.window;
});

test('MediaArbiter manages shared media cache and cleanup', () => {
  const arbiter = new MediaArbiter();
  let revokedUrls = [];
  global.URL = {
    revokeObjectURL: (url) => revokedUrls.push(url),
  };

  arbiter.cacheMedia('song-1', 'original', { url: 'blob:http://localhost/audio-1', blob: { size: 1024 } });
  arbiter.cacheMedia('song-1', 'vocals', { url: 'blob:http://localhost/vocals-1', blob: { size: 512 } });
  arbiter.cacheMedia('song-2', 'original', { url: 'blob:http://localhost/audio-2', blob: { size: 2048 } });

  const cached1 = arbiter.getCachedMedia('song-1', 'original');
  assert.ok(cached1);
  assert.equal(cached1.url, 'blob:http://localhost/audio-1');

  // Revoke only song-1
  arbiter.revokeMedia('song-1');
  assert.equal(arbiter.getCachedMedia('song-1', 'original'), null);
  assert.ok(arbiter.getCachedMedia('song-2', 'original'));
  assert.deepEqual(revokedUrls, ['blob:http://localhost/audio-1', 'blob:http://localhost/vocals-1']);

  // Clear all
  arbiter.clearAll();
  assert.equal(arbiter.getCachedMedia('song-2', 'original'), null);

  delete global.URL;
});
