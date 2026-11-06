const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../local/lyric_editor.js'), 'utf8');

function setup(saveOk = true) {
  const elements = new Map(), calls = [], notices = [];
  let poll;
  function element(selector) {
    if (!elements.has(selector)) elements.set(selector, {
      style: {}, dataset: {}, handlers: {}, value: '',
      addEventListener(event, fn) {this.handlers[event] = fn;},
      pause() {}, load() {}, play: async () => {},
    });
    return elements.get(selector);
  }
  element('#export-start-time').value = '0:05';
  element('#export-end-time').value = '0:15';
  const context = {
    window: {addEventListener() {}}, document: {querySelector: () => null, addEventListener() {}},
    $: element, $$: () => [], state: {currentFile: {task_id: 'song', is_saas: true}, dirty: true},
    saveAlignment: async () => {calls.push({saved: true}); return saveOk;},
    status: m => notices.push(m), alert: m => notices.push(m),
    setInterval(fn) {poll = fn; return 1;}, clearInterval() {}, console,
    URL: {createObjectURL: () => 'blob:video', revokeObjectURL() {}},
  };
  context.window.apiFetch = async (url, options = {}) => {
    calls.push({url, body: options.body && JSON.parse(options.body)});
    if (url.startsWith('/api/credits')) return {ok:true,json:async()=>({available:5,pricing:{lyric_export:0}})};
    if (url.endsWith('/lyric-video')) return {ok: true, json: async () => ({task_id: 'job'})};
    if (url.includes('/access?')) return {ok: true, json: async () => ({url: 'https://files.invalid/video.mp4', filename:'lyric_video.mp4'})};
    return {ok: true, json: async () => ({status: 'completed', progress: 100, result: {video_url: '/api/editor/jobs/job/video'}})};
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  vm.runInContext('initLyricExportModal()', context);
  return {context, elements, calls, notices, start: () => element('#btn-start-lyric-export').handlers.click(), poll: () => poll()};
}

test('cloud modal shows completed export immediately and loads preview only on demand', async () => {
  const s = setup();
  await s.start();
  assert.equal(s.calls[0].saved, true);
  assert.equal(s.calls[1].url, '/api/credits?page_size=1');
  const render=s.calls.find(c=>c.url?.endsWith('/lyric-video'));
  assert.equal(render.body.start_time,5);assert.equal(render.body.end_time,15);
  assert.equal(render.body.accepted_cost,0);assert.match(render.body.request_id,/^[0-9a-f-]{36}$/);
  assert.equal('json_path' in render.body,false);
  await s.poll();
  assert.deepEqual(s.calls.slice(3).map(c => c.url), ['/api/editor/jobs/job']);
  assert.equal(s.elements.get('#lyric-modal-video').src, undefined);
  assert.equal(s.elements.get('#lyric-result-box').style.display, 'flex');
  await s.elements.get('#btn-preview-lyric-mp4').onclick();
  assert.equal(s.calls.at(-1).url, '/api/exports/job/access?preview=true');
  assert.equal(s.elements.get('#lyric-modal-video').src, 'https://files.invalid/video.mp4');
  assert.equal(s.elements.get('#btn-download-lyric-mp4').download, 'lyric_video.mp4');
});

test('failed alignment save prevents rendering stale lyrics', async () => {
  const s = setup(false);
  await s.start();
  assert.equal(s.calls.length, 1);
  assert.equal(s.elements.get('#btn-start-lyric-export').disabled, false);
  assert.ok(s.notices.some(m => m.includes('保存失败')));
});

test('ambiguous network failures reuse the same export request until source or options change', async () => {
  const s=setup(), original=s.context.window.apiFetch, bodies=[];
  s.context.window.apiFetch=async(url,options)=>{
    if(url.endsWith('/lyric-video')) {bodies.push(JSON.parse(options.body));throw Error('Network timeout after submission');}
    return original(url,options);
  };
  await s.start();await s.start();
  assert.equal(bodies[0].request_id,bodies[1].request_id);
  s.context.state.alignment={lines:[{text:'Changed lyrics',start:0,end:1}]};
  await s.start();assert.notEqual(bodies[1].request_id,bodies[2].request_id);
});

test('closing the export dialog during preview lookup keeps media stopped',async()=>{
 const s=setup();let resolve;
 const original=s.context.window.apiFetch;
 s.context.window.apiFetch=(url,options)=>url.includes('/access?')?new Promise(r=>resolve=r):original(url,options);
 await s.start();await s.poll();
 const pending=s.elements.get('#btn-preview-lyric-mp4').onclick();
 s.elements.get('#btn-close-lyric-modal').handlers.click();
 resolve({ok:true,json:async()=>({url:'https://files.invalid/late.mp4'})});
 await pending;
 assert.equal(s.elements.get('#lyric-modal-video').src,undefined);
 assert.equal(s.elements.get('#lyric-export-modal').style.display,'none');
});

test('formats select only Apple portrait and dual-line karaoke landscape', async()=>{
 const s=setup();
 s.context.document.querySelector=selector=>selector.includes('export-ratio')?{value:'16:9'}:null;
 await s.start();
 assert.equal(s.calls.find(c=>c.url?.endsWith('/lyric-video')).body.template,'tv');
});

test('clip matrix uses section boundaries and never treats pre-chorus as chorus',()=>{
 const s=setup();
 const clips=s.context.buildExportClips({duration:100,sections:[{name:'Pre-Chorus',start:0,end:10},{name:'Verse 1',start:10,end:20},{name:'Chorus',start:20,end:35}],lines:[{text:'pre',start:0,end:8},{text:'verse',start:11,end:19},{text:'chorus',start:21,end:34}]});
 assert.equal(clips.find(c=>c.id==='verse').start_time,11);
 assert.equal(clips.find(c=>c.id==='chorus').start_time,21);
 assert.equal(clips.find(c=>c.id==='chorus').end_time,34);
 assert.equal(s.context.buildExportClips({lines:[{text:'x',start:0,end:4}]}).find(c=>c.id==='verse').available,false);
});

test('multiple selected clips submit separate jobs with independent retry ids',async()=>{
 const s=setup();
 s.context.document.createElement=()=>({appendChild(){},textContent:''});
 s.elements.get('#lyric-batch-results').appendChild=()=>{};
 s.context.$$=selector=>selector==='.export-clip-check'?[{checked:true,dataset:{clipId:'full'}},{checked:true,dataset:{clipId:'chorus'}}]:[];
 s.context.state.alignment={sections:[{name:'Chorus',start:20,end:35}],lines:[{text:'hook',start:21,end:34}]};
 await s.start();
 let jobs=s.calls.filter(c=>c.url?.endsWith('/lyric-video'));
 assert.equal(jobs.length,2);assert.equal(jobs[0].body.start_time,0);assert.equal(jobs[0].body.end_time,null);
 assert.equal(jobs[1].body.start_time,21);assert.equal(jobs[1].body.end_time,34);
 assert.notEqual(jobs[0].body.request_id,jobs[1].body.request_id);
 await s.start();jobs=s.calls.filter(c=>c.url?.endsWith('/lyric-video'));
 assert.equal(jobs[0].body.request_id,jobs[2].body.request_id);
 assert.equal(jobs[1].body.request_id,jobs[3].body.request_id);
});

test('same clip in both formats becomes Apple portrait and Karaoke landscape',async()=>{
 const s=setup();
 // Batch progress rows use DOM elements in the browser.
 s.context.document.createElement=()=>({appendChild(){},textContent:''});
 s.elements.get('#lyric-batch-results').appendChild=()=>{};
 s.context.$$=selector=>selector==='.export-clip-check'?[{checked:true,dataset:{clipId:'full',ratio:'9:16'}},{checked:true,dataset:{clipId:'full',ratio:'16:9'}}]:[];
 await s.start();const jobs=s.calls.filter(c=>c.url?.endsWith('/lyric-video'));
 assert.equal(jobs.length,2);assert.equal(jobs[0].body.template,'apple');assert.equal(jobs[0].body.aspect_ratio,'9:16');
 assert.equal(jobs[1].body.template,'tv');assert.equal(jobs[1].body.aspect_ratio,'16:9');
});

test('matrix export works with a browser NodeList that lacks Array.prototype.filter',async()=>{
 const s=setup();
 s.context.document.createElement=()=>({appendChild(){},textContent:''});
 s.elements.get('#lyric-batch-results').appendChild=()=>{};
 const mockNodeList = (items) => ({
   length: items.length,
   forEach(fn) { items.forEach(fn); },
   [Symbol.iterator]() { return items[Symbol.iterator](); },
   item(i) { return items[i]; }
 });
 s.context.$$=selector=>selector==='.export-clip-check'?mockNodeList([{checked:true,dataset:{clipId:'full',ratio:'9:16'}}]):mockNodeList([]);
 await s.start();
 const jobs=s.calls.filter(c=>c.url?.endsWith('/lyric-video'));
 assert.equal(jobs.length,1);
 assert.equal(jobs[0].body.aspect_ratio,'9:16');
});

test('matrix export gracefully waits for render slots on HTTP 429 instead of crashing',async()=>{
 const s=setup();
 const rows=[];
 s.context.document.createElement=()=>({appendChild(){},set textContent(t){rows.push(t);},get textContent(){return rows.at(-1);}});
 s.elements.get('#lyric-batch-results').appendChild=()=>{};
 let callCount=0, original=s.context.window.apiFetch;
 s.context.window.apiFetch=async(url,options)=>{
   if(url.endsWith('/lyric-video')){
     callCount++;
     s.calls.push({url,body:options.body&&JSON.parse(options.body)});
     if(callCount>2){
       return {ok:false,status:429,json:async()=>({detail:'Your render slots are full. Wait for an existing video to finish.'})};
     }
     return {ok:true,status:200,json:async()=>({task_id:`job-${callCount}`})};
   }
   return original(url,options);
 };
 s.context.$$=selector=>selector==='.export-clip-check'?[
   {checked:true,dataset:{clipId:'full',ratio:'9:16'}},
   {checked:true,dataset:{clipId:'full',ratio:'16:9'}},
   {checked:true,dataset:{clipId:'chorus',ratio:'9:16'}}
 ]:[];
 s.context.state.alignment={sections:[{name:'Chorus',start:20,end:35}],lines:[{text:'hook',start:21,end:34}]};
 await s.start();
 const jobs=s.calls.filter(c=>c.url?.endsWith('/lyric-video'));
 assert.equal(jobs.length,3);
 assert.ok(rows.some(r=>r.includes('Waiting for available render slot')));
});

test('formatLrcTimestamp formats seconds as mm:ss.xx', () => {
  const { formatLrcTimestamp } = require('../local/lyric_editor.js');
  assert.equal(formatLrcTimestamp(0), '00:00.00');
  assert.equal(formatLrcTimestamp(5.42), '00:05.42');
  assert.equal(formatLrcTimestamp(65.12), '01:05.12');
  assert.equal(formatLrcTimestamp(125.05), '02:05.05');
});

test('formatTtmlTimestamp formats seconds as HH:MM:SS.mmm', () => {
  const { formatTtmlTimestamp } = require('../local/lyric_editor.js');
  assert.equal(formatTtmlTimestamp(0), '00:00:00.000');
  assert.equal(formatTtmlTimestamp(5.42), '00:00:05.420');
  assert.equal(formatTtmlTimestamp(65.125), '00:01:05.125');
  assert.equal(formatTtmlTimestamp(3665.05), '01:01:05.050');
});

test('exportCurrentLrc exports standard LRC format from state', () => {
  const s = setup();
  s.context.state.currentFile = { name: 'My Song' };
  s.context.state.alignment = {
    title: 'My Song',
    artist: 'Singer',
    lines: [
      { start: 2.5, end: 6.0, text: 'First line of lyrics' },
      { start: 7.25, end: 12.0, text: 'Second line of lyrics' },
    ],
  };

  const lrc = s.context.exportCurrentLrc();
  assert.match(lrc, /\[ti:My Song\]/);
  assert.match(lrc, /\[ar:Singer\]/);
  assert.match(lrc, /\[by:Fovea MV\]/);
  assert.match(lrc, /\[00:02.50\]First line of lyrics/);
  assert.match(lrc, /\[00:07.25\]Second line of lyrics/);
});

test('exportCurrentTtml exports Apple Music TTML format with word spans', () => {
  const s = setup();
  s.context.state.currentFile = { name: 'My Song' };
  s.context.state.alignment = {
    title: 'My Song',
    artist: 'Singer',
    lines: [
      {
        start: 2.5,
        end: 6.0,
        text: 'Hello world',
        words: [
          { word: 'Hello', start: 2.5, end: 3.5 },
          { word: 'world', start: 3.6, end: 6.0 },
        ],
      },
      { start: 7.25, end: 12.0, text: 'Second line' },
    ],
  };

  const ttml = s.context.exportCurrentTtml();
  assert.match(ttml, /<\?xml version="1.0" encoding="UTF-8"\?>/);
  assert.match(ttml, /<tt xmlns="http:\/\/www\.w3\.org\/ns\/ttml"/);
  assert.match(ttml, /xml:lang="en"/);
  assert.match(ttml, /<ttm:title>My Song<\/ttm:title>/);
  assert.match(ttml, /<ttm:agent type="person" xml:id="v1">Singer<\/ttm:agent>/);
  assert.match(ttml, /<p begin="00:00:02\.500" end="00:00:06\.000">/);
  assert.match(ttml, /<span begin="00:00:02\.500" end="00:00:03\.500">Hello<\/span>/);
  assert.match(ttml, /<span begin="00:00:03\.600" end="00:00:06\.000">world<\/span>/);
  assert.match(ttml, /<p begin="00:00:07\.250" end="00:00:12\.000">Second line<\/p>/);
});

test('detectLyricLanguage detects English, Simplified Chinese, and Traditional Chinese', () => {
  const { detectLyricLanguage } = require('../local/lyric_editor.js');
  assert.equal(detectLyricLanguage('Hello world, I love singing this song'), 'en');
  assert.equal(detectLyricLanguage('海风轻轻吹过海岸，夜色温柔'), 'zh-Hans');
  assert.equal(detectLyricLanguage('海風輕輕吹過海岸，夜色溫柔'), 'zh-Hant');
  assert.equal(detectLyricLanguage(''), 'zh-Hans');
  assert.equal(detectLyricLanguage('123 456 789'), 'zh-Hans');
});

test('exportCurrentTtml generates standard Apple Music xml:lang according to lyric language', () => {
  const s = setup();

  // Simplified Chinese lyrics -> zh-Hans
  s.context.state.alignment = {
    title: '简中歌曲',
    lines: [
      { start: 1.0, end: 4.0, text: '海风轻轻吹拂' },
      { start: 4.5, end: 8.0, text: '我们在沙滩漫步' },
    ],
  };
  const ttmlSimp = s.context.exportCurrentTtml();
  assert.match(ttmlSimp, /xml:lang="zh-Hans"/);
  assert.doesNotMatch(ttmlSimp, /xml:lang="zh-CN"/);

  // Traditional Chinese lyrics -> zh-Hant
  s.context.state.alignment = {
    title: '繁中歌曲',
    lines: [
      { start: 1.0, end: 4.0, text: '海風輕輕吹拂' },
      { start: 4.5, end: 8.0, text: '我們在沙灘漫步' },
    ],
  };
  const ttmlTrad = s.context.exportCurrentTtml();
  assert.match(ttmlTrad, /xml:lang="zh-Hant"/);
  assert.doesNotMatch(ttmlTrad, /xml:lang="zh-CN"/);

  // Explicit override normalization (zh-CN -> zh-Hans)
  s.context.state.alignment = {
    title: '覆盖测试',
    lang: 'zh-CN',
    lines: [{ start: 1.0, end: 3.0, text: 'Hello world' }],
  };
  const ttmlOverride = s.context.exportCurrentTtml();
  assert.match(ttmlOverride, /xml:lang="zh-Hans"/);
});

test('exportCurrentTtml supports zh-Hant conversion and pinyin ruby options', () => {
  const s = setup();
  s.context.state.alignment = {
    title: '海风轻轻',
    lines: [
      {
        start: 1.0,
        end: 4.0,
        text: '海风轻轻吹',
        words: [
          { word: '海', pinyin: 'hǎi', start: 1.0, end: 1.5 },
          { word: '风', pinyin: 'fēng', start: 1.5, end: 2.0 },
          { word: '轻', pinyin: 'qīng', start: 2.0, end: 2.5 },
          { word: '轻', pinyin: 'qīng', start: 2.5, end: 3.0 },
          { word: '吹', pinyin: 'chuī', start: 3.0, end: 3.5 },
        ],
      },
    ],
  };

  // Export Traditional Chinese
  const ttmlHant = s.context.exportCurrentTtml({ lang: 'zh-Hant' });
  assert.match(ttmlHant, /xml:lang="zh-Hant"/);
  assert.match(ttmlHant, /<ttm:title>海風輕輕<\/ttm:title>/);
  assert.match(ttmlHant, />海<\/span><span[^>]*>風<\/span><span[^>]*>輕<\/span><span[^>]*>輕<\/span><span[^>]*>吹<\/span>/);

  // Export Ruby Pinyin
  const ttmlRuby = s.context.exportCurrentTtml({ ruby: 'pinyin' });
  assert.match(ttmlRuby, /xmlns:tts="http:\/\/www\.w3\.org\/ns\/ttml#styling"/);
  assert.match(ttmlRuby, /tts:ruby="container"/);
  assert.match(ttmlRuby, /<span tts:ruby="base">海<\/span><span tts:ruby="textContainer"><span tts:ruby="text">hǎi<\/span><\/span>/);
  assert.match(ttmlRuby, /<span tts:ruby="base">风<\/span><span tts:ruby="textContainer"><span tts:ruby="text">fēng<\/span><\/span>/);
});

test('exportCurrentLrc supports zh-Hant and pinyin dual-line options', () => {
  const s = setup();
  s.context.state.alignment = {
    title: '海风轻轻',
    artist: '歌手',
    lines: [
      {
        start: 1.5,
        end: 4.0,
        text: '海风轻轻吹',
        words: [
          { word: '海', pinyin: 'hǎi' },
          { word: '风', pinyin: 'fēng' },
          { word: '轻', pinyin: 'qīng' },
          { word: '轻', pinyin: 'qīng' },
          { word: '吹', pinyin: 'chuī' },
        ],
      },
    ],
  };

  // Traditional LRC
  const lrcHant = s.context.exportCurrentLrc({ lang: 'zh-Hant' });
  assert.match(lrcHant, /\[00:01\.50\]海風輕輕吹/);

  // Pinyin Dual-Line LRC
  const lrcPinyin = s.context.exportCurrentLrc({ pinyin: true });
  assert.match(lrcPinyin, /\[00:01\.50\]hǎi fēng qīng qīng chuī\n\[00:01\.50\]海风轻轻吹/);
});

test('convertScript properly converts simplified to traditional Chinese and vice versa', () => {
  const { convertScript } = require('../local/lyric_editor.js');
  assert.equal(convertScript('海风轻轻吹拂，梦在远方', 'zh-Hant'), '海風輕輕吹拂，夢在遠方');
  assert.equal(convertScript('海風輕輕吹拂，夢在遠方', 'zh-Hans'), '海风轻轻吹拂，梦在远方');
  assert.equal(convertScript('Hello World', 'zh-Hant'), 'Hello World');
});



