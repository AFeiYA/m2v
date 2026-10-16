const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../dashboard.js'),'utf8');
function setup(){
 const nodes=new Map(),calls=[];
 const element=id=>{if(!nodes.has(id))nodes.set(id,{value:'',style:{},handlers:{},querySelectorAll:()=>[],addEventListener(k,v){this.handlers[k]=v;}});return nodes.get(id);};
 const document={querySelector:element,querySelectorAll:()=>[],addEventListener(){},createElement:()=>({textContent:'',get innerHTML(){return this.textContent.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');}})};
 const row={id:'song-a',title:'<Rabbit hole>',current_task_id:'version-a',latest_task_id:'version-b',status:'failed',progress:0,version_count:2,export_count:3,starred:false,archived:false,updated_at:'2026-10-16T00:00:00Z',versions:[{id:'version-a',title:'Original',status:'completed',editable:true,export_count:3,updated_at:'2026-10-15T00:00:00Z'},{id:'version-b',title:'Changed',status:'failed',editable:false,error:'<error>',updated_at:'2026-10-16T00:00:00Z',export_count:0}]};
 const context={window:{},location:{hostname:'localhost',host:'localhost',origin:'http://localhost',search:''},document,URL,URLSearchParams,console,setTimeout,clearTimeout,clearInterval(){},localStorage:{getItem:()=>null},
  fetch:async(url,options={})=>{calls.push({url,options});return {ok:true,headers:{get:()=> 'application/json'},json:async()=>({songs:[row],total:25,total_songs:30,active_count:1})};}};
 context.window.location=context.location;
 vm.createContext(context);vm.runInContext(source,context);vm.runInContext('currentUser={id:"alice"}',context);
 return {nodes,calls,context,row,run:s=>vm.runInContext(s,context)};
}
test('song cards group versions, escape text and keep an editable version after failure',async()=>{
 const s=setup();await s.run('loadTasks()');
 assert.match(s.calls[0].url,/api\/songs\?/);assert.match(s.calls[0].url,/page_size=12/);
 const html=s.nodes.get('#tasks-list').innerHTML;
 assert.match(html,/&lt;Rabbit hole>/);assert.match(html,/Versions &amp; history \(2\)/);
 assert.match(html,/lyric-editor\/version-a/);assert.match(html,/Latest import failed/);assert.match(html,/&lt;error>/);
 assert.equal(s.nodes.get('#songs-next').disabled,false);
 assert.equal(s.calls.some(c=>c.url.includes('/align')||c.url.includes('/audio')),false);
});
test('search and paging operate on songs and preserve the chosen filters',async()=>{
 const s=setup();s.run('document.querySelector("#song-search").value="rabbit";document.querySelector("#song-view").value="archived";');
 await s.run('loadTasks(2)');
 assert.match(s.calls[0].url,/q=rabbit/);assert.match(s.calls[0].url,/view=archived/);assert.match(s.calls[0].url,/page=2/);
 assert.equal(s.nodes.get('#songs-prev').disabled,false);
});
test('favorite updates only library preferences without submitting another import',async()=>{
 const s=setup();await s.run('loadTasks()');s.calls.length=0;
 await s.run('handleSongAction({dataset:{song:"song-a",songAction:"star"}})');
 assert.match(s.calls[0].url,/\/api\/songs\/song-a$/);assert.equal(s.calls[0].options.method,'PATCH');
 assert.deepEqual(JSON.parse(s.calls[0].options.body),{starred:true});
 assert.equal(s.calls.some(c=>c.url.includes('from-suno')),false);
});
test('view videos filters by every version of the selected song',async()=>{
 const s=setup();await s.run('loadTasks()');s.calls.length=0;
 s.context.fetch=async(url)=>{s.calls.push({url});return {ok:true,headers:{get:()=> 'application/json'},json:async()=>({exports:[],total:0})};};
 await s.run('handleSongAction({dataset:{song:"song-a",songAction:"exports"}})');
 assert.match(s.calls[0].url,/task_ids=version-a%2Cversion-b/);
});
test('a delayed library response cannot repopulate another signed-in account',async()=>{
 const s=setup();let resolve;
 s.context.fetch=()=>new Promise(r=>resolve=r);
 const pending=s.run('loadTasks()');s.run('currentUser={id:"bob"}');
 resolve({ok:true,headers:{get:()=> 'application/json'},json:async()=>({songs:[s.row],total:1,total_songs:1})});await pending;
 assert.equal(s.nodes.has('#tasks-list'),false);
});
