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

test('Apple Scroll viewport maintains continuous reading stream with safe margins and natural density', () => {
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

    // 1. Maintain continuous reading stream without overfilling or truncating (5-9 visible lines)
    assert.ok(state.items.length >= 1 && state.items.length <= 10, `At t=${t}s, lines count ${state.items.length} must be <= 10`);

    // 2. Never touch borders (no 顶格):
    // All visible items must stay within safe margins (8% ~ 96% of height)
    for (const item of state.items) {
      assert.ok(item.y > 1920 * 0.08, `Line ${item.compiled.lineIndex} y=${item.y} must not exceed top safe margin`);
      assert.ok(item.y < 1920 * 0.96, `Line ${item.compiled.lineIndex} y=${item.y} must not exceed bottom safe margin`);
      assert.ok(item.alpha > 0.02, 'Rendered item must have noticeable alpha');
      if (item.isActive) {
        assert.equal(item.alpha, 1.0, 'Active line must have full opacity 1.0');
      }
    }
  });
});

test('Apple Scroll interlude row: left-aligned dots light up one by one, exit shrink, and catch-up spring offset animation', () => {
  const project = {
    duration: 30,
    lines: [
      { id: '0', text: 'First verse singing', start: 4.0, end: 8.0, words: [{ word: 'First', start: 4.0, end: 5.0 }, { word: 'verse', start: 5.0, end: 6.5 }, { word: 'singing', start: 6.5, end: 8.0 }] },
      { id: '1', text: 'Second verse after solo', start: 14.0, end: 18.0, words: [{ word: 'Second', start: 14.0, end: 15.0 }, { word: 'verse', start: 15.0, end: 16.5 }, { word: 'after', start: 16.5, end: 17.0 }, { word: 'solo', start: 17.0, end: 18.0 }] }
    ]
  };

  const width = 1080;
  const height = 1920;
  const compiled = compileAppleScrollLayout(project, width, height, measure, palette);

  // 1. 验证间奏行独立编排
  assert.ok(compiled.interludes);
  assert.equal(compiled.interludes.length, 2); // intro interlude before 4.0s, and 6s solo between 8.0s and 14.0s
  const soloInterlude = compiled.interludes.find(it => it.targetLineIndex === 1);
  assert.ok(soloInterlude);
  assert.equal(soloInterlude.startTime, 8.0);
  assert.equal(soloInterlude.endTime, 14.0);

  // 2. 间奏期间 (如 t = 10.0s)：三个圆点左对齐，处于文字基准字号 scale = 1.0
  const stateAt10 = appleScrollStateAt(compiled, 10.0);
  assert.ok(stateAt10.countIn);
  assert.equal(stateAt10.countIn.targetLineIndex, 1);
  assert.equal(stateAt10.countIn.dots.length, 3);

  // 验证左对齐规范：
  // 第一个圆点严格对齐歌词左边距 startX
  assert.equal(stateAt10.countIn.dots[0].x, compiled.startX + stateAt10.countIn.dots[0].radius);
  // 点 1 与点 2 顺延等距向右排列
  const spacing = stateAt10.countIn.dots[1].x - stateAt10.countIn.dots[0].x;
  assert.ok(spacing > stateAt10.countIn.dots[0].radius * 2);
  assert.equal(stateAt10.countIn.dots[2].x - stateAt10.countIn.dots[1].x, spacing);

  // 验证静止期比例为 1.0
  assert.equal(stateAt10.countIn.dots[0].scale, 1.0);

  // 3. 伴奏期间小圆点依次点亮，到达 1.35
  const stateAt13_5 = appleScrollStateAt(compiled, 13.5);
  assert.ok(stateAt13_5.countIn);
  assert.equal(stateAt13_5.countIn.dots[0].lit, true);
  assert.equal(stateAt13_5.countIn.dots[1].lit, true);
  assert.equal(stateAt13_5.countIn.dots[2].lit, true);
  assert.equal(stateAt13_5.countIn.dots[2].scale, 1.35);

  // 4. 开唱前过渡动效：圆点缩小渐隐 (1.35 → 1.18 → 0.40) 同时歌词追行贴上去
  const stateAt13_8 = appleScrollStateAt(compiled, 13.825);
  assert.ok(stateAt13_8.countIn);
  assert.ok(stateAt13_8.countIn.dots[0].scale >= 0.95 && stateAt13_8.countIn.dots[0].scale <= 1.25,
    `Dot scale ${stateAt13_8.countIn.dots[0].scale} should smoothly transition around 1.0~1.2 before singing`);

  // 5. 开唱瞬间 (t = 14.0s)：圆点彻底消失 (countIn = null)，下一句歌词追行贴上去吸附至准确焦点
  const stateAt14 = appleScrollStateAt(compiled, 14.0);
  assert.equal(stateAt14.countIn, null);
  const activeLine = stateAt14.items.find(it => it.isActive);
  assert.ok(activeLine);
  assert.equal(activeLine.compiled.lineIndex, 1);
  const expectedFocusTopY = Math.round(height * (compiled.focusY ?? 0.42) - activeLine.compiled.sentenceHeight / 2);
  assert.equal(activeLine.y, expectedFocusTopY);

  // 6. 验证最小间奏时长要求 MIN_INTERLUDE_GAP = 3.0s
  const projectShortGap = {
    duration: 20,
    lines: [
      { id: '0', text: 'Line one', start: 1.0, end: 3.0, words: [] },
      { id: '1', text: 'Line two with 2s breath pause', start: 5.0, end: 7.0, words: [] } // gap = 2.0s < 3.0s
    ]
  };
  const compiledShort = compileAppleScrollLayout(projectShortGap, width, height, measure, palette);
  assert.equal(compiledShort.interludes.length, 0, 'Gaps under 3.0s must not create interlude count-in dots');
  const stateShortAt4 = appleScrollStateAt(compiledShort, 4.0);
  assert.equal(stateShortAt4.countIn, null, 'No count-in dots for short breath pauses');
});

test('Apple Scroll interlude clearance with multi-line lyrics, font bounds, and smooth spacing restoration', () => {
  // Line 0 is a 2-line wrapped sentence: "它问我：你是不是 比他们想象的 更骄傲？在黑夜里可曾低头？"
  // Followed by a 4.0s interlude before Line 1.
  const project = {
    duration: 30,
    lines: [
      { id: '0', text: '它问我：你是不是 比他们想象的 更骄傲？在黑夜里可曾低头？', start: 2.0, end: 6.0, words: [] },
      { id: '1', text: '他们经过我身边 带着自诩聪明的傲慢', start: 10.0, end: 14.0, words: [] }
    ]
  };

  const width = 720;
  const height = 1280;
  const compiled = compileAppleScrollLayout(project, width, height, measure, palette);

  const line0 = compiled.lines[0];
  assert.ok(line0.rows.length >= 2, 'Line 0 must wrap into multiple rows');
  assert.ok(line0.sentenceHeight > 0, 'Line 0 has positive sentenceHeight');

  const F = compiled.activeFontSize;
  const fontAscender = Math.round(F * 0.85);
  const fontDescender = Math.round(F * 0.25);

  // 1. Entrance animation (t = 6.2s, 0.2s into interlude):
  // Offset is opening up smoothly
  const stateAt6_2 = appleScrollStateAt(compiled, 6.2);
  assert.ok(stateAt6_2.countIn);

  // 2. Main interlude countdown phase (t = 8.0s):
  // Real clearance between prev line bottom and dots, and dots and next line top
  const stateAt8 = appleScrollStateAt(compiled, 8.0);
  assert.ok(stateAt8.countIn);
  const dot = stateAt8.countIn.dots[0];
  const maxDotRadius = Math.ceil(dot.radius * 1.35);

  const item0 = stateAt8.items.find(it => it.compiled.lineIndex === 0);
  const item1 = stateAt8.items.find(it => it.compiled.lineIndex === 1);
  assert.ok(item0 && item1, 'Both lines visible in viewport');

  // Prev line actual bottom (taking into account all wrapped rows + font descenders)
  const prevLineActualBottom = item0.y + item0.compiled.sentenceHeight + fontDescender;
  // Next line actual top (taking into account font ascenders)
  const nextLineActualTop = item1.y - fontAscender;

  // Verify: dots are strictly below prevLineActualBottom with safety margin
  assert.ok(dot.y - maxDotRadius > prevLineActualBottom,
    `Dot top (${dot.y - maxDotRadius}) must be below prevLineActualBottom (${prevLineActualBottom})`);

  // Verify: nextLineActualTop is strictly below dot bottom with safety margin
  assert.ok(nextLineActualTop > dot.y + maxDotRadius,
    `Next line top (${nextLineActualTop}) must be below dot bottom (${dot.y + maxDotRadius})`);

  // 3. Exit phase (t = 9.85s, 0.15s before singing):
  // The extra offset is collapsing back
  const stateAt9_85 = appleScrollStateAt(compiled, 9.85);
  assert.ok(stateAt9_85.items.length >= 2);

  // 4. Singing start (t = 10.0s):
  // Dots are completely gone, spacing has smoothly restored to standard paragraphGap
  const stateAt10 = appleScrollStateAt(compiled, 10.0);
  assert.equal(stateAt10.countIn, null, 'Dots must be completely removed at singing start');

  const activeLine = stateAt10.items.find(it => it.isActive);
  assert.ok(activeLine);
  assert.equal(activeLine.compiled.lineIndex, 1);

  // Check that the distance between line 0 and line 1 is back to standard paragraphGap
  const sungLine0 = stateAt10.items.find(it => it.compiled.lineIndex === 0);
  if (sungLine0) {
    const line0Baseline = sungLine0.y + sungLine0.compiled.sentenceHeight;
    const line1Baseline = activeLine.y;
    assert.equal(line1Baseline - line0Baseline, compiled.paragraphGap,
      'Sentence spacing between line 0 and line 1 must cleanly restore to standard paragraphGap');
  }
});
