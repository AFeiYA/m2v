const assert = require('node:assert/strict');
const { test } = require('node:test');
const path = require('node:path');
const esbuild = require('../motion/node_modules/esbuild');

const code = esbuild.buildSync({
  stdin: {
    contents: `
      export * from './neon-layout';
      export * from './motion-design';
      export * from './render-plan';
      export { normalizeProject, resolveVisualMode } from './model';
    `,
    resolveDir: path.join(__dirname, '../motion/src'),
  },
  bundle: true,
  platform: 'node',
  format: 'cjs',
  write: false,
}).outputFiles[0].text;

const entry = { exports: {} };
const fn = new Function('module', 'exports', 'require', code);
fn(entry, entry.exports, require);

const {
  compileNeonLayout,
  computeNeonFlicker,
  neonStateAt,
  paintNeonCanvas,
  VISUAL_TEMPLATES,
  visualModes,
  compileRenderPlan,
  resolveVisualMode,
} = entry.exports;

const mockMeasure = (text, size, weight) => ({
  width: text.length * size * 0.55,
  ascent: size * 0.8,
  descent: size * 0.2,
});

const sampleProject = {
  title: 'Test Song',
  duration: 60,
  lines: [
    {
      id: 'l1',
      text: '偏离中线 我自成焦点',
      start: 1.0,
      end: 4.5,
      words: [
        { word: '偏离', start: 1.0, end: 1.8 },
        { word: '中线', start: 1.8, end: 2.6 },
        { word: '我自成', start: 2.6, end: 3.5 },
        { word: '焦点', start: 3.5, end: 4.5 },
      ],
    },
    {
      id: 'l2',
      text: '霓虹点亮 每一个长夜',
      start: 5.0,
      end: 8.5,
      words: [
        { word: '霓虹', start: 5.0, end: 6.0 },
        { word: '点亮', start: 6.0, end: 7.0 },
        { word: '每一个', start: 7.0, end: 7.8 },
        { word: '长夜', start: 7.8, end: 8.5 },
      ],
    },
  ],
  analysis: { bpm: 120, beats: [1.0, 2.0, 3.0, 4.0], drum_hits: [{ time: 1.0, type: 'kick' }], energy_curve: [] },
};

const palette = {
  background: '#07080b',
  foreground: '#f3f4f6',
  accent: '#00f0ff',
  dim: '#4b5563',
};

test('VISUAL_TEMPLATES and visualModes contain neon with 9:16 and 16:9 support', () => {
  assert.ok(VISUAL_TEMPLATES.neon, 'VISUAL_TEMPLATES must contain neon');
  assert.equal(VISUAL_TEMPLATES.neon.id, 'neon');
  assert.equal(VISUAL_TEMPLATES.neon.badge, 'Neon Glow');
  assert.equal(VISUAL_TEMPLATES.neon.defaultAspect, '9:16');
  assert.deepEqual(VISUAL_TEMPLATES.neon.supportedAspects, ['9:16', '16:9']);

  assert.ok(visualModes.neon, 'visualModes must contain neon');
  assert.equal(visualModes.neon.label, 'Cyber Neon');
  assert.equal(resolveVisualMode('neon', '9:16'), 'neon');
  assert.equal(resolveVisualMode('neon', '16:9'), 'neon');
});

test('compileNeonLayout compiles lines, centers coordinates, and measures spans', () => {
  const layout = compileNeonLayout(sampleProject, 1080, 1920, mockMeasure, palette);
  assert.equal(layout.width, 1080);
  assert.equal(layout.height, 1920);
  assert.equal(layout.aspect, '9:16');
  assert.equal(layout.lines.length, 2);

  const l1 = layout.lines[0];
  assert.equal(l1.text, '偏离中线 我自成焦点');
  assert.ok(l1.rows.length >= 1);
  assert.ok(l1.rows[0].x > 0, 'Line row should be centered (x > 0)');
  assert.equal(l1.spans.length, 4, 'Must have 4 highlight spans for 4 words');
});

test('computeNeonFlicker simulates gas tube ignition pulse in first 0.25s', () => {
  // Within ignition window
  const f1 = computeNeonFlicker(0.02, true);
  const f2 = computeNeonFlicker(0.06, true);
  assert.notEqual(f1, f2, 'Flicker intensity fluctuates during ignition');

  // After ignition window (steady light)
  assert.equal(computeNeonFlicker(0.35, true), 1.0, 'Steady light after 0.26s');
  // When disabled
  assert.equal(computeNeonFlicker(0.02, false), 1.0, 'Always 1.0 when flicker disabled');
});

test('neonStateAt tracks active line, progress sweep, and neighbor lines', () => {
  const layout = compileNeonLayout(sampleProject, 1080, 1920, mockMeasure, palette);
  
  // At t = 2.0s (midway through word '中线' in line 1)
  const state = neonStateAt(layout, 2.0, 0.5);
  assert.ok(state.current, 'Must have current line');
  assert.equal(state.current.compiled.line.id, 'l1');
  assert.ok(state.current.scale >= 1.0, 'Active line has pulse scale >= 1.0');
  assert.ok(state.next, 'Must have next upcoming line');
  assert.equal(state.next.compiled.line.id, 'l2');
  assert.equal(state.next.alpha, 0.28, 'Next line should have preview alpha');

  // Verify word progress
  const word1 = state.current.spansWithProgress[0];
  assert.equal(word1.progress, 1.0, 'Word 1 should be fully sung');
  const word2 = state.current.spansWithProgress[1];
  assert.ok(word2.progress > 0 && word2.progress < 1.0, 'Word 2 is currently active');
});

test('compileRenderPlan correctly builds neonLayout when visualMode is neon', () => {
  const plan = compileRenderPlan(sampleProject, { visualMode: 'neon' }, 1080, 1920, mockMeasure);
  assert.equal(plan.mode, 'neon');
  assert.ok(plan.neonLayout, 'neonLayout must be compiled');
  assert.equal(plan.neonLayout.lines.length, 2);
  assert.equal(plan.layouts, null);
  assert.equal(plan.appleLayout, null);
  assert.equal(plan.ktvLayout, null);
});

test('paintNeonCanvas executes without throwing on mock context', () => {
  const layout = compileNeonLayout(sampleProject, 1080, 1920, mockMeasure, palette);
  const calls = [];
  const mockCtx = {
    save: () => calls.push('save'),
    restore: () => calls.push('restore'),
    clearRect: () => calls.push('clearRect'),
    fillRect: () => calls.push('fillRect'),
    fillText: (...args) => calls.push(['fillText', ...args]),
    beginPath: () => calls.push('beginPath'),
    rect: () => calls.push('rect'),
    clip: () => calls.push('clip'),
    createRadialGradient: () => ({ addColorStop: () => {} }),
    set font(v) {},
    set fillStyle(v) {},
    set shadowColor(v) {},
    set shadowBlur(v) {},
    set globalAlpha(v) {},
    set textBaseline(v) {},
    set textAlign(v) {},
  };

  assert.doesNotThrow(() => {
    paintNeonCanvas(mockCtx, layout, 2.0, 'sans-serif', 0.4);
  });
  assert.ok(calls.some(c => Array.isArray(c) && c[0] === 'fillText'), 'Must render text');
});
