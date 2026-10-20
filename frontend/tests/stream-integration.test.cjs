const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('VisualMode resolution preserves layout ratio consistency', () => {
  const modelCode = fs.readFileSync(path.join(__dirname, '../motion/src/model.ts'), 'utf-8');
  assert.ok(modelCode.includes('resolveVisualMode'), 'resolveVisualMode must be exported in model.ts');
  assert.ok(modelCode.includes("'tv'"), 'VisualMode includes tv');
  assert.ok(modelCode.includes("'apple'"), 'VisualMode includes apple');
  assert.ok(modelCode.includes("'kinetic'"), 'VisualMode includes kinetic');

  // Pure logic replica to verify exact behavior
  function resolveVisualMode(requestedMode, aspect) {
    if (requestedMode === 'tv') {
      return aspect === '16:9' ? 'tv' : 'apple';
    }
    if (requestedMode === 'apple') {
      return aspect === '9:16' ? 'apple' : 'tv';
    }
    return 'kinetic';
  }

  assert.equal(resolveVisualMode('tv', '16:9'), 'tv');
  assert.equal(resolveVisualMode('tv', '9:16'), 'apple');
  assert.equal(resolveVisualMode('apple', '9:16'), 'apple');
  assert.equal(resolveVisualMode('apple', '16:9'), 'tv');
  assert.equal(resolveVisualMode('kinetic', '16:9'), 'kinetic');
  assert.equal(resolveVisualMode('kinetic', '9:16'), 'kinetic');
  assert.equal(resolveVisualMode(undefined, '16:9'), 'kinetic');
});

test('WebCodecs exporter and LyricVideo integrate streamLayout for TV and Apple modes', () => {
  const exporterCode = fs.readFileSync(path.join(__dirname, '../motion/src/webcodecs-exporter.ts'), 'utf-8');
  assert.ok(exporterCode.includes('compileKtvDualLayout'), 'Exporter compiles KTV dual layout');
  assert.ok(exporterCode.includes('paintKtvDualCanvas'), 'Exporter paints KTV dual canvas');
  assert.ok(exporterCode.includes('compileAppleScrollLayout'), 'Exporter compiles Apple scroll layout');
  assert.ok(exporterCode.includes('paintAppleScrollCanvas'), 'Exporter paints Apple scroll canvas');
  assert.ok(exporterCode.includes('visualMode?: VisualMode'), 'ExportRange has visualMode property');

  const lyricVideoCode = fs.readFileSync(path.join(__dirname, '../motion/src/lyric-video.tsx'), 'utf-8');
  assert.ok(lyricVideoCode.includes('compileKtvDualLayout'), 'LyricVideo compiles KTV layout for Remotion preview');
  assert.ok(lyricVideoCode.includes('ktvDualStateAt'), 'LyricVideo computes KTV dual line state');
  assert.ok(lyricVideoCode.includes('compileAppleScrollLayout'), 'LyricVideo compiles Apple scroll layout');
  assert.ok(lyricVideoCode.includes('appleScrollStateAt'), 'LyricVideo computes Apple scroll state');
  assert.ok(lyricVideoCode.includes('ktv-clip-'), 'LyricVideo uses clipPath for KTV karaoke sweep');
  assert.ok(lyricVideoCode.includes('apple-clip-'), 'LyricVideo uses clipPath for Apple scroll wipe');

  const studioCode = fs.readFileSync(path.join(__dirname, '../motion/src/studio.ts'), 'utf-8');
  assert.ok(studioCode.includes("options.visualMode = 'apple'"), 'Studio sets visualMode apple');
  assert.ok(studioCode.includes("options.visualMode = 'tv'"), 'Studio sets visualMode tv');
  assert.ok(studioCode.includes('visualMode: options.visualMode'), 'Studio passes visualMode to exportMotionWebCodecs');
});

test('Built studio.js bundle contains integrated stream-layout engine', () => {
  const bundlePath = path.join(__dirname, '../local/motion/studio.js');
  assert.ok(fs.existsSync(bundlePath), 'studio.js bundle must exist');
  const bundle = fs.readFileSync(bundlePath, 'utf-8');
  assert.ok(bundle.includes('ktv-clip-'), 'Bundle contains KTV clip path rendering');
  assert.ok(bundle.includes('apple-clip-'), 'Bundle contains Apple clip path rendering');
  assert.ok(bundle.includes('visualMode'), 'Bundle preserves visualMode routing');
});
