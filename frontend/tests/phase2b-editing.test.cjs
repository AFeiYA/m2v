const assert = require('node:assert/strict');
const { test } = require('node:test');
const {
  PORTRAIT_SAFE_AREA,
  CURATED_EXPORT_THEMES,
  countVocalUnits,
  inspectAlignmentTiming,
  snapExcerptToSentenceBounds,
  recommendExcerptCandidates,
} = require('../local/lyric_editor.js');

test('portrait safe area defines correct bounds and margins', () => {
  assert.equal(PORTRAIT_SAFE_AREA.aspect_ratio, '9:16');
  assert.equal(PORTRAIT_SAFE_AREA.top_pct, 0.14);
  assert.equal(PORTRAIT_SAFE_AREA.bottom_pct, 0.76);
  assert.equal(PORTRAIT_SAFE_AREA.left_pct, 0.08);
  assert.equal(PORTRAIT_SAFE_AREA.right_pct, 0.86);
  assert.ok(PORTRAIT_SAFE_AREA.unsafe_zones.top);
  assert.ok(PORTRAIT_SAFE_AREA.unsafe_zones.bottom);
  assert.ok(PORTRAIT_SAFE_AREA.unsafe_zones.right);
  assert.ok(PORTRAIT_SAFE_AREA.unsafe_zones.left);
});

test('curated themes contain all 5 distinct complete styles with colors and templates', () => {
  assert.equal(CURATED_EXPORT_THEMES.length, 5);
  const ids = CURATED_EXPORT_THEMES.map(t => t.id);
  assert.deepEqual(ids, [
    'apple_white_ambient',
    'cyber_neon_bounce',
    'amber_vinyl_classic',
    'midnight_ktv_duet',
    'emerald_minimal_black',
  ]);
  CURATED_EXPORT_THEMES.forEach(t => {
    assert.ok(t.template);
    assert.ok(t.theme);
    assert.ok(t.background_mode);
    assert.match(t.accent, /^#[0-9a-fA-F]{6}$/);
    assert.ok(t.bg_preview);
  });
});

test('countVocalUnits counts CJK characters and Latin vowel groups accurately', () => {
  assert.equal(countVocalUnits(''), 0);
  assert.equal(countVocalUnits('一二三四五'), 5);
  assert.equal(countVocalUnits('Hello World'), 3); // Hel-lo (2) + World (1) = 3
  assert.equal(countVocalUnits('Let it go 随它吧'), 6); // Let(1) it(1) go(1) + 随它吧(3) = 6
});

test('inspectAlignmentTiming flags line overlaps and compressed durations non-destructively', () => {
  const payload = {
    lines: [
      {
        start: 5.0,
        end: 8.5,
        text: '第一句歌词唱完',
        words: [
          { word: '第一句', start: 5.0, end: 6.2 },
          { word: '歌词', start: 6.2, end: 7.2 },
          { word: '唱完', start: 7.2, end: 8.5 },
        ],
      },
      {
        start: 8.2, // Overlaps with previous line (8.5 > 8.2)
        end: 8.23, // Compressed duration (30ms < 45ms)
        text: '紧接着快速进入下一句',
        words: [
          { word: '紧接着', start: 8.2, end: 8.21 },
          { word: '快速', start: 8.21, end: 8.22 },
          { word: '进入', start: 8.22, end: 8.23 },
        ],
      },
      {
        start: 10.0,
        end: 15.0,
        text: '尾字拉得很长很长',
        words: [
          { word: '尾字', start: 10.0, end: 10.5 },
          { word: '拉得很长', start: 10.5, end: 11.0 },
          { word: '很长', start: 11.0, end: 15.0 }, // Stretched tail word: 4s / 5s = 80% > 72%
        ],
      },
      {
        start: 16.0,
        end: 18.0,
        text: '带有复核标记的句子',
        needs_review: true,
        words: [
          { word: '带有', start: 16.0, end: 16.5 },
          { word: '复核', start: 16.5, end: 17.2, needs_review: true },
          { word: '标记', start: 17.2, end: 18.0, unresolved_compound: true },
        ],
      },
    ],
  };

  const originalJson = JSON.stringify(payload);
  const result = inspectAlignmentTiming(payload);

  // Non-destructive verification: original payload must remain identical
  assert.equal(JSON.stringify(payload), originalJson);

  assert.ok(result.total_warnings > 0);
  assert.ok(result.flagged_line_indices.includes(1));
  assert.ok(result.flagged_line_indices.includes(2));
  assert.ok(result.flagged_line_indices.includes(3));
  assert.ok(result.counts_by_kind.overlap > 0);
  assert.ok(result.counts_by_kind.compressed_duration > 0);
  assert.ok(result.counts_by_kind.excessive_gap > 0);
  assert.ok(result.counts_by_kind.low_confidence > 0);

  // Overlap evidence verification
  const overlapWarning = result.warnings.find(w => w.kind === 'overlap' && w.line_index === 1);
  assert.ok(overlapWarning);
  assert.equal(overlapWarning.evidence.overlap_ms, 300);
});

test('inspectAlignmentTiming returns 0 warnings for clean, healthy alignment', () => {
  const cleanPayload = {
    lines: [
      {
        start: 1.0,
        end: 4.0,
        text: '春风吹拂着山岗',
        words: [
          { word: '春风', start: 1.0, end: 2.0 },
          { word: '吹拂着', start: 2.0, end: 3.0 },
          { word: '山岗', start: 3.0, end: 4.0 },
        ],
      },
      {
        start: 4.5,
        end: 7.5,
        text: '阳光洒向了大地',
        words: [
          { word: '阳光', start: 4.5, end: 5.5 },
          { word: '洒向了', start: 5.5, end: 6.5 },
          { word: '大地', start: 6.5, end: 7.5 },
        ],
      },
    ],
  };

  const result = inspectAlignmentTiming(cleanPayload);
  assert.equal(result.total_warnings, 0);
  assert.deepEqual(result.flagged_line_indices, []);
  assert.equal(result.counts_by_kind.overlap, 0);
  assert.equal(result.counts_by_kind.compressed_duration, 0);
  assert.equal(result.counts_by_kind.excessive_gap, 0);
  assert.equal(result.counts_by_kind.low_confidence, 0);
});

test('snapExcerptToSentenceBounds snaps arbitrary time ranges to full sentence boundaries', () => {
  const payload = {
    lines: [
      { start: 10.0, end: 14.0, text: '第一句歌词开始' },
      { start: 14.5, end: 18.0, text: '第二句旋律扬起' },
      { start: 18.5, end: 23.0, text: '第三句副歌高潮到达' },
      { start: 23.5, end: 28.0, text: '第四句高音回荡悠长' },
      { start: 29.0, end: 34.0, text: '第五句尾声渐弱落幕' },
    ],
  };

  // User selects 12.0 to 25.0: line 0 starts at 10.0; line 2 ends at 23.0 (|23-25|=2 < |28-25|=3)
  const snapped1 = snapExcerptToSentenceBounds(payload, 12.0, 25.0);
  assert.equal(snapped1.start_time, 10.0);
  assert.equal(snapped1.end_time, 23.0);
  assert.equal(snapped1.start_line_index, 0);
  assert.equal(snapped1.end_line_index, 2);
  assert.equal(snapped1.line_count, 3);
  assert.ok(snapped1.preview_text.includes('第一句歌词开始'));

  // User selects 12.0 to 27.0: line 3 ends at 28.0 (|28-27|=1 < |23-27|=4)
  const snapped2 = snapExcerptToSentenceBounds(payload, 12.0, 27.0);
  assert.equal(snapped2.start_time, 10.0);
  assert.equal(snapped2.end_time, 28.0);
  assert.equal(snapped2.start_line_index, 0);
  assert.equal(snapped2.end_line_index, 3);
  assert.equal(snapped2.line_count, 4);
});

test('recommendExcerptCandidates generates scored promotional candidates aligned to sentences', () => {
  const payload = {
    sections: [
      { name: 'Intro', label: '前奏', start: 0.0, end: 12.0 },
      { name: 'Verse 1', label: '主歌 1', start: 12.0, end: 35.0 },
      { name: 'Chorus 1', label: '副歌 1 (高潮)', start: 35.0, end: 62.0 },
      { name: 'Verse 2', label: '主歌 2', start: 62.0, end: 85.0 },
      { name: 'Chorus 2', label: '副歌 2 (终极大高潮)', start: 85.0, end: 115.0 },
    ],
    lines: [
      { start: 12.0, end: 16.0, text: '安静的夜里' },
      { start: 16.5, end: 21.0, text: '微风轻轻吹' },
      { start: 22.0, end: 27.0, text: '思念随风远去' },
      { start: 28.0, end: 34.0, text: '回到最初的起点' },
      // Chorus lines:
      { start: 35.5, end: 40.0, text: '如果这就是爱' },
      { start: 40.5, end: 46.0, text: '请不要放开我的手' },
      { start: 46.5, end: 52.0, text: '在每一个漫长的黑夜里' },
      { start: 52.5, end: 60.0, text: '都有你温柔陪伴左右' },
      // Verse 2 lines:
      { start: 63.0, end: 68.0, text: '走过这片熟悉的街角' },
      { start: 68.5, end: 74.0, text: '回忆依然清晰如昨' },
      // Chorus 2 lines:
      { start: 85.5, end: 91.0, text: '如果这就是爱' },
      { start: 91.5, end: 97.0, text: '请用一生来守护' },
      { start: 97.5, end: 104.0, text: '直到世界尽头也无悔' },
      { start: 104.5, end: 112.0, text: '爱是最耀眼的光辉' },
    ],
  };

  const candidates = recommendExcerptCandidates(payload, { target_duration: 25.0, max_candidates: 4 });

  assert.ok(candidates.length >= 2);
  // Top candidates should be Chorus sections
  const chorusCand = candidates.find(c => c.kind === 'chorus');
  assert.ok(chorusCand);
  assert.ok(chorusCand.score > 80);
  assert.ok(chorusCand.preview_text.includes('如果这就是爱'));
  // Candidate start and end must match line boundaries exactly
  assert.equal(chorusCand.start_time, 35.5);
  assert.ok(chorusCand.duration >= 12.0 && chorusCand.duration <= 45.0);
});
