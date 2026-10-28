const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('visual mode selection and layout compilation use the shared modules', () => {
 const code=fs.readFileSync(path.join(__dirname,'../motion/src/studio.ts'),'utf8');
 assert.ok(code.includes('selectMode(designSnapshot(),mode)'));
});

test('WebCodecs exporter and LyricVideo integrate streamLayout for TV and Apple modes', () => {
  const exporterCode = fs.readFileSync(path.join(__dirname, '../motion/src/webcodecs-exporter.ts'), 'utf-8');
  assert.ok(exporterCode.includes('compileRenderPlan'), 'Exporter uses shared render plan');
  assert.ok(exporterCode.includes('paintKtvDualCanvas'), 'Exporter paints KTV dual canvas');

  assert.ok(exporterCode.includes('paintAppleScrollCanvas'), 'Exporter paints Apple scroll canvas');
  assert.ok(exporterCode.includes('visualMode?: VisualMode'), 'ExportRange has visualMode property');

  const lyricVideoCode = fs.readFileSync(path.join(__dirname, '../motion/src/lyric-video.tsx'), 'utf-8');
  assert.ok(lyricVideoCode.includes('compileRenderPlan'), 'Preview uses shared render plan');
  assert.ok(lyricVideoCode.includes('ktvDualStateAt'), 'LyricVideo computes KTV dual line state');

  assert.ok(lyricVideoCode.includes('appleScrollStateAt'), 'LyricVideo computes Apple scroll state');
  assert.ok(lyricVideoCode.includes('ktv-clip-'), 'LyricVideo uses clipPath for KTV karaoke sweep');
  assert.ok(lyricVideoCode.includes('apple-clip-'), 'LyricVideo uses clipPath for Apple scroll wipe');

  const studioCode = fs.readFileSync(path.join(__dirname, '../motion/src/studio.ts'), 'utf-8');


  assert.ok(studioCode.includes('visualMode: task.visualMode') || studioCode.includes('visualMode: options.visualMode'), 'Studio passes visualMode to exportMotionWebCodecs');
});

test('Built studio.js bundle contains integrated stream-layout engine', () => {
  const bundlePath = path.join(__dirname, '../local/motion/studio.js');
  assert.ok(fs.existsSync(bundlePath), 'studio.js bundle must exist');
  const bundle = fs.readFileSync(bundlePath, 'utf-8');
  assert.ok(bundle.includes('ktv-clip-'), 'Bundle contains KTV clip path rendering');
  assert.ok(bundle.includes('apple-clip-'), 'Bundle contains Apple clip path rendering');
  assert.ok(bundle.includes('visualMode'), 'Bundle preserves visualMode routing');
});
