const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('motion studio html files include WebCodecs fast export checkbox', () => {
  const html1 = fs.readFileSync(path.join(__dirname, '../local/motion_studio.html'), 'utf8');
  const html2 = fs.readFileSync(path.join(__dirname, '../local/motion_studio_director.html'), 'utf8');

  assert.ok(html1.includes('id="export-fast-webcodecs"'));
  assert.ok(html1.includes('data-i18n="ms_fast_webcodecs"'));
  assert.ok(html2.includes('id="export-fast-webcodecs"'));
  assert.ok(html2.includes('data-i18n="ms_fast_webcodecs"'));
});

test('i18n contains translations for WebCodecs fast export', () => {
  const i18nContent = fs.readFileSync(path.join(__dirname, '../local/i18n.js'), 'utf8');
  assert.ok(i18nContent.includes('ms_fast_webcodecs'));
  assert.ok(i18nContent.includes('ms_help_export_webcodecs'));
});

test('webcodecs-exporter module exports isWebCodecsSupported and exportMotionWebCodecs', () => {
  const exporterContent = fs.readFileSync(path.join(__dirname, '../motion/src/webcodecs-exporter.ts'), 'utf8');
  assert.ok(exporterContent.includes('export function isWebCodecsSupported'));
  assert.ok(exporterContent.includes('export async function exportMotionWebCodecs'));
  assert.ok(exporterContent.includes('export function renderCanvasFrame'));
});

test('renderCanvasFrame in TV mode omits raw cover image, staggers cards, and animates active word zoom & icon', () => {
  const esbuild = require('../motion/node_modules/esbuild');
  const load = (file) => {
    const code = esbuild.buildSync({
      entryPoints: [path.join(__dirname, '../motion/src', file)],
      bundle: true,
      platform: 'node',
      format: 'cjs',
      write: false,
    }).outputFiles[0].text;
    const m = { exports: {} };
    new Function('module', 'exports', code)(m, m.exports);
    return m.exports;
  };

  const { renderCanvasFrame } = load('webcodecs-exporter.ts');
  const { compileRenderPlan } = load('render-plan.ts');

  const project = {
    title: 'Everglow',
    artist: 'Made with fovea.si',
    duration: 20,
    song_cover: { data_url: 'data:image/png;base64,AAA', width: 1000, height: 1000, source: 'custom' },
    analysis: { bpm: 147, beats: [], drum_hits: [] },
    lines: [
      {
        id: 'l1',
        text: 'And though you might',
        start: 1.0,
        end: 3.0,
        section: 'VERSE 1',
        words: [
          { word: 'And', start: 1.0, end: 1.5 },
          { word: 'though', start: 1.5, end: 2.0 },
          { word: 'you', start: 2.0, end: 2.5 },
          { word: 'might', start: 2.5, end: 3.0 },
        ],
      },
      {
        id: 'l2',
        text: 'Still I see you',
        start: 3.2,
        end: 5.0,
        section: 'VERSE 1',
        words: [
          { word: 'Still', start: 3.2, end: 3.6 },
          { word: 'I', start: 3.6, end: 4.0 },
          { word: 'see', start: 4.0, end: 4.5 },
          { word: 'you', start: 4.5, end: 5.0 },
        ],
      },
    ],
  };

  const measure = (text, size) => ({
    width: text.length * size * 0.55,
    advance: text.length * size * 0.55,
    ascent: size * 0.8,
    descent: size * 0.2,
  });

  const plan = compileRenderPlan(project, { visualMode: 'tv' }, 1920, 1080, measure);

  const calls = [];
  const fakeGrad = { addColorStop() {} };
  const fakeCtx = {
    save() { calls.push(['save']); },
    restore() { calls.push(['restore']); },
    clearRect() {},
    fillRect() {},
    fill() {},
    stroke() {},
    beginPath() {},
    rect() {},
    arc() {},
    clip() {},
    setLineDash() {},
    roundRect(...args) { calls.push(['roundRect', ...args]); },
    translate(...args) { calls.push(['translate', ...args]); },
    scale(...args) { calls.push(['scale', ...args]); },
    rotate(...args) { calls.push(['rotate', ...args]); },
    drawImage(...args) { calls.push(['drawImage', ...args]); },
    fillText(...args) { calls.push(['fillText', ...args]); },
    measureText(t) { return { width: t.length * 24 }; },
    createRadialGradient() { return fakeGrad; },
    createLinearGradient() { return fakeGrad; },
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 1,
    font: '',
    textAlign: 'left',
    textBaseline: 'alphabetic',
    shadowColor: '',
    shadowBlur: 0,
    shadowOffsetY: 0,
    globalAlpha: 1,
  };

  // Render at t = 1.75 (word "though" is actively singing in line 1, line 2 is upcoming)
  renderCanvasFrame(
    fakeCtx,
    project,
    plan.layouts,
    plan.songLayout,
    plan.intro,
    { width: 1000, height: 1000 }, // non-null coverImage
    1.75,
    1920,
    1080,
    { visualMode: 'tv', ktvLayout: plan.ktvLayout }
  );

  // 1. Raw coverImage must NEVER be drawn in TV mode
  assert.equal(calls.filter(c => c[0] === 'drawImage').length, 0, 'TV mode must not draw raw coverImage');

  // 2. Active word zoom (1.12x) must be applied
  assert.ok(
    calls.some(c => c[0] === 'scale' && Math.abs(c[1] - 1.12) < 0.001 && Math.abs(c[2] - 1.12) < 0.001),
    'Active word must zoom by 1.12x'
  );

  // 3. Oscillating mic icon rotation must be applied
  assert.ok(
    calls.some(c => c[0] === 'rotate' && Math.abs(c[1]) > 0.001),
    'Active singing icon must animate rotation'
  );

  // 4. Cards must be staggered (top card left-aligned at x=108, bottom card right-aligned at x > 900)
  const cardRects = calls.filter(c => c[0] === 'roundRect' && c[3] > 150 && c[4] > 60 && c[3] < 1700);
  assert.ok(cardRects.length >= 2, 'Both top and bottom cards must be drawn');
  assert.equal(cardRects[0][1], 108, 'Top card must be left-aligned at stagePadX + staggerPad = 108');
  assert.ok(cardRects[1][1] > cardRects[0][1] + 500, 'Bottom card must be right-aligned');
});
