import { MotionEngine } from './engine';
import { demo, demoAudio, defaults, normalizeProject, type Project, type Options } from './model';
const $=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
const canvas=$<HTMLCanvasElement>('stage'),audio=new Audio();audio.preload='auto';
let project:Project=demo, options:Options={...defaults}, engine:MotionEngine|null=null, audioBlob:Blob=demoAudio(), audioUrl='', demoMode=true, selectedProject='';
let playing=false, previewTime=0, previousFrame=0;
const fmt=(t:number)=>{const m=Math.floor(t/60),s=t%60;return `${String(m).padStart(2,'0')}:${s.toFixed(2).padStart(5,'0')}`;};
const setStatus=(s:string)=>{$('status').textContent=s;};
const fail=(e:unknown)=>{const msg=e instanceof Error?e.message:String(e);$('stage-error').textContent=msg;$('stage-error').hidden=false;setStatus(msg);console.error(e);};
function setAudio(blob:Blob){if(audioUrl)URL.revokeObjectURL(audioUrl);audioBlob=blob;audioUrl=URL.createObjectURL(blob);audio.src=audioUrl;audio.load();}
function refreshEngine(){
  try {engine?.dispose();const w=options.aspect==='16:9'?1280:720,h=options.aspect==='16:9'?720:1280;
    canvas.width=w;canvas.height=h;canvas.style.aspectRatio=`${w} / ${h}`;$('stage-meta').textContent=`${options.aspect} · ${w}×${h}`;
    engine=new MotionEngine(canvas,project,options,w,h);$('stage-error').hidden=true;engine.renderAt(audio.currentTime||0);
  }catch(e){engine=null;fail(e);}
}
function setProject(p:Project,blob?:Blob){
  audio.pause();playing=false;$('play').textContent='▶';project=p;
  if(blob)setAudio(blob); else {audio.removeAttribute('src');audio.load();audioBlob=new Blob();}
  $('track-name').textContent=p.title;$('seek').setAttribute('max',String(p.duration));$('duration').textContent=fmt(p.duration);
  $('source-type').textContent=demoMode?'合成节奏演示':'歌曲工程';
  $('clip-start').setAttribute('max',String(Math.max(0,p.duration-1)));
  refreshEngine();audio.currentTime=0;previewTime=0;previousFrame=0;
  $<HTMLInputElement>('seek').value='0';$('time').textContent=fmt(0);
  setStatus(p.analysis.beats.length?'已载入歌词和拍点':'已载入歌词；暂无拍点，关闭节拍冲击');
}
function tick(now:number){
  if(playing&&engine){const t=audio.src?audio.currentTime:Math.min(project.duration,previewTime+Math.min(0.1,(now-(previousFrame||now))/1000));
    if(!audio.src)previewTime=t;previousFrame=now;
    if(audio.ended||t>=project.duration){playing=false;audio.pause();$('play').textContent='▶';}
    engine.renderAt(t);$('seek').setAttribute('value',String(t));($<HTMLInputElement>('seek')).value=String(t);$('time').textContent=fmt(t);
    const line=project.lines.find(l=>t>=l.start&&t<l.end);$('line-status').textContent=line?.text||'';
  }
  requestAnimationFrame(tick);
}
async function loadSavedProjects(){
  try{const r=await fetch('/api/motion/projects');if(!r.ok)throw new Error('无法读取工程列表');
    const projects: {id:string;name:string}[]=await r.json();const select=$<HTMLSelectElement>('project-select');
    for(const p of projects){const o=document.createElement('option');o.value=p.id;o.textContent=p.name;select.appendChild(o);}
  }catch(e){setStatus('工程列表不可用，可手动选择文件');}
}
async function loadSaved(id:string){
  if(!id)return;try{setStatus('正在载入工程…');const r=await fetch(`/api/motion/project?project_id=${encodeURIComponent(id)}`);if(!r.ok)throw new Error(await r.text());
    const result=await r.json();const p=normalizeProject(result.project);demoMode=false;selectedProject=id;
    if(result.audio_url){const a=await fetch(result.audio_url);if(!a.ok)throw new Error('音频读取失败');setProject(p,await a.blob());}
    else {setProject(p);setStatus('已载入工程。未发现原曲音频，请手动选择音频文件。');}
  }catch(e){fail(e);}
}
function updateOptions(){
  options={...options,aspect:$<HTMLSelectElement>('aspect').value as Options['aspect'],preset:$<HTMLSelectElement>('preset').value as Options['preset'],
    mode:$<HTMLSelectElement>('mode').value as Options['mode'],post:$<HTMLInputElement>('post').checked,
    punch:Number($<HTMLInputElement>('punch').value),bloom:Number($<HTMLInputElement>('bloom').value),shake:Number($<HTMLInputElement>('shake').value)};
  for(const id of ['punch','bloom','shake'])$(id+'-value').textContent=$<HTMLInputElement>(id).value;
  refreshEngine();
}
function bind(){
  $('demo').onclick=()=>{demoMode=true;selectedProject='';$<HTMLSelectElement>('project-select').value='';setProject(demo,demoAudio());};
  $<HTMLSelectElement>('project-select').onchange=e=>loadSaved((e.target as HTMLSelectElement).value);
  $<HTMLInputElement>('json-file').onchange=async e=>{const f=(e.target as HTMLInputElement).files?.[0];if(!f)return;
    try{demoMode=false;selectedProject='';setProject(normalizeProject(JSON.parse(await f.text())));setStatus('已载入对齐文件，请选择对应音频');}catch(err){fail(err);}};
  $<HTMLInputElement>('audio-file').onchange=e=>{const f=(e.target as HTMLInputElement).files?.[0];if(f){setAudio(f);setStatus(`已载入音频：${f.name}`);}};
  $('play').onclick=()=>{if(!engine)return;if(playing){audio.pause();playing=false;$('play').textContent='▶';}else{
    if(audio.src){audio.play().catch(fail);}else previewTime=Number($<HTMLInputElement>('seek').value);previousFrame=0;playing=true;$('play').textContent='Ⅱ';}};
  $<HTMLInputElement>('seek').oninput=e=>{const t=Number((e.target as HTMLInputElement).value);if(audio.src)audio.currentTime=t;else previewTime=t;
    engine?.renderAt(t);$('time').textContent=fmt(t);$('line-status').textContent=project.lines.find(l=>t>=l.start&&t<l.end)?.text||'';};
  for(const id of ['aspect','preset','mode','post','punch','bloom','shake'])$(id).addEventListener('input',updateOptions);
  $('export').onclick=()=>{location.href='/motion_studio';};
}
async function exportClip(){
  const start=Number($<HTMLInputElement>('clip-start').value),length=Number($<HTMLInputElement>('clip-length').value);
  if(!Number.isFinite(start)||!Number.isFinite(length)||start<0||length<1||length>15||start+length>project.duration+.05){$('export-status').textContent='请设置位于歌曲范围内的 1–15 秒片段。';return;}
  if(!audioBlob.size){$('export-status').textContent='需要音频文件才能导出 MP4。';return;}
  const btn=$<HTMLButtonElement>('export');btn.disabled=true;$('download').hidden=true;
  try{
    $('export-status').textContent='正在上传音频…';
    const upload=await fetch('/api/upload-audio',{method:'POST',headers:{'Content-Type':audioBlob.type||'application/octet-stream'},body:audioBlob});
    if(!upload.ok)throw new Error(await upload.text());const {audioId}=await upload.json();
    const result=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project,options,audioId,start,length})});
    if(!result.ok)throw new Error(await result.text());const {id}=await result.json();
    const timer=setInterval(async()=>{
      try{const r=await fetch(`/api/render/${id}`);const j=await r.json();$('export-status').textContent=j.status==='running'?`渲染中 ${j.frames||0}/${j.total||0} 帧`:j.status==='failed'?`导出失败：${j.error}`:j.status==='done'?'已完成，可以下载。':'排队中…';
        if(j.status==='done'){clearInterval(timer);const a=$<HTMLAnchorElement>('download');a.href=`/api/render/${id}/download`;a.hidden=false;btn.disabled=false;}
        if(j.status==='failed'){clearInterval(timer);btn.disabled=false;}
      }catch(e){clearInterval(timer);btn.disabled=false;fail(e);}
    },1000);
  }catch(e){btn.disabled=false;fail(e);$('export-status').textContent=String(e);}
}
bind();setProject(demo,demoAudio());loadSavedProjects();requestAnimationFrame(tick);
