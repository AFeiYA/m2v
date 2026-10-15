const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../local/i18n.js'), 'utf8');
function setup(saved, blocked = false) {
  const storage = new Map(saved ? [['m2v_locale', saved]] : []);
  const context = {
    window: {dispatchEvent() {}, location: {pathname: "/lyric-editor"}},
    navigator: {language: 'zh-CN'},
    document: {readyState: 'loading', addEventListener() {}, documentElement: {}, querySelectorAll: () => [], querySelector: () => null},
    CustomEvent: class {},
    localStorage: {getItem: k => {if(blocked) throw Error('denied'); return storage.get(k);}, setItem: (k,v) => storage.set(k,v)},
  };
  vm.createContext(context); vm.runInContext(source, context);
  return context;
}
test('first visit uses English even with a Chinese browser or unavailable storage', () => {
  for (const context of [setup(), setup('invalid'), setup(null, true)]) {
    assert.equal(context.window.currentLocale, 'en');
    context.window.applyTranslations();
    assert.equal(context.document.documentElement.lang, 'en');
    assert.equal(context.window.t('btn_save'), '💾 Save');
  }
});
test('explicit language preference survives, and switching still updates the page', () => {
  const context = setup('zh');
  assert.equal(context.window.currentLocale, 'zh');
  context.window.setLocale('en');
  assert.equal(context.document.documentElement.lang, 'en');
  context.window.toggleLocale();
  assert.equal(context.document.documentElement.lang, 'zh-CN');
  assert.equal(context.localStorage.getItem('m2v_locale'), 'zh');
});
