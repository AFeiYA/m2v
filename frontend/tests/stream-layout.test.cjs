const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const esbuild = require('../motion/node_modules/esbuild');

function load(file) {
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
}

const {
  compileKtvDualLayout,
  ktvDualStateAt,
  compileAppleScrollLayout,
  appleScrollStateAt,
} = load('stream-layout.ts');

const measure = (text, size) => ({
  width: text.length * size * 0.6,
  advance: text.length * size * 0.6,
  ascent: size * 0.8,
  descent: size * 0.2,
});

const palette = {
  accent: '#00f0ff',
  background: '#070e17',
  foreground: '#ffffff',
  muted: '#628299',
};

test('KTV dual layout enforces uniform font size across all lines regardless of length', () => {
  const project = {
    duration: 30,
    lines: [
      { id: '1', text: 'Short line', start: 1, end: 3, words: [{ word: 'Short', start: 1, end: 2 }, { word: 'line', start: 2, end: 3 }] },
      { id: '2', text: 'A significantly longer sentence that tests the uniform font size calculation', start: 3.5, end: 8, words: [] },
      { id: '3', text: 'Next third line', start: 8.5, end: 11, words: [] },
      { id: '4', text: 'Fourth line here', start: 11.5, end: 14, words: [] },
    ],
  };

  const compiled = compileKtvDualLayout(project, 1920, 1080, measure, palette);

  assert.equal(compiled.aspect, '16:9');
  assert.ok(compiled.uniformFontSize > 20 && compiled.uniformFontSize <= 72);

  // 所有行字号严格相等
  for (const line of compiled.lines) {
    assert.equal(line.fontSize, compiled.uniformFontSize);
  }

  // 偶数句在上行靠左，奇数句在下行靠右
  assert.equal(compiled.lines[0].isUpper, true);
  assert.equal(compiled.lines[0].align, 'left');
  assert.equal(compiled.lines[1].isUpper, false);
  assert.equal(compiled.lines[1].align, 'right');
  assert.equal(compiled.lines[2].isUpper, true);
  assert.equal(compiled.lines[2].align, 'left');
  assert.equal(compiled.lines[3].isUpper, false);
  assert.equal(compiled.lines[3].align, 'right');
});

test('KTV state machine: preview, active sweep, and continuous stay sung', () => {
  const project = {
    duration: 20,
    lines: [
      { id: '0', text: 'First line', start: 2.0, end: 4.0, words: [{ word: 'First', start: 2.0, end: 3.0 }, { word: 'line', start: 3.0, end: 4.0 }] },
      { id: '1', text: 'Second line', start: 4.5, end: 7.0, words: [{ word: 'Second', start: 4.5, end: 5.5 }, { word: 'line', start: 5.5, end: 7.0 }] },
      { id: '2', text: 'Third line', start: 7.5, end: 10.0, words: [{ word: 'Third', start: 7.5, end: 8.5 }, { word: 'line', start: 8.5, end: 10.0 }] },
    ],
  };

  const compiled = compileKtvDualLayout(project, 1920, 1080, measure, palette);

  // t = 0.5s: 第 0 句处于 preview（开唱前预读），第 1 句未进场
  const s0 = ktvDualStateAt(compiled, 0.5);
  assert.equal(s0.upper?.phase, 'preview');
  assert.equal(s0.lower, null);

  // t = 2.5s: 第 0 句正在演唱（active），同时第 1 句已在下行处于 preview 预读
  const s1 = ktvDualStateAt(compiled, 2.5);
  assert.equal(s1.upper?.phase, 'active');
  assert.equal(s1.lower?.phase, 'preview');

  // t = 4.6s: 第 0 句已唱完但常驻保持（stay），第 1 句正在演唱（active）
  const s2 = ktvDualStateAt(compiled, 4.6);
  assert.equal(s2.upper?.phase, 'stay');
  assert.equal(s2.lower?.phase, 'active');

  // t = 6.0s: 第 2 句开始在上行槽位预读（preview），第 1 句正在下行演唱（active）
  const s2b = ktvDualStateAt(compiled, 6.0);
  assert.equal(s2b.upper?.compiled.lineIndex, 2);
  assert.equal(s2b.upper?.phase, 'preview');
  assert.equal(s2b.lower?.phase, 'active');

  // t = 8.0s: 第 2 句已经开唱，替换了上行槽位（第 0 句退出，第 2 句 active），下行第 1 句 stay
  const s3 = ktvDualStateAt(compiled, 8.0);
  assert.equal(s3.upper?.compiled.lineIndex, 2);
  assert.equal(s3.upper?.phase, 'active');
  assert.equal(s3.lower?.compiled.lineIndex, 1);
  assert.equal(s3.lower?.phase, 'stay');
});

test('Apple Scroll layout focuses active sentence and smoothly scrolls focal Y', () => {
  const project = {
    duration: 30,
    lines: [
      { id: '0', text: 'Line zero', start: 0, end: 2.0, words: [] },
      { id: '1', text: 'Line one focus', start: 2.5, end: 5.0, words: [] },
      { id: '2', text: 'Line two next', start: 5.5, end: 8.0, words: [] },
      { id: '3', text: 'Line three tail', start: 8.5, end: 11.0, words: [] },
    ],
  };

  const compiled = compileAppleScrollLayout(project, 1080, 1920, measure, palette);
  assert.equal(compiled.aspect, '9:16');
  assert.equal(compiled.lines.length, 4);

  // t = 3.0s: 第 1 句为焦点行
  const stateAt3 = appleScrollStateAt(compiled, 3.0);
  const activeItem = stateAt3.items.find(it => it.isActive);
  assert.ok(activeItem);
  assert.equal(activeItem.compiled.lineIndex, 1);
  assert.equal(activeItem.alpha, 1.0);
  assert.equal(activeItem.scale, 1.0);

  // 非焦点行 alpha 降低
  const otherItems = stateAt3.items.filter(it => !it.isActive);
  for (const it of otherItems) {
    assert.ok(it.alpha < 1.0);
    assert.ok(it.scale <= 1.0);
  }

  // 随着时间向后推移，滚动 Y 轴向上移动（数值变小）
  const stateAt7 = appleScrollStateAt(compiled, 7.0);
  assert.ok(stateAt7.currentScrollY < stateAt3.currentScrollY);
});
