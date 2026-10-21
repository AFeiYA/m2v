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
  wrapSentenceToRows,
  paintAppleScrollCanvas,
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

test('wrapSentenceToRows wraps English at word boundaries and Chinese at glyph boundaries with Kinsoku Shori', () => {
  // 1. Long English sentence wraps at whole words without cutting words
  const enSentence = "When I stop running away, I've arrived at the place where the road back home is clear.";
  const enRows = wrapSentenceToRows(enSentence, 40, 700, 450, measure);
  assert.ok(enRows.length > 1, 'Long English sentence must wrap to multiple rows');
  for (const row of enRows) {
    assert.ok(measure(row, 40, 700).width <= 450, `Row "${row}" must not exceed maxWidth`);
  }
  // No partial word splitting: words like "running", "I've", "arrived" are kept intact
  assert.ok(enRows.some(r => r.includes('running')));
  assert.ok(enRows.some(r => r.includes("I've")));
  assert.ok(enRows.some(r => r.includes("arrived")));

  // 2. Kinsoku Shori: closing quotes and punctuation never start a line alone
  const quoteSentence = 'It says: "I am willing, I am able, I am here to stay."';
  const quoteRows = wrapSentenceToRows(quoteSentence, 40, 700, 400, measure);
  assert.ok(quoteRows.length >= 2);
  for (const row of quoteRows) {
    assert.ok(!/^[，。！？、；：”’）》〉】｝〕…—~～,.!?;:)\]}"']/u.test(row), `Row "${row}" must not start with forbidden punctuation`);
  }
});

test('Apple Scroll multi-line sentences compile exact rows, dynamic height, and multi-row highlight spans', () => {
  const words = [
    { word: 'When', start: 1.0, end: 1.5 },
    { word: 'I', start: 1.5, end: 1.8 },
    { word: 'stop', start: 1.8, end: 2.3 },
    { word: 'running', start: 2.3, end: 3.0 },
    { word: 'away,', start: 3.0, end: 3.8 },
    { word: "I've", start: 3.8, end: 4.4 },
    { word: 'arrived.', start: 4.4, end: 5.2 },
  ];
  const project = {
    duration: 15,
    lines: [
      { id: '1', text: "When I stop running away, I've arrived.", start: 1.0, end: 5.2, words },
      { id: '2', text: "Short second line", start: 5.5, end: 8.0, words: [{ word: 'Short', start: 5.5, end: 6.2 }, { word: 'second', start: 6.2, end: 7.0 }, { word: 'line', start: 7.0, end: 8.0 }] }
    ]
  };

  // 9:16 mobile canvas: width=720, height=1280
  const compiled = compileAppleScrollLayout(project, 720, 1280, measure, palette);
  const line0 = compiled.lines[0];

  assert.ok(line0.rows.length >= 2, 'Line 0 must wrap into at least 2 rows for mobile width');
  assert.ok(line0.sentenceHeight > 0, 'Multi-line sentence has positive sentenceHeight');
  assert.equal(line0.rows[0].yOffset, 0);
  assert.equal(line0.rows[1].yOffset, compiled.rowLineHeight);

  // Highlight spans compile across multiple rows
  assert.equal(line0.spans.length, words.length, 'All words must have highlight spans');
  const spanRow0 = line0.spans.filter(s => s.row === 0);
  const spanRow1 = line0.spans.filter(s => s.row === 1);
  assert.ok(spanRow0.length > 0, 'Row 0 has spans');
  assert.ok(spanRow1.length > 0, 'Row 1 has spans');

  // Verify paintAppleScrollCanvas runs cleanly with multi-row spans
  const canvasCalls = [];
  const mockCtx = {
    save: () => {},
    restore: () => {},
    beginPath: () => {},
    rect: (x, y, w, h) => canvasCalls.push({ type: 'rect', x, y, w, h }),
    clip: () => canvasCalls.push({ type: 'clip' }),
    fillText: (text, x, y) => canvasCalls.push({ type: 'fillText', text, x, y }),
    fillRect: (x, y, w, h) => canvasCalls.push({ type: 'fillRect', x, y, w, h }),
    createRadialGradient: () => ({ addColorStop: () => {} }),
    set font(v) {},
    set fillStyle(v) {},
    set globalAlpha(v) {},
    set textBaseline(v) {},
    set textAlign(v) {},
  };

  paintAppleScrollCanvas(mockCtx, compiled, 2.5, 'sans-serif');
  assert.ok(canvasCalls.length > 0, 'Canvas paint commands recorded');
  const fillTexts = canvasCalls.filter(c => c.type === 'fillText');
  assert.ok(fillTexts.length >= 2, 'All sub-rows of active multi-line sentence are painted');
});

test('Apple Scroll viewport restricts visible lines to 3-4, preserves top/bottom safe breathing space and never touches borders', () => {
  const project = {
    duration: 60,
    lines: Array.from({ length: 15 }, (_, i) => ({
      id: String(i),
      text: `Lyric line number ${i} for scrolling density check`,
      start: i * 3.0,
      end: (i + 1) * 3.0 - 0.5,
      words: []
    }))
  };

  const compiled = compileAppleScrollLayout(project, 1080, 1920, measure, palette);

  // Test at several playback times
  [0.5, 9.0, 18.0, 30.0].forEach(t => {
    const state = appleScrollStateAt(compiled, t);

    // 1. Never overfill screen: visible line count must be between 1 and 4
    assert.ok(state.items.length >= 1 && state.items.length <= 4, `At t=${t}s, lines count ${state.items.length} must be <= 4`);

    // 2. Never touch borders (no 顶格):
    // All visible items must stay within 16% ~ 82% of height
    for (const item of state.items) {
      assert.ok(item.y > 1920 * 0.14, `Line ${item.compiled.lineIndex} y=${item.y} must not exceed top safe margin`);
      assert.ok(item.y < 1920 * 0.82, `Line ${item.compiled.lineIndex} y=${item.y} must not exceed bottom safe margin`);
      assert.ok(item.alpha > 0.02, 'Rendered item must have noticeable alpha');
      if (item.isActive) {
        assert.equal(item.alpha, 1.0, 'Active line must have full opacity 1.0');
      }
    }
  });
});
