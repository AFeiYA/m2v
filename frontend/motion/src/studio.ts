import type {HighlightMode} from './karaoke';
import {localRulePlan,localPalette,preserveHighlight} from './local-design';
import {compileSongLayout,paintSongLayout,paintCoverBackground} from './song-layout';
import {POSTER_FONT} from './poster-layout';
import {checkImportScope} from './import-scope';
import {compileSongPosters,canvasMeasure,paintCompiledPoster,automaticPoster,resolvePaletteColors,pickRandomStackLayout,type CompiledPoster,type DefaultLayoutPreset,type StackLayout} from './poster-layout';
import { RemotionPreview } from './remotion-preview';
import { defaults, normalizeProject, renderSize, buildExportClips, type Project, type Options, type MotionPlan, type ExportClip } from './model';
import {motionJson as api,motionUrl,serviceJson,serviceAudio,cloudService,downloadService} from './service-api';
const $=<T extends HTMLElement>(id:string)=>document.getElementById(id) as T;
const audio=new Audio();
let audioObjectUrl='';
let audioReady=false;
let loadSequence=0;
let project:Project|null=null,plan:MotionPlan|null=null,engine:RemotionPreview|null=null,selected='',currentCue='',dirty=false,jobId='',playing=false;
let identityDirty=false,settingsDirty=false,saving=false;
let ruleSeed:MotionPlan|null=null;
let coverPending:Promise<void>|null=null;
let scrubbing=false,resumeAfterScrub=false;
let posterPreview:CompiledPoster|null=null,clipEnd:number|null=null,clipReviewTime=0,reviewHandover=false;
const options:Options={...defaults,height:720};
const initialSettings=settingsSnapshot();
const status=(text:string)=>{$('status').textContent=text;updateSaveState();};
function download(name:string,data:string,type='application/json'){const url=URL.createObjectURL(new Blob([data],{type})),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function refresh(){updateSaveState();if(!project)return;project.motion_plan=plan||undefined;const {width,height}=renderSize(options),canvas=$<HTMLCanvasElement>('stage');engine?.dispose();canvas.width=width;canvas.height=height;canvas.style.aspectRatio=`${width}/${height}`;$('stage-box').style.aspectRatio=`${width}/${height}`;engine=new RemotionPreview(canvas,project,options,width,height);engine.renderAt(audio.currentTime||0);$('stage-meta').textContent=`Remotion · ${options.aspect} · ${width}×${height}`;}
function listCues(){const select=$<HTMLSelectElement>('cue-select');select.replaceChildren();for(const cue of plan?.cues||[]){const line=project?.lines.find(l=>l.id===cue.line_id),item=document.createElement('option');item.value=cue.line_id;item.textContent=(cue.locked?'🔒 ':'')+(line?.text||cue.line_id);select.append(item);}if(plan?.cues.some(c=>c.line_id===currentCue))select.value=currentCue;else currentCue=plan?.cues[0]?.line_id||'';showCue(false);}
function showCue(seek=true){const cue=plan?.cues.find(c=>c.line_id===currentCue);if(!cue)return;
 const line=project?.lines.find(l=>l.id===currentCue);
 $<HTMLSelectElement>('poster-layout').value=cue.poster?.layout||'hero-stack';$('poster-design-status').textContent=cue.poster?(dirty?'Local preview design · Unsaved':'Saved director poster design'):'Automatic layout. You can import an AI poster design.';
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
 $<HTMLSelectElement>('cue-highlight').value=cue.poster?.highlight||'none';$<HTMLSelectElement>('cue-highlight').disabled=cue.locked;
 $<HTMLSelectElement>('visual-intensity').value=cue.poster?.visual_intensity||'auto';$<HTMLSelectElement>('visual-intensity').disabled=cue.locked;
 $<HTMLSelectElement>('semantic-mode').value=cue.poster?.semantic_mode||'auto';$<HTMLSelectElement>('semantic-mode').disabled=cue.locked;
 $<HTMLSelectElement>('cue-exit').value=cue.poster?.transition_out||'cut';$<HTMLSelectElement>('cue-exit').disabled=cue.locked;
 if(line){renderPosterNodes(line,cue);const size=renderSize(options),c=document.createElement('canvas').getContext('2d')!;
  const p=compileSongPosters(project!,size.width,size.height,canvasMeasure(c)).find(p=>p.line_id===line.id)!;
  $('visual-intensity-status').textContent=cue.poster?.highlight&&cue.poster.highlight!=='none'?'Lyric highlighting keeps the layout stable, disables entrance and beat scaling, and uses existing word timings.':`Intensity: ${{restrained:'restrained',expanded:'expanded',peak:'peak'}[p.visual_intensity]} · Controls text size and entrance strength; timing and safe areas take priority.`;
  $('handover-status').textContent=`Hold after singing: ${(Math.max(0,(p.handover?.visible_end||p.end)-p.end)).toFixed(2)}s · ${p.handover?.mode==='layered-fade'?'Supporting text fades before the primary text':p.handover?.mode==='fade'?'Short fade':'Cut'}. Lyrics and audio timing stay unchanged.`;
 }
 $<HTMLSelectElement>('cue-template').value=cue.template;$<HTMLSelectElement>('cue-layout').value=cue.layout;$<HTMLSelectElement>('cue-palette').value=cue.palette;$<HTMLInputElement>('cue-intensity').value=String(cue.intensity);$<HTMLInputElement>('cue-emphasis').value=cue.emphasis;$<HTMLInputElement>('cue-locked').checked=cue.locked;
 if(seek){clipEnd=null;audio.pause();playing=false;$('play').textContent='▶';const line=project?.lines.find(l=>l.id===currentCue);audio.currentTime=line?Math.min(line.end-.001,line.start+.15):0;engine?.renderAt(audio.currentTime);$<HTMLInputElement>('seek').value=String(audio.currentTime);$('time').textContent=audio.currentTime.toFixed(2)+'s';}}
function updateSaveState(){
 const changed=dirty||identityDirty||settingsDirty;
 const english=(window as any).currentLocale==='en';
 const button=$<HTMLButtonElement>('save-design');button.disabled=!project||!changed||saving;
 button.textContent=saving?(english?'Saving…':'保存中…'):(english?'Save':'保存');
 $('save-state').textContent=changed?(english?'Unsaved preview':'预览有未保存修改'):(english?'Saved':'已保存');
 $('save-state').dataset.dirty=String(changed);
}
function settingsSnapshot(){return {aspect:options.aspect,height:options.height,post:options.post,bloom:options.bloom,shake:options.shake,
 palette:$<HTMLSelectElement>('preset').value,background:$<HTMLSelectElement>('theme-bg').value,layout:$<HTMLSelectElement>('default-layout-preset').value,highlight:$<HTMLSelectElement>('highlight-mode').value||'none'};}
async function savePlan(){
 if(!dirty||!plan||!selected)return;
 const id=selected,sequence=loadSequence,snapshot=JSON.stringify(plan),value=JSON.parse(snapshot);
 const result=await api('plan','PUT',{project_id:id,plan:value,from_llm:false});
 if(selected===id&&sequence===loadSequence&&JSON.stringify(plan)===snapshot){plan=result;dirty=false;}
}
async function saveSettings(){
 if(!settingsDirty||!selected)return;
 const id=selected,sequence=loadSequence,value=settingsSnapshot(),snapshot=JSON.stringify(value);
 await api('settings','PUT',{project_id:id,settings:value});
 if(selected===id&&sequence===loadSequence&&JSON.stringify(settingsSnapshot())===snapshot)settingsDirty=false;
}
async function saveAll(){
 if(!selected||saving)return;
 const id=selected;saving=true;updateSaveState();
 try{
  const results=await Promise.allSettled([savePlan(),saveIdentity(),saveSettings()]);
  const failure=results.find(r=>r.status==='rejected') as PromiseRejectedResult|undefined;
  if(failure)throw failure.reason;
  if(id===selected){showCue(false);status(dirty||identityDirty||settingsDirty?'Submitted version saved. Newer edits remain local.':'Theme, layout, and song details saved.');}
 }finally{saving=false;updateSaveState();}
}
function requireSaved(){if(dirty||identityDirty||settingsDirty)throw new Error('Save your current preview using the top Save button before continuing.');}
async function load(id:string){
 if((dirty||identityDirty||settingsDirty)&&id!==selected&&!window.confirm('Switch songs and discard unsaved preview changes?')){$<HTMLSelectElement>('project-select').value=selected;return;}
 if(!id){loadSequence++;return;}
 const sequence=++loadSequence;
 try{
  if(sequence!==loadSequence)return;
  audio.pause();playing=false;$('play').textContent='▶';status('Loading song and audio…');
  const result=await api('project?project_id='+encodeURIComponent(id));
  if(sequence!==loadSequence)return;
  project=normalizeProject(result.project);plan=result.plan;ruleSeed=result.rule_seed||null;selected=id;dirty=false;identityDirty=false;settingsDirty=false;
  {const v=result.settings||initialSettings;Object.assign(options,{aspect:v.aspect,height:v.height,post:v.post,bloom:v.bloom,shake:v.shake});
   for(const key of ['aspect','resolution','post','bloom','shake']){const node=$<HTMLInputElement>(key);if(key==='post')node.checked=options.post;else node.value=String(key==='resolution'?options.height:options[key as 'aspect'|'bloom'|'shake']);}
   $<HTMLSelectElement>('highlight-mode').value=v.highlight||'none';$<HTMLSelectElement>('preset').value=v.palette;$<HTMLSelectElement>('theme-bg').value=v.background;$<HTMLSelectElement>('default-layout-preset').value=v.layout;
  }
  audioReady=false;audio.src='';audio.currentTime=0;
  showIdentity();showCover();$<HTMLAnchorElement>('rhythm-link').href='/rhythm-studio?project='+encodeURIComponent(id);coverPending=cacheSunoCover(id);
  $('track-name').textContent=project.title;
  $<HTMLInputElement>('seek').max=String(project.duration);$('duration').textContent=project.duration.toFixed(1)+'s';
  refresh();listCues();
  let nextAudioUrl='';
  let audioCached=false;
  if(result.audio_url&&cloudService()){
   const {blob,cached}=await serviceAudio(result.audio_url,id,result.project.audio_cache);
   if(sequence!==loadSequence)return;
   audioCached=cached;
   nextAudioUrl=URL.createObjectURL(blob);
  }
  if(audioObjectUrl)URL.revokeObjectURL(audioObjectUrl);
  audioObjectUrl=nextAudioUrl;audio.src=audioObjectUrl||result.audio_url||'';audio.currentTime=0;audio.load();
  audioReady=Boolean(audioObjectUrl||result.audio_url);
  $('track-name').textContent=project.title||$<HTMLSelectElement>('project-select').selectedOptions[0].text;
  $<HTMLInputElement>('seek').max=String(project.duration);$('duration').textContent=project.duration.toFixed(1)+'s';
  $('analysis-status').textContent=project.analysis.energy_curve.length?`Audio analysis ready · ${project.analysis.beats.length} beats · Estimated ${project.analysis.bpm} BPM`:'No audio analysis yet. Run it in Lyric Editor.';
  refresh();listCues();populateExportMatrix();await loadExports();
  if(sequence===loadSequence)status(result.plan_error||((plan?'Saved director plan loaded':'Choose a style and generate a director plan')+(audioCached?' · Audio loaded from local cache':'')));
 }catch(error){if(sequence===loadSequence)throw error;}
}
function rules(onlyCurrent=false){
 if(!project||!selected)throw new Error('Select a song first.');
 if(onlyCurrent&&!currentCue)throw new Error('Select a lyric line first.');
 const base=plan||ruleSeed;if(!base)throw new Error('Refresh the page to load layout data.');
 plan=localRulePlan(project,base,$<HTMLSelectElement>(onlyCurrent?'cue-palette':'preset').value,$<HTMLSelectElement>(onlyCurrent?'cue-layout-preset':'default-layout-preset').value as DefaultLayoutPreset,
  $<HTMLSelectElement>('theme-bg').value as 'auto'|'light'|'dark',onlyCurrent?currentCue:undefined);
 for(const cue of plan.cues)if(!cue.locked&&(!onlyCurrent||cue.line_id===currentCue)&&cue.poster&&!cue.poster.highlight)cue.poster.highlight=($<HTMLSelectElement>('highlight-mode').value||'none') as HighlightMode;
 dirty=true;settingsDirty=true;refresh();listCues();status('Local layout preview updated. Save when ready.');
}
function previewPalette(){
 if(!project||!selected)return;
 if(!plan){rules();return;}
 plan=localPalette(plan,$<HTMLSelectElement>('preset').value,$<HTMLSelectElement>('theme-bg').value as 'auto'|'light'|'dark');
 dirty=true;settingsDirty=true;refresh();showCue(false);status('Theme updated locally. Save when ready.');
}
$('preset').onchange=action(previewPalette);$('theme-bg').onchange=action(previewPalette);$('default-layout-preset').onchange=action(()=>rules());
function previewHighlight(single=false){
 if(!project||!selected)return;
 if(!plan){rules();return;}
 const mode=$<HTMLSelectElement>(single?'cue-highlight':'highlight-mode').value as HighlightMode;
 for(const cue of plan.cues){if(cue.locked||(single&&cue.line_id!==currentCue))continue;const line=project.lines.find(l=>l.id===cue.line_id);if(!line)continue;cue.poster=cue.poster||automaticPoster(line,cue.palette);cue.poster.highlight=mode;}
 dirty=true;if(!single)settingsDirty=true;refresh();listCues();status('Highlighting updated locally. Save when ready.');
}
$('highlight-mode').onchange=action(()=>previewHighlight());$('cue-highlight').onchange=action(()=>previewHighlight(true));
let cancelExportQueue = false;

function populateExportMatrix() {
  const container = $('matrix-candidates-list');
  if (!container) return;
  container.replaceChildren();
  const isZh = (window as any).currentLocale === 'zh';
  const clips = typeof buildExportClips === 'function' ? buildExportClips(project, isZh ? 'zh' : 'en') : [];

  const headings = [
    isZh ? '片段' : 'Clip',
    isZh ? '9:16 竖屏' : '9:16 Portrait',
    isZh ? '16:9 横屏' : '16:9 Landscape'
  ];
  for (const h of headings) {
    const el = document.createElement('strong');
    el.textContent = h;
    container.append(el);
  }

  clips.forEach(clip => {
    const title = document.createElement('span');
    title.className = 'matrix-clip-title';
    let durationStr = '';
    if (clip.available) {
      if (clip.end_time == null) {
        durationStr = project?.duration ? `${project.duration.toFixed(1)}s` : (isZh ? '全曲' : 'Full track');
      } else {
        durationStr = `${(clip.end_time - clip.start_time).toFixed(1)}s`;
      }
    } else {
      durationStr = isZh ? '未检测到' : 'Not detected';
    }
    title.textContent = `${clip.title} · ${durationStr}`;
    if (clip.available) {
      title.title = `${clip.title} (${clip.start_time.toFixed(1)}s - ${clip.end_time == null ? 'End' : clip.end_time.toFixed(1) + 's'})`;
    }
    container.append(title);

    for (const ratio of ['9:16', '16:9'] as const) {
      const card = document.createElement('label');
      card.className = 'matrix-card';
      const check = document.createElement('input');
      check.type = 'checkbox';
      check.className = 'matrix-clip-check';
      check.dataset.clipId = clip.id;
      check.dataset.ratio = ratio;
      check.checked = clip.id === 'full' && ratio === (options.aspect || '9:16');
      check.disabled = !clip.available;
      check.setAttribute?.('aria-label', `${clip.title} ${ratio}`);
      check.addEventListener('change', () => {
        updateMatrixCount();
        if (check.checked) {
          options.aspect = ratio;
          $<HTMLSelectElement>('aspect').value = ratio;
          settingsDirty = true;
          refresh();
        }
      });
      card.append(check);
      container.append(card);
    }
  });
  updateMatrixCount();
}

function updateMatrixCount() {
  const custom = $<HTMLInputElement>('export-custom-range')?.checked;
  const count = custom ? 1 : (typeof document.querySelectorAll === 'function' ? Array.from(document.querySelectorAll<HTMLInputElement>('.matrix-clip-check')).filter(c => c.checked && !c.disabled).length : 0);
  const isZh = (window as any).currentLocale === 'zh';
  const badge = $('matrix-selected-count');
  if (badge) badge.textContent = `${count} ${isZh ? '已选' : 'selected'}`;
  const btn = $<HTMLButtonElement>('export');
  if (btn && !btn.disabled) {
    btn.textContent = custom ? (isZh ? '导出自定义片段' : 'Export Custom Clip') : (isZh ? `导出所选视频 (${count})` : `Export Selected (${count})`);
  }
}

async function exportVideo() {
  if (!selected || !plan) throw new Error('Generate a director plan first.');
  requireSaved();
  if (coverPending) await coverPending;

  const customRange = Boolean($<HTMLInputElement>('export-custom-range')?.checked);
  const selectedBoxes = customRange ? [] : (typeof document.querySelectorAll === 'function' ? Array.from(document.querySelectorAll<HTMLInputElement>('.matrix-clip-check')).filter(c => c.checked && !c.disabled) : []);
  if (!customRange && !selectedBoxes.length) throw new Error('Please select at least one clip or format from the matrix.');

  const isZh = (window as any).currentLocale === 'zh';
  const clips = typeof buildExportClips === 'function' ? buildExportClips(project, isZh ? 'zh' : 'en') : [];
  type QueueTask = {
    title: string;
    aspect: '16:9' | '9:16';
    start: number;
    length: number | null;
  };
  const tasks: QueueTask[] = customRange ? [{
    title: isZh ? '自定义片段' : 'Custom clip',
    aspect: options.aspect,
    start: Math.max(0, Number($<HTMLInputElement>('clip-start').value || 0)),
    length: Math.max(0.1, Number($<HTMLInputElement>('clip-length').value || 8))
  }] : selectedBoxes.map(box => {
    const clip = clips.find(c => c.id === box.dataset.clipId)!;
    const aspect = (box.dataset.ratio || options.aspect) as '16:9' | '9:16';
    const start = clip.start_time;
    const length = clip.end_time == null ? null : Math.max(0.1, clip.end_time - clip.start_time);
    return { title: clip.title, aspect, start, length };
  });

  const exportBtn = $<HTMLButtonElement>('export');
  const cancelBtn = $<HTMLButtonElement>('cancel');
  const queueBox = $('matrix-queue-box');
  const queueSummary = $('matrix-queue-summary');
  const queueItems = $('matrix-queue-items');
  const downloadLink = $<HTMLAnchorElement>('download');

  exportBtn.disabled = true;
  cancelBtn.hidden = false;
  downloadLink.hidden = true;
  cancelExportQueue = false;

  queueBox.hidden = false;
  queueItems.replaceChildren();

  const itemRows = tasks.map(task => {
    const row = document.createElement('div');
    row.className = 'queue-row';
    const text = document.createElement('span');
    text.textContent = `${task.title} (${task.aspect}): ${isZh ? '排队中…' : 'Queued…'}`;
    row.append(text);
    queueItems.append(row);
    return { task, row, text };
  });

  let completedCount = 0;
  const updateSummary = (runningMsg = '') => {
    queueSummary.textContent = `${completedCount}/${tasks.length} ${isZh ? '完成' : 'completed'}${runningMsg ? ' · ' + runningMsg : ''}`;
  };
  updateSummary();

  try {
    for (let i = 0; i < tasks.length; i++) {
      if (cancelExportQueue) {
        for (let j = i; j < tasks.length; j++) {
          itemRows[j].text.textContent = `${tasks[j].title} (${tasks[j].aspect}): ${isZh ? '已取消' : 'Cancelled'}`;
        }
        break;
      }
      const { task, row, text } = itemRows[i];
      text.textContent = `${task.title} (${task.aspect}): ${isZh ? '准备导出…' : 'Preparing…'}`;
      updateSummary(`${task.title} (${task.aspect})`);

      let submittedJobId = '';
      while (!cancelExportQueue) {
        try {
          const res = await api('render', 'POST', {
            project_id: selected,
            aspect: task.aspect,
            height: options.height,
            bloom: options.bloom,
            shake: options.shake,
            post: options.post,
            start: task.start,
            length: task.length
          });
          submittedJobId = res.id;
          jobId = res.id;
          break;
        } catch (err: any) {
          const msg = err?.message || String(err);
          if (/已有视频正在导出|slots are full|409/i.test(msg)) {
            text.textContent = `${task.title} (${task.aspect}): ${isZh ? '等待通道空闲…' : 'Waiting for render slot…'}`;
            await new Promise(r => setTimeout(r, 1500));
            continue;
          }
          throw err;
        }
      }

      if (cancelExportQueue) break;

      for (;;) {
        if (cancelExportQueue) {
          await api('render/' + submittedJobId + '/cancel', 'POST').catch(() => {});
          text.textContent = `${task.title} (${task.aspect}): ${isZh ? '已取消' : 'Cancelled'}`;
          break;
        }
        const job = await api('render/' + submittedJobId);
        const statusText = job.status === 'running'
          ? (isZh ? `渲染中 ${job.frames}/${job.total} 帧 (${Math.round(job.frames/job.total*100)}%)` : `Rendering ${job.frames}/${job.total} frames (${Math.round(job.frames/job.total*100)}%)`)
          : job.status === 'queued'
          ? (isZh ? '排队等待渲染…' : 'Waiting to render…')
          : job.status === 'done'
          ? (isZh ? '视频已完成' : 'Video complete')
          : job.status === 'cancelled'
          ? (isZh ? '已取消' : 'Cancelled')
          : (isZh ? '渲染失败: ' + job.error : 'Failed: ' + job.error);

        text.textContent = `${task.title} (${task.aspect}): ${statusText}`;
        $('export-status').textContent = `${task.title} (${task.aspect}) · ${statusText}`;

        if (job.status === 'done') {
          completedCount++;
          const dlUrl = motionUrl('render/' + submittedJobId + '/download');
          const dlLink = document.createElement('a');
          dlLink.className = 'dl-link';
          dlLink.textContent = isZh ? '下载 ↓' : 'Download ↓';
          dlLink.href = dlUrl;
          dlLink.onclick = (e) => {
            e.preventDefault();
            void action(() => downloadService(dlUrl))();
          };
          row.append(dlLink);

          if (tasks.length === 1) {
            downloadLink.href = dlUrl;
            downloadLink.onclick = dlLink.onclick;
            downloadLink.hidden = false;
          }
          await loadExports();
          updateSummary();
          break;
        }
        if (['failed', 'cancelled'].includes(job.status)) {
          updateSummary();
          break;
        }
        await new Promise(r => setTimeout(r, 1000));
      }
    }
    updateSummary(isZh ? '所有任务已结束' : 'All jobs finished');
    $('export-status').textContent = `${completedCount}/${tasks.length} ${isZh ? '视频导出完成。' : 'videos completed.'} ${cloudService() ? (isZh ? '可在「我的导出」中集中管理。' : 'Manage them in My Exports.') : ''}`;
    if (cloudService()) $('my-exports').hidden = false;
  } finally {
    exportBtn.disabled = false;
    cancelBtn.hidden = true;
    updateMatrixCount();
  }
}

function action(fn:()=>unknown){return async()=>{try{await fn();}catch(error){status(error instanceof Error?error.message:String(error));console.error(error);}};}
$('generate').onclick=action(()=>rules());$('regenerate-cue').onclick=action(()=>rules(true));$('save-plan').onclick=action(saveAll);$('save-design').onclick=action(saveAll);
async function directorPrompt(single:boolean){
 if(!selected)throw new Error('Select a song first.');if(single&&!currentCue)throw new Error('Generate a plan and select a lyric line first.');requireSaved();
 const result=await api(single?'director/line/input':'director/input','POST',{project_id:selected,style:$<HTMLSelectElement>('preset').value,instruction:$<HTMLTextAreaElement>('director-instruction').value,...(single?{line_id:currentCue}:{})});
 $<HTMLTextAreaElement>('director-prompt').value=result.prompt;$<HTMLSelectElement>('import-scope').value=single?'line':'song';
 download(single?`motion-${currentCue}-prompt.txt`:'motion-director-prompt.txt',result.prompt,'text/plain');
 status(result.warnings?.length?result.warnings.join('；'):single?'Line prompt ready: final poster, entrance, and transition draft':'Song prompt ready: posters and animation drafts');
}
$('director-input').onclick=action(()=>directorPrompt(false));$('line-director-input').onclick=action(()=>directorPrompt(true));
let aiJob='',aiBaseline='',aiBusy=false;
async function loadAIConfig(){try{const config=await api('director/config');$('ai-config-status').textContent=config.configured?`Connected to ${config.model}${config.fallback_model?` · Quota fallback: ${config.fallback_model}`:''} · Sends only lyrics, timing, and audio analysis`:'Gemini is not configured. Set GEMINI_API_KEY on the backend.';for(const id of ['ai-line','ai-song'])$<HTMLButtonElement>(id).disabled=!config.configured;}catch{$('ai-config-status').textContent='Unable to load model settings';}}
async function aiDirector(single:boolean){
 if(aiBusy)return;if(!selected)throw new Error('Select a song first.');if(single&&!currentCue)throw new Error('Generate a base plan and select a lyric line first.');requireSaved();
 aiBusy=true;aiJob='';$('ai-apply').hidden=true;for(const id of ['ai-line','ai-song'])$<HTMLButtonElement>(id).disabled=true;
 const projectId=selected;aiBaseline=JSON.stringify(plan);
 try{
  const request=await api('director/generate','POST',{project_id:projectId,line_id:single?currentCue:null,style:$<HTMLSelectElement>('preset').value,instruction:$<HTMLTextAreaElement>('director-instruction').value});
  aiJob=request.id;
  for(;;){const job=await api('director/jobs/'+aiJob);$('ai-job-status').textContent=({queued:'Waiting for Gemini…',running:'Gemini is designing posters and animation…',validating:'Validating lyrics, hierarchy, and locked lines…',repairing:'Validation failed. Attempting one automatic repair…',ready:'Validated. Apply to preview, then save.',failed:'Generation failed: '+job.error} as Record<string,string>)[job.status]||job.status;
   if(job.fallback_used)$('ai-job-status').textContent+=` · Rate or quota limit reached. Switched to ${job.model}`;
   if(job.status==='failed')throw new Error(job.error);
   if(job.status==='ready'){if(selected!==projectId)throw new Error('Song changed. Return to the original song to regenerate.');$('ai-apply').hidden=false;break;}
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
 }finally{aiBusy=false;for(const id of ['ai-line','ai-song'])$<HTMLButtonElement>(id).disabled=false;}
}
$('ai-line').onclick=action(()=>aiDirector(true));$('ai-song').onclick=action(()=>aiDirector(false));
$('ai-apply').onclick=action(async()=>{if(dirty||JSON.stringify(plan)!==aiBaseline)throw new Error('The local plan changed. Save before requesting a new Gemini plan.');const id=selected,sequence=loadSequence;const result=await api('director/jobs/'+aiJob+'/apply?preview=true','POST');if(selected!==id||sequence!==loadSequence||dirty||JSON.stringify(plan)!==aiBaseline)throw new Error('Preview changed. Apply again; your current edits are preserved.');plan=preserveHighlight(result.plan,plan,($<HTMLSelectElement>('highlight-mode').value||'none') as HighlightMode);dirty=true;$('ai-apply').hidden=true;refresh();listCues();$('ai-job-status').textContent='Gemini plan applied locally. Save to sync.';status('Local preview updated. Save when ready.');});
new MutationObserver(()=>{updateSaveState();populateExportMatrix();}).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
void loadAIConfig();
async function returnedPlan(apply:boolean){
 if(!selected)throw new Error('Select a song first.');if(dirty)throw new Error('Save local edits before validating or applying an AI plan.');
 const id=selected,sequence=loadSequence,baseline=JSON.stringify(plan);
 const data=JSON.parse($<HTMLTextAreaElement>('llm-return').value.trim().replace(/^```(?:json)?\s*/,'').replace(/\s*```$/,''));
 const single=$<HTMLSelectElement>('import-scope').value==='line';
 checkImportScope(data,single?'line':'song');
 const result=await api(single?'director/line/validate':'director/validate','POST',single?{project_id:selected,line_id:currentCue,response:data,style:$<HTMLSelectElement>('preset').value}:{project_id:selected,plan:data,from_llm:true});
 if(selected!==id||sequence!==loadSequence||JSON.stringify(plan)!==baseline)throw new Error('Preview changed during validation. Validate again; edits are preserved.');
 $('director-validation').textContent=single?`Validated · Full line preserved · ${result.compiled_groups.length} groups:`+result.compiled_groups.map((group:{text:string;start:number;end:number})=>`${group.text} ${group.start.toFixed(3)}–${group.end.toFixed(3)}s`).join('；'):'Song plan validated';
 if(apply){plan=result.plan;dirty=true;refresh();listCues();status(single?'Line plan applied. Other lines are unchanged.':'Song plan applied locally. Please save.');}
 else status('Validated. Review the plan, then apply it to the preview.');
 const designPlan=result.plan;
 if(designPlan?.cues?.some((cue:{poster?:unknown})=>cue.poster)){status(apply?'Poster preview updated. Save before exporting.':'Poster plan validated. Apply to preview the layout and animation.');}
}
$('validate-plan').onclick=action(()=>returnedPlan(false));$('import-plan').onclick=action(()=>returnedPlan(true));
$('download-plan').onclick=action(()=>{if(!plan)throw new Error('No plan yet.');download('motion-plan.json',JSON.stringify(plan,null,2));});
$<HTMLSelectElement>('project-select').onchange=action(()=>load($<HTMLSelectElement>('project-select').value));$<HTMLSelectElement>('cue-select').onchange=()=>{currentCue=$<HTMLSelectElement>('cue-select').value;showCue();};
for(const id of ['cue-template','cue-layout','cue-palette','cue-intensity','cue-emphasis','cue-locked'])$(id).addEventListener('input',()=>{const cue=plan?.cues.find(c=>c.line_id===currentCue);if(!cue)return;cue.template=$<HTMLSelectElement>('cue-template').value as typeof cue.template;cue.layout=$<HTMLSelectElement>('cue-layout').value as typeof cue.layout;cue.palette=$<HTMLSelectElement>('cue-palette').value as typeof cue.palette;cue.intensity=Number($<HTMLInputElement>('cue-intensity').value);cue.emphasis=$<HTMLInputElement>('cue-emphasis').value;cue.locked=$<HTMLInputElement>('cue-locked').checked;dirty=true;refresh();if(id==='cue-locked')showCue(false);status('Preview updated · Unsaved changes');});
for(const id of ['aspect','resolution','post','bloom','shake'])$(id).addEventListener('input',()=>{options.aspect=$<HTMLSelectElement>('aspect').value as Options['aspect'];options.height=Number($<HTMLSelectElement>('resolution').value) as 360|720;options.post=$<HTMLInputElement>('post').checked;options.bloom=Number($<HTMLInputElement>('bloom').value);options.shake=Number($<HTMLInputElement>('shake').value);settingsDirty=true;refresh();status('Format and display settings updated locally. Save to sync.');});
$('play').onclick=action(async()=>{if(!project)return;if(!audioReady)throw new Error('Audio is loading. You can preview posters while waiting.');clipEnd=null;if(playing){audio.pause();playing=false;$('play').textContent='▶';}else{await audio.play();playing=true;$('play').textContent='Ⅱ';}});const seek=$<HTMLInputElement>('seek');
function beginScrub(){if(scrubbing)return;scrubbing=true;resumeAfterScrub=playing;audio.pause();playing=false;$('play').textContent='▶';clipEnd=null;}
async function finishScrub(){if(!scrubbing)return;scrubbing=false;const resume=resumeAfterScrub;resumeAfterScrub=false;if(resume){await audio.play();playing=true;$('play').textContent='Ⅱ';}}
seek.onpointerdown=beginScrub;
seek.oninput=()=>{beginScrub();const t=Number(seek.value);audio.currentTime=t;engine?.renderAt(t);$('time').textContent=t.toFixed(2)+'s';};
seek.onchange=action(finishScrub);
window.addEventListener('pointerup',action(finishScrub));
window.addEventListener('pointercancel',()=>{resumeAfterScrub=false;void finishScrub();});
$('export').onclick=action(exportVideo);
$('cancel').onclick=action(async()=>{
  cancelExportQueue=true;
  if(jobId)await api('render/'+jobId+'/cancel','POST').catch(()=>{});
});
$('export-custom-range')?.addEventListener('change',updateMatrixCount);
$('clip-start')?.addEventListener('input',updateMatrixCount);
$('clip-length')?.addEventListener('input',updateMatrixCount);
function tick(){if(engine&&playing){if(clipEnd!==null&&audio.currentTime>=clipEnd){audio.pause();audio.currentTime=clipReviewTime;clipEnd=null;playing=false;$('play').textContent='▶';status(reviewHandover?'Transition preview complete':'Line playback complete. Showing the final poster.');}engine.renderAt(audio.currentTime);$<HTMLInputElement>('seek').value=String(audio.currentTime);$('time').textContent=audio.currentTime.toFixed(2)+'s';if(audio.ended){playing=false;$('play').textContent='▶';}}requestAnimationFrame(tick);}requestAnimationFrame(tick);
audio.addEventListener('seeked',()=>{if(scrubbing)return;engine?.renderAt(audio.currentTime);$<HTMLInputElement>('seek').value=String(audio.currentTime);$('time').textContent=audio.currentTime.toFixed(2)+'s';});
window.addEventListener('beforeunload',event=>{if(dirty||identityDirty||settingsDirty){event.preventDefault();event.returnValue='';}});
(async()=>{try{
 const select=$<HTMLSelectElement>('project-select');
 const rows=cloudService()?(await serviceJson('/api/songs?view=all&page_size=50')).songs.filter((s:any)=>s.current_task_id).map((s:any)=>({id:s.current_task_id,name:s.title})):await api('projects');
 for(const row of rows){const item=document.createElement('option');item.value=row.id;item.textContent=row.name;select.append(item);}
 if(cloudService())window.m2vSongPicker?.mount(select,serviceJson,async id=>{await load(id);return selected===id;});
 const params=new URLSearchParams(location.search),wanted=params.get('project')||params.get('song');
 const chosen=rows.find((row:{id:string;name:string})=>row.id===wanted||row.name===wanted)||(rows.length===1?rows[0]:null);
 if(chosen){select.value=chosen.id;await load(chosen.id);}else if(cloudService()&&wanted){await load(wanted);}
}catch(error){status(String(error));}})();

async function loadExports(){
  const id=selected,sequence=loadSequence;
  const records=await api('exports?project_id='+encodeURIComponent(id));
  if(id!==selected||sequence!==loadSequence)return;
  const list=$('export-history');list.replaceChildren();
  for(const job of records){
    if(job.status!=='done')continue;
    const link=document.createElement('a');link.href=motionUrl('render/'+job.id+'/download');link.onclick=event=>{event.preventDefault();void action(()=>downloadService(motionUrl('render/'+job.id+'/download')))();};link.textContent=`${job.width?job.width+"×"+job.height+" · ":""}${(job.total/30).toFixed(1)}s · ${new Date(job.created_at*1000).toLocaleString()}`;link.download='motion-studio.mp4';link.style.display='block';list.append(link);
  }
}

$('focus-preview').onclick=()=>{const focused=document.body.classList.toggle('preview-focus');$('focus-preview').textContent=focused?'Show settings':'Focus preview';};


$('poster-sample').onclick=action(async()=>{
 const line=project?.lines.find(l=>l.id===currentCue);if(!line)throw new Error('Select a lyric line first.');
 audio.pause();clipEnd=null;playing=false;$('play').textContent='▶';await document.fonts.ready;
 const canvas=$<HTMLCanvasElement>('poster-canvas'),size=renderSize(options);canvas.width=size.width;canvas.height=size.height;canvas.style.aspectRatio=`${size.width}/${size.height}`;
 const c=canvas.getContext('2d')!;posterPreview=compileSongPosters(project!,size.width,size.height,canvasMeasure(c)).find(p=>p.line_id===currentCue)!;paintCompiledPoster(c,posterPreview);
 if(project?.song_cover?.data_url){const image=new Image();image.src=project.song_cover.data_url;await image.decode();c.fillStyle=posterPreview.background;c.fillRect(0,0,size.width,size.height);paintCoverBackground(c,project,image,size.width,size.height);paintCompiledPoster(c,posterPreview,undefined,0,false);}
 paintSongLayout(c,compileSongLayout(project!,size.width,size.height,canvasMeasure(c)),line.start,posterPreview.background,posterPreview.accent,POSTER_FONT);
 $('poster-title').textContent='Current line · Final poster';$('poster-lyric').textContent=line.text;
 const hold=Math.max(0,(posterPreview.handover?.exit_start??line.end)-Math.max(...posterPreview.nodes.map(n=>n.settled)));
 $('poster-description').textContent=`${posterPreview.source==='director'?'Director design':'Automatic layout'} · ${options.aspect} · ${posterPreview.nodes.length} text blocks · Final hold: ${hold.toFixed(2)}s. Preview and MP4 use the same layout.`;
 $<HTMLDialogElement>('poster-dialog').showModal();
});
$('poster-close').onclick=()=>$<HTMLDialogElement>('poster-dialog').close();
$('poster-json').onclick=()=>{if(posterPreview)download(`${posterPreview.line_id}-poster-layout.json`,JSON.stringify(posterPreview,null,2));};
$('poster-png').onclick=action(()=>{
 $<HTMLCanvasElement>('poster-canvas').toBlob(blob=>{
  if(!blob){status('Poster export failed');return;}
  const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=(posterPreview?.line_id||'lyric')+'-poster.png';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 },'image/png');
});
$('poster-layout').onchange=action(()=>{
 const cue=plan?.cues.find(c=>c.line_id===currentCue),line=project?.lines.find(l=>l.id===currentCue);if(!cue||!line)return;
 if(cue.locked)throw new Error('Unlock this line before editing.');
 cue.poster=cue.poster||automaticPoster(line,cue.palette);cue.poster.layout=$<HTMLSelectElement>('poster-layout').value as typeof cue.poster.layout;
 dirty=true;refresh();showCue(false);status('Poster layout updated. Save your plan.');
});
if($('random-layout-cue')){
 $('random-layout-cue').onclick=action(()=>{
  const cue=plan?.cues.find(c=>c.line_id===currentCue),line=project?.lines.find(l=>l.id===currentCue);if(!cue||!line)return;
  if(cue.locked)throw new Error('Unlock this line before editing.');
  cue.poster=cue.poster||automaticPoster(line,cue.palette);
  const currentLayout=(cue.poster.layout as StackLayout)||'hero-stack';
  const nextLayout=pickRandomStackLayout(currentLayout);
  cue.poster.layout=nextLayout;
  $<HTMLSelectElement>('poster-layout').value=nextLayout;
  dirty=true;refresh();showCue(false);
  const names:Record<string,string>={'hero-stack':'Left','center-stack':'Center','right-stack':'Right','staggered':'Staggered'};
  status(`Alignment: ${names[nextLayout]||nextLayout}. Save your plan.`);
 });
}
if($('apply-layout-preset')){
 $('apply-layout-preset').onclick=action(async()=>{
  const cue=plan?.cues.find(c=>c.line_id===currentCue),line=project?.lines.find(l=>l.id===currentCue);
  if(!cue||!line)return;
  if(cue.locked)throw new Error('Unlock this line before editing.');
  const preset=($<HTMLSelectElement>('cue-layout-preset')?.value as DefaultLayoutPreset)||'smart';
  const bgTone=($<HTMLSelectElement>('theme-bg')?.value as 'auto'|'light'|'dark')||'auto';
  const highlight=cue.poster?.highlight||($<HTMLSelectElement>('highlight-mode').value as HighlightMode)||'none';
  cue.poster=automaticPoster(line,cue.palette,preset,bgTone);cue.poster.highlight=highlight;
  dirty=true;refresh();showCue(false);status(`Applied layout preset: ${preset}. Save your plan.`);
 });
}
if($('apply-palette')){
 $('apply-palette').onclick=action(async()=>{
  const cue=plan?.cues.find(c=>c.line_id===currentCue),line=project?.lines.find(l=>l.id===currentCue);
  if(!cue||!line)return;
  if(cue.locked)throw new Error('Unlock this line before editing.');
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
  dirty=true;refresh();showCue(false);status(`Applied palette: ${palette}. Save your plan.`);
 });
}
async function playCue(handover=false){
 if(!audioReady)throw new Error('Audio is loading. Please wait before playing.');
 const line=project?.lines.find(l=>l.id===currentCue);if(!line)throw new Error('Select a lyric line first.');
 $<HTMLDialogElement>('poster-dialog').close();const size=renderSize(options),context=document.createElement('canvas').getContext('2d')!;
 const compiled=compileSongPosters(project!,size.width,size.height,canvasMeasure(context)).find(p=>p.line_id===currentCue)!;
 clipReviewTime=Math.max(line.start,Math.min(line.end-.001,Math.max(...compiled.nodes.map(n=>n.settled),line.end-.16)));
 reviewHandover=handover;clipEnd=handover?Math.min(project!.duration,(compiled.handover?.next_start??compiled.handover?.visible_end??line.end)+.7):line.end;
 if(handover)clipReviewTime=Math.max(line.start,clipEnd-.001);
 audio.currentTime=line.start;await audio.play();playing=true;$('play').textContent='Ⅱ';
}
$('play-cue').onclick=action(()=>playCue());$('play-handover').onclick=action(()=>playCue(true));
$('cue-exit').onchange=()=>{const cue=plan?.cues.find(c=>c.line_id===currentCue),line=project?.lines.find(l=>l.id===currentCue);if(!cue||!line||cue.locked)return;cue.poster=cue.poster||automaticPoster(line,cue.palette);cue.poster.transition_out=$<HTMLSelectElement>('cue-exit').value as 'fade'|'cut';dirty=true;refresh();showCue(false);status('Transition updated. Save your plan.');};

$('visual-intensity').onchange=()=>{const cue=plan?.cues.find(c=>c.line_id===currentCue),line=project?.lines.find(l=>l.id===currentCue);if(!cue||!line||cue.locked)return;cue.poster=cue.poster||automaticPoster(line,cue.palette);cue.poster.visual_intensity=$<HTMLSelectElement>('visual-intensity').value as NonNullable<typeof cue.poster.visual_intensity>;dirty=true;refresh();showCue(false);status('Visual intensity updated. Save your plan.');};
$('semantic-mode').onchange=()=>{const cue=plan?.cues.find(c=>c.line_id===currentCue),line=project?.lines.find(l=>l.id===currentCue);if(!cue||!line||cue.locked)return;cue.poster=cue.poster||automaticPoster(line,cue.palette);cue.poster.semantic_mode=$<HTMLSelectElement>('semantic-mode').value as 'auto'|'off';dirty=true;refresh();showCue(false);status('Semantic mode updated. Save your plan.');};

function renderPosterNodes(line:import('./model').Line,cue:import('./model').CuePlan){
 const host=$('poster-node-editor');host.replaceChildren();const direction=cue.poster||automaticPoster(line,cue.palette);
 const relations=document.createElement('div');relations.setAttribute('aria-label','Lyric semantic relationships');
 const names={guidance:'Guidance',contrast:'Contrast',negation:'Negation',repetition:'Repetition',spatial:'Spatial'};
 if(direction.relations?.length){for(const relation of direction.relations){const item=document.createElement('p');item.textContent=`${names[relation.kind]} · ${relation.node_indices.map(i=>direction.nodes[i]?.text||'Invalid node').join(' → ')}：${relation.intent}`;relations.append(item);}}
 else relations.textContent='No semantic relationships yet. Generate them with the latest AI prompt.';
 const size=renderSize(options),context=document.createElement('canvas').getContext('2d')!;
 const compiled=compileSongPosters(project!,size.width,size.height,canvasMeasure(context)).find(p=>p.line_id===line.id)!;
 for(const applied of compiled.semantic_arrangement){const item=document.createElement('p');item.textContent=`${names[applied.kind]} · ${applied.status==='applied'?'Arranged':applied.status==='disabled'?'Disabled':'Limited support'}：${applied.effects.join('；')}`;relations.append(item);}
 const help=document.createElement('small');help.textContent='Automatic mode adjusts these source settings. Turn it off for manual control. Vocal timing, one primary node, and fast-vocal limits take priority.';relations.append(help);host.append(relations);

 direction.nodes.forEach((node,i)=>{
  const card=document.createElement('div');card.style.cssText='padding:12px 0;border-bottom:1px solid #263530';
  const title=document.createElement('strong');title.textContent=node.text;title.style.display='block';card.append(title);const actual=document.createElement('small');const motionNames={none:'Instant',fade:'Fade','slide-up':'Slide up','slide-left':'Slide left','scale-in':'Scale in'};actual.textContent='Actual entrance: '+motionNames[compiled.nodes[i].entrance];card.append(actual);
  const fields:[string,string,[string,string][]][]=[['role','Hierarchy',[['primary','Primary'],['secondary','Secondary'],['support','Support']]],['entrance','Entrance',[['none','Instant'],['fade','Fade'],['slide-up','Slide up'],['slide-left','Slide left'],['scale-in','Scale in']]],['beat_reaction','Beat reaction',[['none','None'],['pulse','Primary pulse']]]];
  for(const [key,label,choices] of fields){const wrapper=document.createElement('label');wrapper.textContent=label;const select=document.createElement('select');select.setAttribute('aria-label',node.text+' '+label);
   for(const [value,text] of choices){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}
   select.value=String((node as any)[key]||'none');select.disabled=cue.locked||(!!direction.highlight&&direction.highlight!=='none'&&key!=='role');
   select.onchange=()=>{cue.poster=cue.poster||automaticPoster(line,cue.palette);const target=cue.poster.nodes[i];
    if(key==='role'&&select.value==='primary'){cue.poster.nodes.forEach(n=>{if(n.role==='primary'){n.role='secondary';n.beat_reaction='none';}});}
    if(key==='role'&&select.value!=='primary'&&target.role==='primary'){status('Set another text block as primary first.');select.value='primary';return;}
    if(key==='beat_reaction'&&select.value==='pulse'&&target.role!=='primary'){status('Beat pulse is available only for the primary node.');select.value='none';return;}
    (target as any)[key]=select.value;dirty=true;refresh();renderPosterNodes(line,cue);status('Poster animation updated. Save your plan.');
   };wrapper.append(select);card.append(wrapper);
  }host.append(card);
 });
}

function showIdentity(){const v=project?.song_identity;if(!v)return;
 $<HTMLInputElement>('song-title').value=v.title;$<HTMLInputElement>('song-artist').value=v.artist;$<HTMLSelectElement>('song-style').value=v.style;$<HTMLSelectElement>('song-theme').value=v.visual_theme||'director';
 $<HTMLSelectElement>('cover-mode').value=v.cover_mode||'background';$<HTMLInputElement>('cover-x').value=String(v.cover_x??50);$<HTMLInputElement>('cover-y').value=String(v.cover_y??50);$<HTMLInputElement>('cover-zoom').value=String(v.cover_zoom??1);
 for(const [id,key] of [['intro','show_intro'],['signature','show_signature'],['section','show_section'],['outro','show_outro']] as const)$<HTMLInputElement>('song-'+id).checked=v[key];
 $('identity-source').textContent=v.source==='suno-cache'?`Suno source: ${v.source_title||v.title} · ${v.source_artist||'Artist unavailable'}. Edit freely; Reset restores the original credits.`:'Existing project. Suno artist details are unavailable; enter them manually.';
}
function editIdentity(){if(!project?.song_identity)return;
 Object.assign(project.song_identity,{visual_theme:$<HTMLSelectElement>('song-theme').value,cover_mode:$<HTMLSelectElement>('cover-mode').value,cover_x:Number($<HTMLInputElement>('cover-x').value),cover_y:Number($<HTMLInputElement>('cover-y').value),cover_zoom:Number($<HTMLInputElement>('cover-zoom').value),title:$<HTMLInputElement>('song-title').value.trim(),artist:$<HTMLInputElement>('song-artist').value.trim(),style:$<HTMLSelectElement>('song-style').value,show_intro:$<HTMLInputElement>('song-intro').checked,show_signature:$<HTMLInputElement>('song-signature').checked,show_section:$<HTMLInputElement>('song-section').checked,show_outro:$<HTMLInputElement>('song-outro').checked});
 project.title=project.song_identity.title;project.artist=project.song_identity.artist;identityDirty=true;$('track-name').textContent=project.title;refresh();status('Song layout preview updated. Save before exporting.');
}
async function saveIdentity(){
 if(!identityDirty||!project?.song_identity||!selected)return;if(!project.song_identity.title.trim())throw new Error('Enter a song title.');
 const id=selected,sequence=loadSequence,snapshot=JSON.stringify(project.song_identity);
 const {source,source_title,source_artist,...identity}=project.song_identity;
 const result=await api('identity','PUT',{project_id:id,identity});
 if(selected===id&&sequence===loadSequence&&JSON.stringify(project?.song_identity)===snapshot){project!.song_identity=result.identity;identityDirty=false;showIdentity();}
}
$('source-refresh-panel').hidden=!cloudService();
async function refreshSourceInfo(){
 if(!selected||!project)throw new Error('Select a song first.');
 const id=selected,sequence=loadSequence,button=$<HTMLButtonElement>('refresh-source');button.disabled=true;status('Loading song details from Suno…');
 try{
  const result=await api('source/refresh','POST',{project_id:id});if(selected!==id||sequence!==loadSequence)return;
  project.song_identity=identityDirty&&project.song_identity?{...project.song_identity,source_title:result.identity.source_title,source_artist:result.identity.source_artist,source:result.identity.source}:result.identity;
  project.song_cover=result.cover;project.title=project.song_identity!.title;project.artist=project.song_identity!.artist;
  if(Array.isArray(result.sections)){
   project.sections=result.sections;
   for(const line of project.lines){const section=project.sections?.find(s=>s.start<=line.start&&line.start<s.end);if(section)line.section=section.name;}
  }
  showIdentity();showCover();refresh();$('track-name').textContent=project.title;
  status(result.warning||'Song details updated. Custom edits, alignment, and credits are unchanged.');
 }finally{button.disabled=false;}
}
$('refresh-source').onclick=action(refreshSourceInfo);
for(const id of ['song-title','song-artist','song-theme','song-style','song-intro','song-signature','song-section','song-outro','cover-mode','cover-x','cover-y','cover-zoom'])$(id).onchange=editIdentity;
$('save-identity').onclick=action(saveAll);
$('reset-identity').onclick=()=>{const v=project?.song_identity;if(!v)return;$<HTMLInputElement>('song-title').value=v.source_title||v.title;$<HTMLInputElement>('song-artist').value=v.source_artist||'';editIdentity();};

function showCover(){const image=$<HTMLImageElement>('song-cover-preview');image.hidden=!project?.song_cover?.data_url;image.src=project?.song_cover?.data_url||'';$('cover-status').textContent=project?.song_cover?.data_url?(project.song_cover.source==='custom'?'Using your uploaded cover':'Using cached Suno artwork'):'No cover. Upload an image or continue with typography only.';}
async function cacheSunoCover(id:string,force=false){
 if(!project||(!force&&(project.song_cover?.data_url||!project.song_cover?.source_url)))return;
 const sequence=loadSequence;
 $('cover-status').textContent='Caching Suno artwork…';
 try{if(force&&cloudService()&&!project.song_cover?.source_url){await refreshSourceInfo();if(selected!==id||sequence!==loadSequence)return;}const result=await api('cover/suno','POST',{project_id:id,restore:force});if(selected!==id||sequence!==loadSequence)return;project.song_cover=result.cover;showCover();refresh();}
 catch(error){if(selected===id&&sequence===loadSequence)$('cover-status').textContent=String(error)+' · You can upload an image instead';}
}
$('restore-cover').onclick=action(()=>cacheSunoCover(selected,true));
$<HTMLInputElement>('cover-file').onchange=action(async()=>{
 const file=$<HTMLInputElement>('cover-file').files?.[0];if(!file)return;if(!selected)throw new Error('Select a song first.');
 const id=selected,body=new FormData();body.append('project_id',id);body.append('file',file);
 const result=await serviceJson(motionUrl('cover'),{method:'POST',body});
 if(selected===id&&project){project.song_cover=result.cover;showCover();refresh();status('Cover saved. Preview and export are updated.');}
 $<HTMLInputElement>('cover-file').value='';
});

$('my-exports').hidden=!cloudService();
