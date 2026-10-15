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

test('palette choices have English defaults and bilingual labels on both Studio pages', () => {
  for (const page of ['motion_studio.html','motion_studio_director.html']) {
    const html=fs.readFileSync(path.join(__dirname,'../local',page),'utf8');
    for (const id of ['preset','cue-palette']) {
      const select=html.match(new RegExp(`<select id="${id}"[^>]*>([\\s\\S]*?)</select>`))[1];
      const options=[...select.matchAll(/<option value="([^"]+)" data-i18n="([^"]+)">([^<]+)<\/option>/g)];
      assert.equal(options.length,8);
      for (const [,value,key,label] of options) {
        assert.ok(value);assert.equal(/[\u3400-\u9fff]/.test(label),false);
        assert.equal(setup('en').window.t(key),label);
        assert.match(setup('zh').window.t(key),/[\u3400-\u9fff]/);
      }
    }
  }
});

test('audio buffering, original track and failure badges follow the selected locale', () => {
  const context=setup();
  const nodes=new Map();
  function element(id) {
    if(!nodes.has(id)) nodes.set(id,{innerHTML:'',textContent:'',style:{},classList:{add(){},remove(){},contains(){return false;}}});
    return nodes.get(id);
  }
  context.document.getElementById=element;
  context.dom={};context.t=context.window.t;context.setTimeout=()=>{};
  const common=fs.readFileSync(path.join(__dirname,'../local/common.js'),'utf8');
  const render=common.slice(common.indexOf('const trackLoadingStates'),common.indexOf('\nfunction updateTimeDisplay'));
  vm.runInContext(render,context);
  vm.runInContext('setTrackLoadingState("vocals",true,"Original",null,"track_orig")',context);
  assert.match(element('btn-mute-vocals').innerHTML,/Original.*Buffering/);
  assert.equal(element('skeleton-text-vocals').textContent,'Loading 🎵 Original…');
  // Run the same refresh used by the languagechange listener.
  context.window.setLocale('zh');
  vm.runInContext('for (const [track,value] of trackLoadingStates) setTrackLoadingState(track,value.isLoading,value.trackName,value.errorMsg,value.titleKey)',context);
  assert.match(element('btn-mute-vocals').innerHTML,/原声.*缓冲中/);
  vm.runInContext('setTrackLoadingState("instrumental",false,"Instrumental",true)',context);
  assert.match(element('btn-mute-instrumental').innerHTML,/加载失败/);
  context.window.setLocale('en');
  vm.runInContext('for (const [track,value] of trackLoadingStates) setTrackLoadingState(track,value.isLoading,value.trackName,value.errorMsg,value.titleKey)',context);
  assert.match(element('btn-mute-instrumental').innerHTML,/Instrumental.*Load failed/);
});
