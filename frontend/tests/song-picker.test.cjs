const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../local/song-picker.js'),'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function setup(request,choose=async()=>true){
 class Element {
  constructor(tag){this.tag=tag;this.dataset={};this.children=[];this.textContent='';this.value='';this.handlers={};this.parts={};}
  get options(){return this.children;}
  append(...nodes){this.children.push(...nodes);if(this.tag==='select'&&!this.value)this.value=nodes[0]?.value;}
  replaceChildren(){this.children=[];}
  after(node){this.next=node;}
  querySelector(selector){return this.parts[selector] ||= new Element(selector);}
  setAttribute(){}
  addEventListener(event,fn){this.handlers[event]=fn;}
  showModal(){this.open=true;}
  close(){this.open=false;this.handlers.close?.();}
 }
 const document={body:new Element('body'),createElement:tag=>new Element(tag)};
 const values={m2v_user:JSON.stringify({id:'alice'})};
 const window={addEventListener(){}};
 const context={window,document,localStorage:{getItem:key=>values[key]},setTimeout,clearTimeout,atob,encodeURIComponent,Date};
 vm.createContext(context);vm.runInContext(source,context);
 const select=new Element('select');window.m2vSongPicker.mount(select,request,choose);
 return {select,dialog:document.body.children[0],values};
}
const song=(id='v1')=>({title:'Rabbit Hole',current_task_id:id,versions:[{id,title:'Original',editable:true,updated_at:'2026-10-16T00:00:00Z'},{id:'failed',title:'Failed import',editable:false}]});
test('picker pages songs, excludes failed versions, and opens the selected editable version',async()=>{
 const calls=[],chosen=[];
 const s=setup(async path=>{calls.push(path);return {songs:[song()],total:13};},async id=>{chosen.push(id);return true;});
 s.select.next.onclick();await flush();
 assert.equal(s.select.hidden,true);
 const list=s.dialog.querySelector('.picker-list');
 assert.equal(list.children[0].children[1].options.length,1);
 assert.equal(s.dialog.querySelector('.picker-next').disabled,false);
 await s.dialog.querySelector('.picker-next').onclick();
 assert.match(calls[1],/page=2/);
 await s.dialog.querySelector('.picker-list').children[0].children[2].onclick();
 assert.deepEqual(chosen,['v1']);assert.equal(s.dialog.open,false);
});
test('a delayed picker response is discarded when the signed-in account changes',async()=>{
 let resolve;const s=setup(()=>new Promise(r=>resolve=r));
 s.select.next.onclick();s.values.m2v_user=JSON.stringify({id:'bob'});
 resolve({songs:[song()],total:1});await flush();
 assert.equal(s.dialog.open,false);
 assert.equal(s.dialog.querySelector('.picker-list').children.length,0);
});
test('declining an unsaved-change switch leaves the picker open',async()=>{
 const s=setup(async()=>({songs:[song()],total:1}),async()=>false);
 s.select.next.onclick();await flush();
 await s.dialog.querySelector('.picker-list').children[0].children[2].onclick();
 assert.equal(s.dialog.open,true);
});
