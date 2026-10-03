import {checkImportScope} from './import-scope';
import {compileSongPosters,canvasMeasure,paintCompiledPoster,automaticPoster,resolvePaletteColors,type CompiledPoster,type DefaultLayoutPreset} from './poster-layout';
import { RemotionPreview } from './remotion-preview';
import { defaults, normalizeProject, renderSize, type Project, type Options, type MotionPlan } from './model';
const $=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
const audio=new Audio();
let project:Project|null=null,plan:MotionPlan|null=null,engine:RemotionPreview|null=null,selected='',currentCue='',dirty=false,jobId='',playing=false;
let scrubbing=false,resumeAfterScrub=false;
let posterPreview:CompiledPoster|null=null,clipEnd:number|null=null,clipReviewTime=0,reviewHandover=false;
const options:Options={...defaults,height:720};
const status=(text:string)=>{$('status').textContent=text;};
async function api(path:string,method='GET',body?:unknown){
 const response=await fetch('/api/motion/'+path,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
 const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:JSON.stringify(result.detail||result));return result;
}
function download(name:string,data:string,type='application/json'){const url=URL.createObjectURL(new Blob([data],{type})),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function refresh(){if(!project)return;project.motion_plan=plan||undefined;const {width,height}=renderSize(options),canvas=$<HTMLCanvasElement>('stage');engine?.dispose();canvas.width=width;canvas.height=height;canvas.style.aspectRatio=`${width}/${height}`;$('stage-box').style.aspectRatio=`${width}/${height}`;engine=new RemotionPreview(canvas,project,options,width,height);engine.renderAt(audio.currentTime||0);$('stage-meta').textContent=`Remotion · ${options.aspect} · ${width}×${height}`;}
function listCues(){const select=$<HTMLSelectElement>('cue-select');select.replaceChildren();for(const cue of plan?.cues||[]){const line=project?.lines.find(l=>l.id===cue.line_id),item=document.createElement('option');item.value=cue.line_id;item.textContent=(cue.locked?'🔒 ':'')+(line?.text||cue.line_id);select.append(item);}if(plan?.cues.some(c=>c.line_id===currentCue))select.value=currentCue;else currentCue=plan?.cues[0]?.line_id||'';showCue(false);}
function showCue(seek=true){const cue=plan?.cues.find(c=>c.line_id===currentCue);if(!cue)return;
 const line=project?.lines.find(l=>l.id===currentCue);
 $<HTMLSelectElement>('poster-layout').value=cue.poster?.layout||'hero-stack';$('poster-design-status').textContent=cue.poster?'使用已保存的导演海报设计':'使用自动基础排版，可导入 LLM 海报设计';
 if($('cue-layout-preset')){
  $<HTMLSelectElement>('cue-layout-preset').disabled=cue.locked;
  $<HTMLButtonElement>('apply-layout-preset').disabled=cue.locked;
  if(cue.poster?.intent?.includes('单行'))$<HTMLSelectElement>('cue-layout-preset').value='single';
  else if(cue.poster?.intent?.includes('双行'))$<HTMLSelectElement>('cue-layout-preset').value='two-stack';
  else if(cue.poster?.intent?.includes('三段'))$<HTMLSelectElement>('cue-layout-preset').value='three-stack';
  else if(cue.poster?.intent?.includes('逐词'))$<HTMLSelectElement>('cue-layout-preset').value='word-by-word';
  else $<HTMLSelectElement>('cue-layout-preset').value='smart';
 }
 if($('cue-palette')){
  $<HTMLSelectElement>('cue-palette').disabled=cue.locked;
  $<HTMLSelectElement>('cue-palette').value=cue.palette||'impact';
  if($('apply-palette'))$<HTMLButtonElement>('apply-palette').disabled=cue.locked;
 }
 $<HTMLSelectElement>('visual-intensity').value=cue.poster?.visual_intensity||'auto';$<HTMLSelectElement>('visual-intensity').disabled=cue.locked;
 $<HTMLSelectElement>('semantic-mode').value=cue.poster?.semantic_mode||'auto';$<HTMLSelectElement>('semantic-mode').disabled=cue.locked;
 $<HTMLSelectElement>('cue-exit').value=cue.poster?.transition_out||'cut';$<HTMLSelectElement>('cue-exit').disabled=cue.locked;
 if(line){renderPosterNodes(line,cue);const size=renderSize(options),c=document.createElement('canvas').getContext('2d')!;
  const p=compileSongPosters(project!,size.width,size.height,canvasMeasure(c)).find(p=>p.line_id===line.id)!;
  $('visual-intensity-status').textContent=`当前采用${{restrained:'克制',expanded:'展开',peak:'峰值'}[p.visual_intensity]}档 · 统一控制字号与入场幅度；快唱与安全区优先。`;
  $('handover-status').textContent=`唱完后保留 ${(Math.max(0,(p.handover?.visible_end||p.end)-p.end)).toFixed(2)} 秒 · ${p.handover?.mode==='layered-fade'?'辅文先退，核心词后退':p.handover?.mode==='fade'?'短淡出交接':'直接交接'}。歌词与音频时间保持原样。`;
 }
 $<HTMLSelectElement>('cue-template').value=cue.template;$<HTMLSelectElement>('cue-layout').value=cue.layout;$<HTMLSelectElement>('cue-palette').value=cue.palette;$<HTMLInputElement>('cue-intensity').value=String(cue.intensity);$<HTMLInputElement>('cue-emphasis').value=cue.emphasis;$<HTMLInputElement>('cue-locked').checked=cue.locked;
 if(seek){clipEnd=null;audio.pause();playing=false;$('play').textContent='▶';const line=project?.lines.find(l=>l.id===currentCue);audio.currentTime=line?Math.min(line.end-.001,line.start+.15):0;engine?.renderAt(audio.currentTime);$<HTMLInputElement>('seek').value=String(audio.currentTime);$('time').textContent=audio.currentTime.toFixed(2)+'s';}}
async function savePlan(){if(!plan||!selected)return;plan=await api('plan','PUT',{project_id:selected,plan,from_llm:false});dirty=false;status('导演方案已保存');}
async function load(id:string){if(!id)return;if(dirty)await savePlan();audio.pause();playing=false;$('play').textContent='▶';const result=await api('project?project_id='+encodeURIComponent(id));project=normalizeProject(result.project);plan=result.plan;selected=id;dirty=false;audio.src=result.audio_url||'';audio.currentTime=0;audio.load();$('track-name').textContent=project.title||$<HTMLSelectElement>('project-select').selectedOptions[0].text;$<HTMLInputElement>('seek').max=String(project.duration);$('duration').textContent=project.duration.toFixed(1)+'s';$('analysis-status').textContent=project.analysis.energy_curve.length?`音乐数据已就绪 · ${project.analysis.beats.length} 拍点 · 估算 ${project.analysis.bpm} BPM`:'尚无音频分析，可先到歌词编辑器补做';refresh();listCues();await loadExports();status(result.plan_error||(plan?'已加载保存的导演方案':'请选择风格并生成导演方案'));}
async function rules(onlyCurrent=false){
 if(!selected)throw new Error('请先选择歌曲');if(dirty)await savePlan();
 const preset=($<HTMLSelectElement>('default-layout-preset')?.value as DefaultLayoutPreset)||'smart';
 const palette=$<HTMLSelectElement>('preset')?.value || 'impact';
 const bgTone=($<HTMLSelectElement>('theme-bg')?.value as 'auto'|'light'|'dark')||'auto';
 plan=await api('director/rules','POST',{project_id:selected,style:palette,line_id:onlyCurrent?currentCue:null});
 if(plan?.cues){
  for(const cue of plan.cues){
   if(onlyCurrent&&cue.line_id!==currentCue)continue;
   if(cue.locked)continue;
   const line=project?.lines.find(l=>l.id===cue.line_id);
   if(line){
    const cuePreset=onlyCurrent?(($<HTMLSelectElement>('cue-layout-preset')?.value as DefaultLayoutPreset)||preset):preset;
    const cuePalette=onlyCurrent?(($<HTMLSelectElement>('cue-palette')?.value)||palette):palette;
    cue.palette=cuePalette;
    cue.poster=automaticPoster(line,cuePalette,cuePreset,bgTone);
   }
  }
  await savePlan();
 }
 refresh();listCues();status(onlyCurrent?'当前句排版已重新生成并保存':'导演方案已生成并保存，可逐句调整');
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
 status(result.warnings?.length?result.warnings.join('；'):single?'单句提示词已生成：最终海报＋入场与衔接草案':'整曲提示词已生成：每句海报＋动画草案');
}
$('director-input').onclick=action(()=>directorPrompt(false));$('line-director-input').onclick=action(()=>directorPrompt(true));
let aiJob='',aiBaseline='',aiBusy=false;
async function loadAIConfig(){try{const config=await api('director/config');$('ai-config-status').textContent=config.configured?`已接入 ${config.model}${config.fallback_model?` · 额度不足时切换 ${config.fallback_model}`:''} · 仅发送歌词、时间与音乐分析数据`:'未配置 Gemini 密钥 · 在后端 .env 设置 GEMINI_API_KEY';for(const id of ['ai-line','ai-song'])$<HTMLButtonElement>(id).disabled=!config.configured;}catch{$('ai-config-status').textContent='无法读取模型配置';}}
async function aiDirector(single:boolean){
 if(aiBusy)return;if(!selected)throw new Error('请先选择歌曲');if(single&&!currentCue)throw new Error('请先生成基础方案并选择一句歌词');if(dirty)await savePlan();
 aiBusy=true;aiJob='';$('ai-apply').hidden=true;for(const id of ['ai-line','ai-song'])$<HTMLButtonElement>(id).disabled=true;
 const projectId=selected;aiBaseline=JSON.stringify(plan);
 try{
  const request=await api('director/generate','POST',{project_id:projectId,line_id:single?currentCue:null,style:$<HTMLSelectElement>('preset').value,instruction:$<HTMLTextAreaElement>('director-instruction').value});
  aiJob=request.id;
  for(;;){const job=await api('director/jobs/'+aiJob);$('ai-job-status').textContent=({queued:'等待 Gemini…',running:'Gemini 正在设计海报与动画…',validating:'正在校验歌词、层级与锁定句…',repairing:'返回值未通过校验，正在自动修正一次…',ready:'校验通过，点击应用后预览和导出',failed:'生成失败：'+job.error} as Record<string,string>)[job.status]||job.status;
   if(job.fallback_used)$('ai-job-status').textContent+=` · 主模型限流或额度不足，已切换 ${job.model}`;
   if(job.status==='failed')throw new Error(job.error);
   if(job.status==='ready'){if(selected!==projectId)throw new Error('歌曲已切换，请回到原歌曲重新生成');$('ai-apply').hidden=false;break;}
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
 }finally{aiBusy=false;for(const id of ['ai-line','ai-song'])$<HTMLButtonElement>(id).disabled=false;}
}
$('ai-line').onclick=action(()=>aiDirector(true));$('ai-song').onclick=action(()=>aiDirector(false));
$('ai-apply').onclick=action(async()=>{if(dirty||JSON.stringify(plan)!==aiBaseline)throw new Error('本地方案已修改，请保存后重新调用 Gemini，防止覆盖修改');const result=await api('director/jobs/'+aiJob+'/apply','POST');plan=result.plan;dirty=false;$('ai-apply').hidden=true;refresh();listCues();$('ai-job-status').textContent='Gemini 方案已应用并保存';status('已按 Gemini 导演方案更新预览，可导出 MP4');});
void loadAIConfig();
async function returnedPlan(apply:boolean){
 if(!selected)throw new Error('请先选择歌曲');if(dirty)throw new Error('请先保存本地修改，再校验或应用 LLM 方案');
 const data=JSON.parse($<HTMLTextAreaElement>('llm-return').value.trim().replace(/^```(?:json)?\s*/,'').replace(/\s*```$/,''));
 const single=$<HTMLSelectElement>('import-scope').value==='line';
 checkImportScope(data,single?'line':'song');
 const result=await api(single?`director/line/${apply?'apply':'validate'}`:apply?'plan':'director/validate',single?'POST':apply?'PUT':'POST',single?{project_id:selected,line_id:currentCue,response:data,style:$<HTMLSelectElement>('preset').value}:{project_id:selected,plan:data,from_llm:true});
 $('director-validation').textContent=single?`校验通过 · 整句保留 · ${result.compiled_groups.length} 个词组：`+result.compiled_groups.map((group:{text:string;start:number;end:number})=>`${group.text} ${group.start.toFixed(3)}–${group.end.toFixed(3)}s`).join('；'):'整曲方案校验通过';
 if(apply){plan=single?result.plan:result;dirty=false;refresh();listCues();status(single?'单句方案已应用，其他句子保持原方案':'整曲方案已应用并保存');}
 else status('校验通过，尚未应用；确认内容后点击“应用并保存方案”');
 const designPlan=single?result.plan:apply?result:result.plan;
 if(designPlan?.cues?.some((cue:{poster?:unknown})=>cue.poster)){status(apply?'海报方案已保存，预览与导出按排版逐组进入':'海报方案校验通过，应用后可查看排版与动画');}
}
$('validate-plan').onclick=action(()=>returnedPlan(false));$('import-plan').onclick=action(()=>returnedPlan(true));
$('download-plan').onclick=action(()=>{if(!plan)throw new Error('尚无方案');download('motion-plan.json',JSON.stringify(plan,null,2));});
$<HTMLSelectElement>('project-select').onchange=action(()=>load($<HTMLSelectElement>('project-select').value));$<HTMLSelectElement>('cue-select').onchange=()=>{currentCue=$<HTMLSelectElement>('cue-select').value;showCue();};
for(const id of ['cue-template','cue-layout','cue-palette','cue-intensity','cue-emphasis','cue-locked'])$(id).addEventListener('input',()=>{const cue=plan?.cues.find(c=>c.line_id===currentCue);if(!cue)return;cue.template=$<HTMLSelectElement>('cue-template').value as typeof cue.template;cue.layout=$<HTMLSelectElement>('cue-layout').value as typeof cue.layout;cue.palette=$<HTMLSelectElement>('cue-palette').value as typeof cue.palette;cue.intensity=Number($<HTMLInputElement>('cue-intensity').value);cue.emphasis=$<HTMLInputElement>('cue-emphasis').value;cue.locked=$<HTMLInputElement>('cue-locked').checked;dirty=true;refresh();if(id==='cue-locked')showCue(false);status('预览已更新 · 修改尚未保存');});
for(const id of ['aspect','resolution','post','bloom','shake'])$(id).addEventListener('input',()=>{options.aspect=$<HTMLSelectElement>('aspect').value as Options['aspect'];options.height=Number($<HTMLSelectElement>('resolution').value) as 360|720;options.post=$<HTMLInputElement>('post').checked;options.bloom=Number($<HTMLInputElement>('bloom').value);options.shake=Number($<HTMLInputElement>('shake').value);refresh();});
$('play').onclick=action(async()=>{if(!project)return;clipEnd=null;if(playing){audio.pause();playing=false;$('play').textContent='▶';}else{await audio.play();playing=true;$('play').textContent='Ⅱ';}});const seek=$<HTMLInputElement>('seek');
function beginScrub(){if(scrubbing)return;scrubbing=true;resumeAfterScrub=playing;audio.pause();playing=false;$('play').textContent='▶';clipEnd=null;}
async function finishScrub(){if(!scrubbing)return;scrubbing=false;const resume=resumeAfterScrub;resumeAfterScrub=false;if(resume){await audio.play();playing=true;$('play').textContent='Ⅱ';}}
seek.onpointerdown=beginScrub;
seek.oninput=()=>{beginScrub();const t=Number(seek.value);audio.currentTime=t;engine?.renderAt(t);$('time').textContent=t.toFixed(2)+'s';};
seek.onchange=action(finishScrub);
window.addEventListener('pointerup',action(finishScrub));
window.addEventListener('pointercancel',()=>{resumeAfterScrub=false;void finishScrub();});
$('export').onclick=action(exportVideo);$('cancel').onclick=action(()=>api('render/'+jobId+'/cancel','POST'));
function tick(){if(engine&&playing){if(clipEnd!==null&&audio.currentTime>=clipEnd){audio.pause();audio.currentTime=clipReviewTime;clipEnd=null;playing=false;$('play').textContent='▶';status(reviewHandover?'交接预览完成':'当前句播放完成，停留在最终海报');}engine.renderAt(audio.currentTime);$<HTMLInputElement>('seek').value=String(audio.currentTime);$('time').textContent=audio.currentTime.toFixed(2)+'s';if(audio.ended){playing=false;$('play').textContent='▶';}}requestAnimationFrame(tick);}requestAnimationFrame(tick);
audio.addEventListener('seeked',()=>{if(scrubbing)return;engine?.renderAt(audio.currentTime);$<HTMLInputElement>('seek').value=String(audio.currentTime);$('time').textContent=audio.currentTime.toFixed(2)+'s';});
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


$('poster-sample').onclick=action(async()=>{
 const line=project?.lines.find(l=>l.id===currentCue);if(!line)throw new Error('请先选择一句歌词');
 audio.pause();clipEnd=null;playing=false;$('play').textContent='▶';await document.fonts.ready;
 const canvas=$<HTMLCanvasElement>('poster-canvas'),size=renderSize(options);canvas.width=size.width;canvas.height=size.height;canvas.style.aspectRatio=`${size.width}/${size.height}`;
 const c=canvas.getContext('2d')!;posterPreview=compileSongPosters(project!,size.width,size.height,canvasMeasure(c)).find(p=>p.line_id===currentCue)!;paintCompiledPoster(c,posterPreview);
 $('poster-title').textContent='当前句 · 最终海报';$('poster-lyric').textContent=line.text;
 const hold=Math.max(0,(posterPreview.handover?.exit_start??line.end)-Math.max(...posterPreview.nodes.map(n=>n.settled)));
 $('poster-description').textContent=`${posterPreview.source==='director'?'导演设计':'自动基础排版'} · ${options.aspect} · ${posterPreview.nodes.length} 个文字块 · 完成后可停留 ${hold.toFixed(2)} 秒。与动画和 MP4 使用同一排版。`;
 $<HTMLDialogElement>('poster-dialog').showModal();
});
$('poster-close').onclick=()=>$<HTMLDialogElement>('poster-dialog').close();
$('poster-json').onclick=()=>{if(posterPreview)download(`${posterPreview.line_id}-poster-layout.json`,JSON.stringify(posterPreview,null,2));};
$('poster-png').onclick=action(()=>{
 $<HTMLCanvasElement>('poster-canvas').toBlob(blob=>{
  if(!blob){status('海报导出失败');return;}
  const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=(posterPreview?.line_id||'lyric')+'-poster.png';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 },'image/png');
});
$('poster-layout').onchange=action(()=>{
 const cue=plan?.cues.find(c=>c.line_id===currentCue),line=project?.lines.find(l=>l.id===currentCue);if(!cue||!line)return;
 if(cue.locked)throw new Error('当前句已锁定，请先解锁');
 cue.poster=cue.poster||automaticPoster(line,cue.palette);cue.poster.layout=$<HTMLSelectElement>('poster-layout').value as typeof cue.poster.layout;
 dirty=true;refresh();status('海报布局已更新，请保存方案');
});
if($('apply-layout-preset')){
 $('apply-layout-preset').onclick=action(async()=>{
  const cue=plan?.cues.find(c=>c.line_id===currentCue),line=project?.lines.find(l=>l.id===currentCue);
  if(!cue||!line)return;
  if(cue.locked)throw new Error('当前句已锁定，请先解锁');
  const preset=($<HTMLSelectElement>('cue-layout-preset')?.value as DefaultLayoutPreset)||'smart';
  const bgTone=($<HTMLSelectElement>('theme-bg')?.value as 'auto'|'light'|'dark')||'auto';
  cue.poster=automaticPoster(line,cue.palette,preset,bgTone);
  dirty=true;refresh();showCue(false);status(`已应用「${preset}」排版预设，请保存方案`);
 });
}
if($('apply-palette')){
 $('apply-palette').onclick=action(async()=>{
  const cue=plan?.cues.find(c=>c.line_id===currentCue),line=project?.lines.find(l=>l.id===currentCue);
  if(!cue||!line)return;
  if(cue.locked)throw new Error('当前句已锁定，请先解锁');
  const palette=$<HTMLSelectElement>('cue-palette')?.value || 'impact';
  const bgTone=($<HTMLSelectElement>('theme-bg')?.value as 'auto'|'light'|'dark')||'auto';
  cue.palette=palette;
  const colors=resolvePaletteColors(palette,bgTone);
  if(cue.poster){
    cue.poster.background=colors.background;
    cue.poster.accent=colors.accent;
  }else{
    const preset=($<HTMLSelectElement>('cue-layout-preset')?.value as DefaultLayoutPreset)||'smart';
    cue.poster=automaticPoster(line,palette,preset,bgTone);
  }
  dirty=true;refresh();showCue(false);status(`已应用「${palette}」配色，请保存方案`);
 });
}
async function playCue(handover=false){
 const line=project?.lines.find(l=>l.id===currentCue);if(!line)throw new Error('请先选择一句歌词');
 $<HTMLDialogElement>('poster-dialog').close();const size=renderSize(options),context=document.createElement('canvas').getContext('2d')!;
 const compiled=compileSongPosters(project!,size.width,size.height,canvasMeasure(context)).find(p=>p.line_id===currentCue)!;
 clipReviewTime=Math.max(line.start,Math.min(line.end-.001,Math.max(...compiled.nodes.map(n=>n.settled),line.end-.16)));
 reviewHandover=handover;clipEnd=handover?Math.min(project!.duration,(compiled.handover?.next_start??compiled.handover?.visible_end??line.end)+.7):line.end;
 if(handover)clipReviewTime=Math.max(line.start,clipEnd-.001);
 audio.currentTime=line.start;await audio.play();playing=true;$('play').textContent='Ⅱ';
}
$('play-cue').onclick=action(()=>playCue());$('play-handover').onclick=action(()=>playCue(true));
$('cue-exit').onchange=()=>{const cue=plan?.cues.find(c=>c.line_id===currentCue),line=project?.lines.find(l=>l.id===currentCue);if(!cue||!line||cue.locked)return;cue.poster=cue.poster||automaticPoster(line,cue.palette);cue.poster.transition_out=$<HTMLSelectElement>('cue-exit').value as 'fade'|'cut';dirty=true;refresh();showCue(false);status('交接策略已更新，请保存方案');};

$('visual-intensity').onchange=()=>{const cue=plan?.cues.find(c=>c.line_id===currentCue),line=project?.lines.find(l=>l.id===currentCue);if(!cue||!line||cue.locked)return;cue.poster=cue.poster||automaticPoster(line,cue.palette);cue.poster.visual_intensity=$<HTMLSelectElement>('visual-intensity').value as NonNullable<typeof cue.poster.visual_intensity>;dirty=true;refresh();showCue(false);status('视觉强度已更新，请保存方案');};
$('semantic-mode').onchange=()=>{const cue=plan?.cues.find(c=>c.line_id===currentCue),line=project?.lines.find(l=>l.id===currentCue);if(!cue||!line||cue.locked)return;cue.poster=cue.poster||automaticPoster(line,cue.palette);cue.poster.semantic_mode=$<HTMLSelectElement>('semantic-mode').value as 'auto'|'off';dirty=true;refresh();showCue(false);status('语义编排模式已更新，请保存方案');};

function renderPosterNodes(line:import('./model').Line,cue:import('./model').CuePlan){
 const host=$('poster-node-editor');host.replaceChildren();const direction=cue.poster||automaticPoster(line,cue.palette);
 const relations=document.createElement('div');relations.setAttribute('aria-label','歌词语义关系');
 const names={guidance:'引导',contrast:'对照',negation:'否定',repetition:'重复',spatial:'空间意象'};
 if(direction.relations?.length){for(const relation of direction.relations){const item=document.createElement('p');item.textContent=`${names[relation.kind]} · ${relation.node_indices.map(i=>direction.nodes[i]?.text||'无效节点').join(' → ')}：${relation.intent}`;relations.append(item);}}
 else relations.textContent='暂无语义关系，可通过新版 LLM 提示词规划。';
 const size=renderSize(options),context=document.createElement('canvas').getContext('2d')!;
 const compiled=compileSongPosters(project!,size.width,size.height,canvasMeasure(context)).find(p=>p.line_id===line.id)!;
 for(const applied of compiled.semantic_arrangement){const item=document.createElement('p');item.textContent=`${names[applied.kind]} · ${applied.status==='applied'?'已编排':applied.status==='disabled'?'已关闭':'有限支持'}：${applied.effects.join('；')}`;relations.append(item);}
 const help=document.createElement('small');help.textContent='自动模式会调整下方源参数；关闭后使用手工参数。演唱起点、唯一主视觉和快唱限制优先。';relations.append(help);host.append(relations);

 direction.nodes.forEach((node,i)=>{
  const card=document.createElement('div');card.style.cssText='padding:12px 0;border-bottom:1px solid #263530';
  const title=document.createElement('strong');title.textContent=node.text;title.style.display='block';card.append(title);const actual=document.createElement('small');const motionNames={none:'直接出现',fade:'淡入','slide-up':'向上落位','slide-left':'从左进入','scale-in':'缩放落位'};actual.textContent='当前实际入场：'+motionNames[compiled.nodes[i].entrance];card.append(actual);
  const fields:[string,string,[string,string][]][]=[['role','层级',[['primary','主视觉'],['secondary','次级'],['support','辅助']]],['entrance','入场',[['none','直接出现'],['fade','淡入'],['slide-up','向上落位'],['slide-left','从左进入'],['scale-in','缩放落位']]],['beat_reaction','拍点',[['none','无'],['pulse','主视觉回弹']]]];
  for(const [key,label,choices] of fields){const wrapper=document.createElement('label');wrapper.textContent=label;const select=document.createElement('select');select.setAttribute('aria-label',node.text+' '+label);
   for(const [value,text] of choices){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}
   select.value=String((node as any)[key]||'none');select.disabled=cue.locked;
   select.onchange=()=>{cue.poster=cue.poster||automaticPoster(line,cue.palette);const target=cue.poster.nodes[i];
    if(key==='role'&&select.value==='primary'){cue.poster.nodes.forEach(n=>{if(n.role==='primary'){n.role='secondary';n.beat_reaction='none';}});}
    if(key==='role'&&select.value!=='primary'&&target.role==='primary'){status('请先把另一个文字块设为主视觉');select.value='primary';return;}
    if(key==='beat_reaction'&&select.value==='pulse'&&target.role!=='primary'){status('拍点回弹只用于主视觉');select.value='none';return;}
    (target as any)[key]=select.value;dirty=true;refresh();renderPosterNodes(line,cue);status('海报动画已更新，请保存方案');
   };wrapper.append(select);card.append(wrapper);
  }host.append(card);
 });
}
