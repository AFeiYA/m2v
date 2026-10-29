const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const esbuild = require('../motion/node_modules/esbuild');

const code = esbuild.buildSync({
  stdin: {
    contents: "export * from './poster-layout'; export { normalizeProject } from './model';",
    resolveDir: path.join(__dirname, '../motion/src')
  },
  bundle: true,
  platform: 'node',
  format: 'cjs',
  write: false
}).outputFiles[0].text;

const entry = { exports: {} };
new Function('module', 'exports', code)(entry, entry.exports);
const { applyCustomGrouping, automaticPoster } = entry.exports;

test('custom phrasing splits Chinese line by slash into separate poster nodes', () => {
  const line = {
    id: 'l1',
    text: '听见你在路旁轻轻唱着歌',
    start: 1,
    end: 5,
    words: [
      { word: '听', start: 1.0, end: 1.3 },
      { word: '见', start: 1.3, end: 1.6 },
      { word: '你', start: 1.6, end: 1.9 },
      { word: '在', start: 2.0, end: 2.3 },
      { word: '路', start: 2.3, end: 2.6 },
      { word: '旁', start: 2.6, end: 2.9 },
      { word: '轻', start: 3.0, end: 3.4 },
      { word: '轻', start: 3.4, end: 3.8 },
      { word: '唱', start: 4.0, end: 4.4 },
      { word: '着', start: 4.4, end: 4.7 },
      { word: '歌', start: 4.7, end: 5.0 }
    ]
  };
  const cue = {
    line_id: 'l1',
    palette: 'impact',
    locked: false,
    template: 'phrase-rise',
    layout: 'center',
    intensity: 0.5,
    emphasis: '',
    poster: automaticPoster(line)
  };

  const result = applyCustomGrouping(line, cue, '听见你 / 在路旁 / 轻轻唱着歌');
  assert.equal(result.nodes.length, 3, 'Should produce 3 nodes');
  assert.equal(result.nodes[0].text, '听见你');
  assert.deepEqual(result.nodes[0].word_indices, [0, 1, 2]);
  assert.equal(result.nodes[0].role, 'secondary');

  assert.equal(result.nodes[1].text, '在路旁');
  assert.deepEqual(result.nodes[1].word_indices, [3, 4, 5]);
  assert.equal(result.nodes[1].role, 'support');

  assert.equal(result.nodes[2].text, '轻轻唱着歌');
  assert.deepEqual(result.nodes[2].word_indices, [6, 7, 8, 9, 10]);
  assert.equal(result.nodes[2].role, 'primary');
  assert.equal(result.nodes[2].color_role, 'accent');
});

test('custom phrasing merges segmented blocks back into a single node when slashes are removed', () => {
  const line = {
    id: 'l1',
    text: '听见你在路旁轻轻唱着歌',
    start: 1,
    end: 5,
    words: [
      { word: '听', start: 1.0, end: 1.3 },
      { word: '见', start: 1.3, end: 1.6 },
      { word: '你', start: 1.6, end: 1.9 },
      { word: '在', start: 2.0, end: 2.3 },
      { word: '路', start: 2.3, end: 2.6 },
      { word: '旁', start: 2.6, end: 2.9 },
      { word: '轻', start: 3.0, end: 3.4 },
      { word: '轻', start: 3.4, end: 3.8 },
      { word: '唱', start: 4.0, end: 4.4 },
      { word: '着', start: 4.4, end: 4.7 },
      { word: '歌', start: 4.7, end: 5.0 }
    ]
  };
  const cue = {
    line_id: 'l1',
    palette: 'neon',
    locked: false,
    template: 'phrase-rise',
    layout: 'center',
    intensity: 0.5,
    emphasis: '',
    poster: null
  };

  // First split
  applyCustomGrouping(line, cue, '听见你 / 在路旁 / 轻轻唱着歌');
  assert.equal(cue.poster.nodes.length, 3);

  // Then merge back into 1 block
  const merged = applyCustomGrouping(line, cue, '听见你在路旁轻轻唱着歌');
  assert.equal(merged.nodes.length, 1, 'Merged result must have exactly 1 node');
  assert.equal(merged.nodes[0].text, '听见你在路旁轻轻唱着歌');
  assert.deepEqual(merged.nodes[0].word_indices, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  assert.equal(merged.nodes[0].role, 'primary');
  assert.equal(merged.layout, 'center-stack');
});

test('custom primary index promotes chosen block as Hero keyword', () => {
  const line = {
    id: 'l1',
    text: '听见你在路旁轻轻唱着歌',
    start: 1,
    end: 5,
    words: [
      { word: '听', start: 1.0, end: 1.3 },
      { word: '见', start: 1.3, end: 1.6 },
      { word: '你', start: 1.6, end: 1.9 },
      { word: '在', start: 2.0, end: 2.3 },
      { word: '路', start: 2.3, end: 2.6 },
      { word: '旁', start: 2.6, end: 2.9 },
      { word: '轻', start: 3.0, end: 3.4 },
      { word: '轻', start: 3.4, end: 3.8 },
      { word: '唱', start: 4.0, end: 4.4 },
      { word: '着', start: 4.4, end: 4.7 },
      { word: '歌', start: 4.7, end: 5.0 }
    ]
  };
  const cue = {
    line_id: 'l1',
    palette: 'violet',
    locked: false,
    template: 'phrase-rise',
    layout: 'center',
    intensity: 0.5,
    emphasis: '',
    poster: null
  };

  // Set block 0 as primary
  const result = applyCustomGrouping(line, cue, '听见你 / 在路旁 / 轻轻唱着歌', 0);
  assert.equal(result.nodes[0].role, 'primary');
  assert.equal(result.nodes[0].color_role, 'accent');
  assert.equal(result.nodes[1].role, 'support');
  assert.equal(result.nodes[2].role, 'support');
});

test('handles fullwidth slashes, extra whitespace, and English lyrics cleanly', () => {
  const line = {
    id: 'l2',
    text: 'Never gonna give you up',
    start: 1,
    end: 4,
    words: [
      { word: 'Never', start: 1, end: 1.5 },
      { word: 'gonna', start: 1.5, end: 2 },
      { word: 'give', start: 2, end: 2.5 },
      { word: 'you', start: 2.5, end: 3 },
      { word: 'up', start: 3, end: 3.5 }
    ]
  };
  const cue = { line_id: 'l2', palette: 'impact', locked: false, template: 'phrase-rise', layout: 'center', intensity: 0.5, emphasis: '', poster: null };

  const result = applyCustomGrouping(line, cue, '  Never gonna  ／  give you up  ');
  assert.equal(result.nodes.length, 2);
  assert.equal(result.nodes[0].text, 'Never gonna');
  assert.deepEqual(result.nodes[0].word_indices, [0, 1]);
  assert.equal(result.nodes[1].text, 'give you up');
  assert.deepEqual(result.nodes[1].word_indices, [2, 3, 4]);
});

test('motion studio html and i18n include phrasing grouping controls and translations', () => {
  const html = fs.readFileSync(path.join(__dirname, '../local/motion_studio_director.html'), 'utf8');
  assert.ok(html.includes('id="cue-phrase-grouping"'), 'cue-phrase-grouping input must exist');
  assert.ok(html.includes('id="btn-reset-phrase-grouping"'), 'btn-reset-phrase-grouping must exist');
  assert.ok(html.includes('id="cue-phrase-chips"'), 'cue-phrase-chips container must exist');

  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]);
  assert.equal(ids.length, new Set(ids).size, 'No duplicate IDs in motion_studio_director.html');

  const i18n = fs.readFileSync(path.join(__dirname, '../local/i18n.js'), 'utf8');
  assert.ok(i18n.includes('ms_lbl_phrase_grouping:'), 'Chinese ms_lbl_phrase_grouping exists');
  assert.ok(i18n.includes('ms_ph_phrase_grouping:'), 'Chinese ms_ph_phrase_grouping exists');
  assert.ok(i18n.includes('ms_btn_reset_grouping:'), 'Chinese ms_btn_reset_grouping exists');
  assert.ok(i18n.includes('ms_help_phrase_grouping:'), 'Chinese ms_help_phrase_grouping exists');
});
