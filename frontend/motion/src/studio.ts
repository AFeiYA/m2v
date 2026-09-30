import { MotionEngine } from './engine';
import { defaults, normalizeProject, renderSize, type Project, type Options, type MotionPlan } from './model';
const $=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
const audio=new Audio();
let project:Project|null=null,plan:MotionPlan|null=null,engine:MotionEngine|null=null,selected='',currentCue='',dirty=false,jobId='',playing=false;
const options:Options={...defaults,height:720};
const status=(text:string)=>{$('status').textContent=text;};
async function api(path:string,method='GET',body?:unknown){
 const response=await fetch('/api/motion/'+path,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
 const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:JSON.stringify(result.detail||result));return result;
}
function download(name:string,data:string,type='application/json'){const url=URL.createObjectURL(new Blob([data],{type})),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function refresh(){if(!project)return;project.motion_plan=plan||undefined;const {width,height}=renderSize(options),canvas=$<HTMLCanvasElement>('stage');engine?.dispose();canvas.width=width;canvas.height=height;canvas.style.aspectRatio=`${width}/${height}`;$('stage-box').style.aspectRatio=`${width}/${height}`;engine=new MotionEngine(canvas,project,options,width,height);engine.renderAt(audio.currentTime||0);$('stage-meta').textContent=`${options.aspect} · ${width}×${height}`;}
function listCues(){const select=$<HTMLSelectElement>('cue-select');select.replaceChildren();for(const cue of plan?.cues||[]){const line=project?.lines.find(l=>l.id===cue.line_id),item=document.createElement('option');item.value=cue.line_id;item.textContent=(cue.locked?'🔒 ':'')+(line?.text||cue.line_id);select.append(item);}if(plan?.cues.some(c=>c.line_id===currentCue))select.value=currentCue;else currentCue=plan?.cues[0]?.line_id||'';showCue(false);}
function showCue(seek=true){const cue=plan?.cues.find(c=>c.line_id===currentCue);if(!cue)return;
 $<HTMLSelectElement>('cue-template').value=cue.template;$<HTMLSelectElement>('cue-layout').value=cue.layout;$<HTMLSelectElement>('cue-palette').value=cue.palette;$<HTMLInputElement>('cue-intensity').value=String(cue.intensity);$<HTMLInputElement>('cue-emphasis').value=cue.emphasis;$<HTMLInputElement>('cue-locked').checked=cue.locked;
 if(seek){audio.pause();playing=false;$('play').textContent='▶';const line=project?.lines.find(l=>l.id===currentCue);audio.currentTime=line?Math.min(line.end-.001,line.start+.15):0;engine?.renderAt(audio.currentTime);$<HTMLInputElement>('seek').value=String(audio.currentTime);$('time').textContent=audio.currentTime.toFixed(2)+'s';}}
async function savePlan(){if(!plan||!selected)return;plan=await api('plan','PUT',{project_id:selected,plan,from_llm:false});dirty=false;status('导演方案已保存');}
async function load(id:string){if(!id)return;if(dirty)await savePlan();audio.pause();playing=false;$('play').textContent='▶';const result=await api('project?project_id='+encodeURIComponent(id));project=normalizeProject(result.project);plan=result.plan;selected=id;dirty=false;audio.src=result.audio_url||'';audio.currentTime=0;audio.load();$('track-name').textContent=project.title||$<HTMLSelectElement>('project-select').selectedOptions[0].text;$<HTMLInputElement>('seek').max=String(project.duration);$('duration').textContent=project.duration.toFixed(1)+'s';$('analysis-status').textContent=project.analysis.energy_curve.length?`音乐数据已就绪 · ${project.analysis.beats.length} 拍点 · 估算 ${project.analysis.bpm} BPM`:'尚无音频分析，可先到歌词编辑器补做';refresh();listCues();await loadExports();status(result.plan_error||(plan?'已加载保存的导演方案':'请选择风格并生成导演方案'));}
async function rules(onlyCurrent=false){
 if(!selected)throw new Error('请先选择歌曲');if(dirty)await savePlan();
 plan=await api('director/rules','POST',{project_id:selected,style:$<HTMLSelectElement>('preset').value,line_id:onlyCurrent?currentCue:null});
 refresh();listCues();status('导演方案已生成并保存，可逐句调整');
}
async function exportVideo(){if(!selected||!plan)throw new Error('请先生成导演方案');if(dirty)await savePlan();const full=$<HTMLSelectElement>('export-range').value==='full';const result=await api('render','POST',{project_id:selected,aspect:options.aspect,height:options.height,bloom:options.bloom,shake:options.shake,post:options.post,start:full?0:Number($<HTMLInputElement>('clip-start').value),length:full?null:Number($<HTMLInputElement>('clip-length').value)});jobId=result.id;$<HTMLButtonElement>('export').disabled=true;$('download').hidden=true;$('cancel').hidden=false;
 try{for(;;){const job=await api('render/'+jobId);$('export-status').textContent=job.status==='running'?`渲染 ${job.frames}/${job.total} 帧 (${Math.round(job.frames/job.total*100)}%)`:job.status==='queued'?'等待渲染…':job.status==='done'?'成片已完成':job.status==='cancelled'?'导出已取消':'导出失败：'+job.error;
 if(['done','failed','cancelled'].includes(job.status)){if(job.status==='done'){const link=$<HTMLAnchorElement>('download');link.href='/api/motion/render/'+jobId+'/download';link.hidden=false;}break;}await new Promise(resolve=>setTimeout(resolve,1000));}}
 finally{$<HTMLButtonElement>('export').disabled=false;$('cancel').hidden=true;}}
function action(fn:()=>unknown){return async()=>{try{await fn();}catch(error){status(error instanceof Error?error.message:String(error));console.error(error);}};}
$('generate').onclick=action(()=>rules());$('regenerate-cue').onclick=action(()=>rules(true));$('save-plan').onclick=action(savePlan);
async function directorPrompt(single:boolean){
 if(!selected)throw new Error('请先选择歌曲');if(single&&!currentCue)throw new Error('请先生成方案并选择一句歌词');if(dirty)await savePlan();
 const result=await api(single?'director/line/input':'director/input','POST',{project_id:selected,style:$<HTMLSelectElement>('preset').value,instruction:$<HTMLTextAreaElement>('director-instruction').value,...(single?{line_id:currentCue}:{})});
 $<HTMLTextAreaElement>('director-prompt').value=result.prompt;$<HTMLSelectElement>('import-scope').value=single?'line':'song';
 download(single?`motion-${currentCue}-prompt.txt`:'motion-director-prompt.txt',result.prompt,'text/plain');
 status(result.warnings?.length?result.warnings.join('；'):single?'单句提示词已生成；LLM 返回词组索引，系统绑定真实时间':'整曲提示词已生成');
}
$('director-input').onclick=action(()=>directorPrompt(false));$('line-director-input').onclick=action(()=>directorPrompt(true));
async function returnedPlan(apply:boolean){
 if(!selected)throw new Error('请先选择歌曲');if(dirty)throw new Error('请先保存本地修改，再校验或应用 LLM 方案');
 const data=JSON.parse($<HTMLTextAreaElement>('llm-return').value.trim().replace(/^```(?:json)?\s*/,'').replace(/\s*```$/,''));
 const single=$<HTMLSelectElement>('import-scope').value==='line';
 const result=await api(single?`director/line/${apply?'apply':'validate'}`:apply?'plan':'director/validate',single?'POST':apply?'PUT':'POST',single?{project_id:selected,line_id:currentCue,response:data,style:$<HTMLSelectElement>('preset').value}:{project_id:selected,plan:data,from_llm:true});
 $('director-validation').textContent=single?`校验通过 · 整句保留 · ${result.compiled_groups.length} 个词组：`+result.compiled_groups.map((group:{text:string;start:number;end:number})=>`${group.text} ${group.start.toFixed(3)}–${group.end.toFixed(3)}s`).join('；'):'整曲方案校验通过';
 if(apply){plan=single?result.plan:result;dirty=false;refresh();listCues();status(single?'单句方案已应用，其他句子保持原方案':'整曲方案已应用并保存');}
 else status('校验通过，尚未应用；确认内容后点击“应用并保存方案”');
}
$('validate-plan').onclick=action(()=>returnedPlan(false));$('import-plan').onclick=action(()=>returnedPlan(true));
$('download-plan').onclick=action(()=>{if(!plan)throw new Error('尚无方案');download('motion-plan.json',JSON.stringify(plan,null,2));});
$<HTMLSelectElement>('project-select').onchange=action(()=>load($<HTMLSelectElement>('project-select').value));$<HTMLSelectElement>('cue-select').onchange=()=>{currentCue=$<HTMLSelectElement>('cue-select').value;showCue();};
for(const id of ['cue-template','cue-layout','cue-palette','cue-intensity','cue-emphasis','cue-locked'])$(id).addEventListener('input',()=>{const cue=plan?.cues.find(c=>c.line_id===currentCue);if(!cue)return;cue.template=$<HTMLSelectElement>('cue-template').value as typeof cue.template;cue.layout=$<HTMLSelectElement>('cue-layout').value as typeof cue.layout;cue.palette=$<HTMLSelectElement>('cue-palette').value as typeof cue.palette;cue.intensity=Number($<HTMLInputElement>('cue-intensity').value);cue.emphasis=$<HTMLInputElement>('cue-emphasis').value;cue.locked=$<HTMLInputElement>('cue-locked').checked;dirty=true;refresh();status('预览已更新 · 修改尚未保存');});
for(const id of ['aspect','resolution','post','bloom','shake'])$(id).addEventListener('input',()=>{options.aspect=$<HTMLSelectElement>('aspect').value as Options['aspect'];options.height=Number($<HTMLSelectElement>('resolution').value) as 360|720;options.post=$<HTMLInputElement>('post').checked;options.bloom=Number($<HTMLInputElement>('bloom').value);options.shake=Number($<HTMLInputElement>('shake').value);refresh();});
$('play').onclick=action(async()=>{if(!project)return;if(playing){audio.pause();playing=false;$('play').textContent='▶';}else{await audio.play();playing=true;$('play').textContent='Ⅱ';}});$<HTMLInputElement>('seek').oninput=()=>{audio.currentTime=Number($<HTMLInputElement>('seek').value);engine?.renderAt(audio.currentTime);};$('export').onclick=action(exportVideo);$('cancel').onclick=action(()=>api('render/'+jobId+'/cancel','POST'));
function tick(){if(engine&&playing){engine.renderAt(audio.currentTime);$<HTMLInputElement>('seek').value=String(audio.currentTime);$('time').textContent=audio.currentTime.toFixed(2)+'s';if(audio.ended){playing=false;$('play').textContent='▶';}}requestAnimationFrame(tick);}requestAnimationFrame(tick);
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
(async()=>{try{const rows=await api('projects'),select=$<HTMLSelectElement>('project-select');for(const row of rows){const item=document.createElement('option');item.value=row.id;item.textContent=row.name;select.append(item);}const wanted=new URLSearchParams(location.search).get('song');const chosen=rows.find((row:{id:string;name:string})=>row.name===wanted)||(rows.length===1?rows[0]:null);if(chosen){select.value=chosen.id;await load(chosen.id);}}catch(error){status(String(error));}})();

async function loadExports(){
  const list=$('export-history');list.replaceChildren();
  for(const job of await api('exports?project_id='+encodeURIComponent(selected))){
    if(job.status!=='done')continue;
    const link=document.createElement('a');link.href='/api/motion/render/'+job.id+'/download';link.textContent=`${job.width?job.width+"×"+job.height+" · ":""}${(job.total/30).toFixed(1)} 秒 · ${new Date(job.created_at*1000).toLocaleString()}`;link.download='motion-studio.mp4';link.style.display='block';list.append(link);
  }
}

$('focus-preview').onclick=()=>{const focused=document.body.classList.toggle('preview-focus');$('focus-preview').textContent=focused?'显示设置':'放大预览';};
