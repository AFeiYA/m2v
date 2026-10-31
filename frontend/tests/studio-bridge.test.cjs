const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../local/studio-bridge.js'),'utf8');
test('embedded editor inherits the explicit workspace backend and reports tagged readiness/save state',()=>{
 const messages=[],auth={},parent={m2vAuth:auth,m2vWorkspaceApi:()=> 'https://api.example',postMessage:(data,target)=>messages.push({data,target})};
 const window={parent};const context={window,document:{documentElement:{dataset:{studio:'lyric'}}},location:{origin:'https://app.example',search:'?_workspace=request-1'},URLSearchParams};
 vm.runInNewContext(source,context);
 assert.equal(window.M2V_API_BASE,'https://api.example');assert.equal(window.m2vAuth,auth);
 const bridge=window.m2vStudioBridge;
 bridge.loaded('song',false,'Title');bridge.state('song',true);bridge.state('song',true);bridge.saved('song',false,'v2');
 assert.deepEqual(messages.map(m=>m.data.type),['M2V_STUDIO_READY','M2V_STUDIO_LOADED','M2V_STUDIO_STATE','M2V_STUDIO_SAVED']);
 assert.ok(messages.every(m=>m.target==='https://app.example'&&m.data.requestId==='request-1'));
 assert.equal(messages.at(-1).data.version,'v2');
});
test('standalone editor does not send workspace events or change backend mode',()=>{
 const window={};window.parent=window;
 vm.runInNewContext(source,{window,document:{documentElement:{dataset:{studio:'motion'}}},location:{origin:'http://localhost',search:''},URLSearchParams});
 window.m2vStudioBridge.loaded('local');assert.equal(window.M2V_API_BASE,undefined);
});

const common=fs.readFileSync(path.join(__dirname,'../local/common.js'),'utf8');
const saveSource=common.slice(common.indexOf('async function saveAlignment()'),common.indexOf('// Undo / Redo & Dirty Flag',common.indexOf('async function saveAlignment()')));
function saveSetup(){
 let resolve;const response=new Promise(r=>resolve=r),writes=[],events=[],cache=[];
 const file={is_saas:true,task_id:'song',name:'Song'};
 const context={state:{currentFile:file,alignment:{lines:[{text:'Before'}]},dirty:true},lyricEditRevision:1,alignmentSaveInFlight:false,
  window:{m2vStudioBridge:{state:(...args)=>events.push(['state',...args]),saved:(...args)=>events.push(['saved',...args])},
   m2vCache:{getCurrentUid:()=> 'alice',saveProject:(...args)=>cache.push(args),clearDraft:()=>events.push(['clear'])}},
  apiFetch:async(url,options)=>{writes.push({url,options});return response;},status(){},document:{},console};
 vm.runInNewContext(saveSource,context);return {context,writes,events,cache,resolve,save:()=>vm.runInNewContext('saveAlignment()',context)};
}
test('lyric save uses a snapshot and never clears edits made while the request is pending',async()=>{
 const s=saveSetup();const saved=s.save();
 s.context.state.alignment.lines[0].text='After';s.context.lyricEditRevision++;
 s.resolve({ok:true,json:async()=>({version:'v2'})});await saved;
 assert.equal(JSON.parse(s.writes[0].options.body).lines[0].text,'Before');
 assert.equal(s.context.state.dirty,true);assert.equal(s.cache[0][3].lines[0].text,'Before');
 assert.ok(s.events.some(e=>e[0]==='saved'&&e[2]===true));assert.ok(!s.events.some(e=>e[0]==='clear'));
});
test('failed saves retain the draft and never tell Motion a new version was saved',async()=>{
 const s=saveSetup();const saved=s.save();s.resolve({ok:false,json:async()=>({detail:'Conflict'})});
 assert.equal(await saved,false);assert.equal(s.context.state.dirty,true);
 assert.ok(!s.events.some(e=>e[0]==='saved'));assert.equal(s.context.alignmentSaveInFlight,false);
});
test('export completion reports the account-scoped song through the current workspace channel',()=>{
 const messages=[],parent={postMessage:(data,target)=>messages.push({data,target})};
 const window={parent};vm.runInNewContext(source,{window,document:{documentElement:{dataset:{studio:'motion'}}},location:{origin:'https://app.example',search:'?_workspace=current'},URLSearchParams});
 window.m2vStudioBridge.loaded('song');window.m2vStudioBridge.exported('song');
 const {data,target}=messages.at(-1);assert.equal(data.type,'M2V_STUDIO_EXPORTED');assert.equal(data.songId,'song');assert.equal(data.requestId,'current');assert.equal(target,'https://app.example');
});
