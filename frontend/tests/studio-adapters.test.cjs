const assert = require('node:assert/strict');
const { test } = require('node:test');
const { LyricStudioAdapter, MotionStudioAdapter } = require('../studio-adapters.js');

test('LyricStudioAdapter manages mount, activate, pause, destroy lifecycles', async () => {
  const adapter = new LyricStudioAdapter();
  const sentMessages = [];
  const fakeFrame = {
    src: 'about:blank',
    dataset: {},
    contentWindow: {
      postMessage: (data) => sentMessages.push(data)
    }
  };
  const fakeContainer = {
    querySelector: sel => sel === '#iframe-lyric-editor' ? fakeFrame : null
  };

  // Mount
  await adapter.mount(fakeContainer, { songId: 'song-test' });
  assert.equal(fakeFrame.src, '/lyric-editor/song-test');
  assert.equal(fakeFrame.dataset.loadedSongId, 'song-test');

  // Activate with same song sends M2V_LOAD_SONG
  await adapter.activate({ songId: 'song-test' });
  assert.equal(sentMessages.length, 1);
  assert.equal(sentMessages[0].type, 'M2V_LOAD_SONG');

  // Pause sends M2V_STUDIO_PAUSE
  adapter.pause();
  assert.equal(sentMessages.length, 2);
  assert.equal(sentMessages[1].type, 'M2V_STUDIO_PAUSE');

  // Destroy sends M2V_STUDIO_DESTROY and clears src
  adapter.destroy();
  assert.equal(sentMessages.length, 3);
  assert.equal(sentMessages[2].type, 'M2V_STUDIO_DESTROY');
  assert.equal(fakeFrame.src, 'about:blank');
  assert.equal(fakeFrame.dataset.loadedSongId, undefined);
});

test('MotionStudioAdapter manages mount, activate, pause, destroy lifecycles', async () => {
  const adapter = new MotionStudioAdapter();
  const sentMessages = [];
  const fakeFrame = {
    src: 'about:blank',
    dataset: {},
    contentWindow: {
      postMessage: (data) => sentMessages.push(data)
    }
  };
  const fakeContainer = {
    querySelector: sel => sel === '#iframe-motion-studio' ? fakeFrame : null
  };

  await adapter.mount(fakeContainer, { songId: 'motion-test' });
  assert.equal(fakeFrame.src, '/motion-studio?project=motion-test');
  assert.equal(fakeFrame.dataset.loadedSongId, 'motion-test');

  adapter.pause();
  assert.equal(sentMessages.some(m => m.type === 'M2V_STUDIO_PAUSE'), true);

  adapter.destroy();
  assert.equal(sentMessages.some(m => m.type === 'M2V_STUDIO_DESTROY'), true);
  assert.equal(fakeFrame.src, 'about:blank');
});
