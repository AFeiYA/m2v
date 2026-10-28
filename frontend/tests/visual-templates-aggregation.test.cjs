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
    const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
    assert.equal(ids.length,new Set(ids).size,`${filename} must not have duplicate control IDs`);
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

test('studio uses non-destructive mode selection', () => {
 const code=fs.readFileSync(path.join(__dirname,'../motion/src/studio.ts'),'utf8');
 const switcher=code.slice(code.indexOf('function applyVisualTemplate()'),code.indexOf("$('visual-template-select')?.addEventListener"));
 assert.ok(switcher.includes('selectMode'));
 assert.doesNotMatch(switcher,/localRulePlan|poster\.highlight|song_identity/);
});
