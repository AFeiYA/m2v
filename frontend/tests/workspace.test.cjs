const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../workspace.js'),'utf8');
function setup(hash='',mobile=false){
 const ids=['tasks-section','exports-section','upload-section','trash-section','credits-section'];
 const nodes=new Map(),events={},classes=new Set();let ready;
 const node=id=>{if(!nodes.has(id))nodes.set(id,{id,hidden:false,attrs:{},handlers:{},classList:{add:k=>classes.add(k),toggle(k){if(classes.has(k)){classes.delete(k);return false}classes.add(k);return true}},getAttribute(k){return this.attrs[k]},setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]},addEventListener(k,v){this.handlers[k]=v},focus(){this.focused=true},click(){this.clicked=true}});return nodes.get(id)};
 const links=ids.filter(id=>id!=='upload-section').map(id=>{const n=node('link-'+id);n.attrs.href='#'+id;return n});
 const context={URLSearchParams,location:{hash},document:{getElementById:node,addEventListener(k,v){ready=v},querySelectorAll:q=>q==='.workspace-page'?ids.map(node):links},window:{matchMedia:()=>({matches:mobile}),addEventListener(k,v){events[k]=v}}};
 vm.runInNewContext(source,context);ready();return {nodes,node,events,context,classes};
}
test('library is the default; deep links and back navigation show exactly one page',()=>{
 const s=setup();assert.equal(s.node('tasks-section').hidden,false);assert.equal(s.node('upload-section').hidden,true);
 s.context.location.hash='#exports-section';s.events.hashchange();
 assert.equal(s.node('exports-section').hidden,false);assert.equal(s.node('tasks-section').hidden,true);
 assert.equal(s.node('link-exports-section').attrs['aria-current'],'page');
 s.context.location.hash='#tasks-section';s.events.hashchange();
 assert.equal(s.node('btn-close-export-preview').clicked,true);
 assert.equal(s.node('link-exports-section').attrs['aria-current'],undefined);
});
test('retired version trash links fall back to the song library',()=>{
 const s=setup('#trash-section');
 assert.equal(s.node('tasks-section').hidden,false);
 s.node('song-search').handlers.input();assert.equal(s.context.location.hash,'tasks-section');
});
test('mobile navigation starts closed, can open, and closes after selecting a page',()=>{
 const s=setup('',true);assert.ok(s.classes.has('navigation-collapsed'));
 s.node('workspace-menu').handlers.click();assert.equal(s.node('workspace-menu').attrs['aria-expanded'],'true');
 s.context.location.hash='#upload-section';s.events.hashchange();
 assert.equal(s.node('upload-section').hidden,false);assert.ok(s.classes.has('navigation-collapsed'));
 assert.equal(s.node('workspace-menu').attrs['aria-expanded'],'false');
});

test('workspace delegates loading once and supports navigation while the hash is unchanged',()=>{
 const s=setup(),calls=[];
 s.context.window.m2vActiveSong={id:'song',title:'Song'};
 s.context.window.m2vStudios={motion:{activate:input=>calls.push(input),pause(){}},lyric:{pause(){}}};
 s.context.location.hash='#motion-studio-section';s.events.hashchange();
 assert.equal(calls.length,1);assert.equal(calls[0].songId,'song');
 assert.equal(s.node('iframe-motion-studio').src,undefined);
 s.context.window.m2vActiveSong={id:'other',title:'Other'};
 s.context.window.m2vNavigateWorkspace('motion-studio-section');
 assert.equal(calls.length,2);assert.equal(calls[1].songId,'other');
});

test('a blocked editor transition keeps the current view and song intact',()=>{
 const s=setup();s.context.window.m2vActiveSong={id:'song',title:'Song'};
 s.context.location.hash='#lyric-editor-section';s.events.hashchange();
 s.context.window.m2vCanOpenStudio=()=>false;
 s.context.location.hash='#motion-studio-section?song=other';s.events.hashchange();
 assert.equal(s.context.location.hash,'lyric-editor-section');
 assert.equal(s.context.window.m2vActiveSong.id,'song');
});
