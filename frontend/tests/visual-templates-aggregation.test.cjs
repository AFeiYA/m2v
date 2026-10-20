const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

test('index.html toolbar contains primary CTA to open Motion Studio', () => {
  const html = fs.readFileSync(path.join(__dirname, '../local/index.html'), 'utf8');
  assert.ok(html.includes('id="btn-open-motion-studio"'), 'btn-open-motion-studio must exist in toolbar');
  assert.ok(html.includes('btn_open_motion_studio'), 'must have i18n attribute');
  assert.ok(html.includes('id="btn-modal-go-motion-studio"'), 'must have recommendation CTA in modal');
});

test('motion studio html files contain visual template selector with kinetic, apple, tv', () => {
  for (const filename of ['motion_studio.html', 'motion_studio_director.html']) {
    const html = fs.readFileSync(path.join(__dirname, '../local', filename), 'utf8');
    assert.ok(html.includes('id="visual-template-select"'), `${filename} must include #visual-template-select`);
    assert.ok(html.includes('value="kinetic"'), `${filename} must have kinetic option`);
    assert.ok(html.includes('value="apple"'), `${filename} must have apple option`);
    assert.ok(html.includes('value="tv"'), `${filename} must have tv option`);
  }
});

test('i18n contains translations for visual template selector and open motion studio', () => {
  const i18nSource = fs.readFileSync(path.join(__dirname, '../local/i18n.js'), 'utf8');
  assert.ok(i18nSource.includes('btn_open_motion_studio:'), 'Chinese btn_open_motion_studio exists');
  assert.ok(i18nSource.includes('ms_tpl_kinetic:'), 'Chinese ms_tpl_kinetic exists');
  assert.ok(i18nSource.includes('ms_tpl_apple:'), 'Chinese ms_tpl_apple exists');
  assert.ok(i18nSource.includes('ms_tpl_tv:'), 'Chinese ms_tpl_tv exists');
  assert.ok(i18nSource.includes('ms_lbl_visual_template:'), 'Chinese ms_lbl_visual_template exists');
});

test('studio.ts implements applyVisualTemplate with apple (9:16) and tv (16:9)', () => {
  const studioSource = fs.readFileSync(path.join(__dirname, '../motion/src/studio.ts'), 'utf8');
  assert.ok(studioSource.includes('applyVisualTemplate'), 'applyVisualTemplate function must be defined');
  assert.ok(studioSource.includes("visual-template-select"), 'visual-template-select must be wired');
  assert.ok(studioSource.includes("options.aspect = '9:16'"), 'apple must switch aspect to 9:16');
  assert.ok(studioSource.includes("options.aspect = '16:9'"), 'tv must switch aspect to 16:9');
  assert.ok(studioSource.includes("cue.poster.highlight = 'sweep'"), 'must apply karaoke sweep highlight');
});
