/* Official cloud client: website login and API origin are deliberately separate. */
var FoveaCloud = (() => {
  const api = 'https://lucazhou-suno2mv-api.hf.space';
  const web = 'https://mv.fovea.si';
  const active = new Map();
  const official = value => {try{return [api, web].includes(new URL(value).origin);}catch{return false;}};
  async function acceptToken(token,expectedUid){
    const response = await fetch(api+'/api/auth/me',{headers:{Authorization:'Bearer '+token},signal:AbortSignal.timeout(15000)});
    const user = await readServerResponse(response);
    if (!user.id || (expectedUid && user.id !== expectedUid)) throw new Error('The website account changed. Switch back to the account that created this job.');
    await chrome.storage.local.set({authToken:token,authUserId:user.id,authServer:api,cloudDisconnected:false,
      authUserName:user.display_name||user.email||user.id});
    return {userId:user.id,name:user.display_name||user.email||user.id};
  }
  async function sync(expectedUid) {
    if (typeof chrome !== "undefined" && chrome.cookies) {
      try {
        const cookie = await chrome.cookies.get({ url: web, name: "m2v_token" });
        if (cookie && cookie.value) {
          const val = decodeURIComponent(cookie.value);
          return await acceptToken(val, expectedUid);
        }
      } catch (_) {}
    }
    const tabs = (await chrome.tabs.query({url:web+'/*'})).filter(tab=>tab.url&&new URL(tab.url).origin===web);
    if (!tabs.length) throw new Error('Open mv.fovea.si and sign in, then click Sync website account.');
    const results = await chrome.scripting.executeScript({target:{tabId:tabs[0].id},world:'MAIN',
      func:async () => {
        if (!window.m2vAuth) return (typeof localStorage !== "undefined" ? localStorage.getItem("m2v_token") : null) || null;
        await window.m2vAuth.ready;
        return window.m2vAuth.getIdToken(true);
      }});
    const token = results[0]?.result;
    if (!token) throw new Error('Sign in at mv.fovea.si first. Refresh that page if needed.');
    return acceptToken(token,expectedUid);
  }
  async function token(owner) {
    let state = await chrome.storage.local.get(['authToken','authServer','authUserId','cloudDisconnected']);
    if(state.cloudDisconnected)throw new Error('Disconnected. Click Sync website account to reconnect.');
    if (!state.authToken || state.authServer !== api) {await sync(owner);state=await chrome.storage.local.get(['authToken','authUserId']);}
    if (owner && state.authUserId !== owner) throw new Error('This job belongs to another account. Sync the original account to resume.');
    return {value:state.authToken,uid:state.authUserId};
  }
  async function request(path,options={},owner) {
    if (!path.startsWith('/api/') || path.includes('://')) throw new Error('Invalid cloud API path');
    let auth = await token(owner);
    let response = await fetch(api+path,{...options,headers:{...options.headers,Authorization:'Bearer '+auth.value},signal:AbortSignal.timeout(25000)});
    if(response.status===401){await sync(owner||auth.uid);auth=await token(owner||auth.uid);
      response=await fetch(api+path,{...options,headers:{...options.headers,Authorization:'Bearer '+auth.value},signal:AbortSignal.timeout(25000)});}
    if([429,502,503,504].includes(response.status))throw Object.assign(new Error('Connection interrupted. Resume this job; no duplicate generation is needed.'),{temporary:true});
    return readServerResponse(response);
  }
  const post=(path,body,owner)=>request(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)},owner);
  async function download(path,filename,owner,tabId,taskId,kind='MP4') {
    if (!/^\/api\/(?:editor\/jobs\/[a-f0-9]+\/video|suno\/download_mp3\?)/.test(path)) throw new Error('Invalid private download URL');
    const user=await request('/api/auth/me',{},owner);
    if(user.id!==owner)throw new Error('Account mismatch. Sync the original account.');
    const auth = await token(owner);
    const id = await chrome.downloads.download({url:api+path,filename,saveAs:false,conflictAction:'uniquify',
      headers:[{name:'Authorization',value:'Bearer '+auth.value}]});
    await trackDownload(id,filename,kind,tabId,taskId);
    await changeRecords('downloads',records=>records.map(r=>r.id===id?{...r,backend:api,apiPath:path,ownerUid:owner}:r));
    if(taskId)await changeRecords('videoJobs',records=>records.map(r=>r.kind==='cloud'&&r.taskId===taskId&&r.ownerUid===owner?
      {...r,downloadId:id,status:['downloaded','download_failed'].includes(r.status)?r.status:'downloading'}:r));
    return {status:'ok',downloadId:id,filename};
  }
  async function step(job,onProgress,once) {
    const deadline=Date.now()+20*60*1000;
    for(;;){
      await token(job.ownerUid);
      if(job.downloadId!==undefined){const [item]=await chrome.downloads.search({id:job.downloadId});
        if(item&&['complete','in_progress'].includes(item.state)&&item.exists!==false)return {status:'ok',downloadId:item.id};}
      try {
        if(!job.songTaskId){
          const result=await post('/api/tasks/from-suno',{suno_url:job.songUrl,language:'auto',ass_only:true},job.ownerUid);
          job.songTaskId=result.task_id;job.status='pending';await saveJob(job);
        }
        if(!job.exportId){
          const task=await request('/api/tasks/'+encodeURIComponent(job.songTaskId),{},job.ownerUid);
          if(task.status==='failed')throw new Error(task.error_message||'Song alignment failed');
          if(task.status!=='completed'){
            job.status='running';job.progress=Number(task.progress||0)*.65;
            await saveJob(job);onProgress({...job,task_id:job.exportId||job.songTaskId||job.requestId,message:'Importing and aligning your song…'});
            if(once)return {status:'pending'};
          }else{
            if(chrome?.offscreen && !job.fallbackToCloud){
              try {
                const exported=await exportWebCodecs(job,onProgress);
                if(exported)return exported;
              }catch(wcErr){
                console.warn('[FoveaCloud] WebCodecs export failed, falling back to cloud FFmpeg:',wcErr);
                job.fallbackToCloud=true;await saveJob(job);
              }
            }
            const result=await post('/api/editor/tasks/'+encodeURIComponent(job.songTaskId)+'/lyric-video',{
              request_id:job.requestId,section_name:job.section||'',aspect_ratio:'9:16',template:'apple',theme:'apple_white',
              background_mode:'blurred_ambient',...(job.duration>0?{duration_limit:job.duration}:{})},job.ownerUid);
            job.exportId=result.task_id;job.taskId=result.task_id;job.status='running';await saveJob(job);
          }
        }
        if(job.exportId){
          const result=await request('/api/editor/jobs/'+encodeURIComponent(job.exportId),{},job.ownerUid);
          if(['failed','interrupted'].includes(result.status))throw new Error(result.error||'Rendering interrupted. Create a new video.');
          job.status=result.status;job.progress=65+Number(result.progress||0)*.35;await saveJob(job);
          onProgress({...job,task_id:job.exportId||job.songTaskId||job.requestId,message:result.status==='completed'?'Video ready. Starting download…':'Rendering your video…'});
          if(result.status==='completed'){
            const suffix={chorus:'_Chorus',verse1:'_Verse1',intro:'_Intro'}[job.section]||'';
            const filename=(job.title||'lyric-video').replace(/[\\/:*?"<>|\x00-\x1f]/g,'_').slice(0,110)+suffix+'_9x16.mp4';
            const downloaded=await download('/api/editor/jobs/'+job.exportId+'/video',filename,job.ownerUid,job.tabId,job.taskId);
            job.downloadId=downloaded.downloadId;return downloaded;
          }
          if(once)return {status:'pending'};
        }
      }catch(error){
        if(!error.temporary && !/fetch|network|timed? ?out|aborted/i.test(error.message))throw error;
        onProgress({...job,task_id:job.exportId||job.songTaskId||job.requestId,message:'Connection interrupted. Reconnecting; the existing job is kept.'});
        if(once)return {status:'pending'};
      }
      if(Date.now()>deadline)throw Object.assign(new Error('Stopped checking after 20 minutes. Resume the saved job; it was not cancelled.'),{temporary:true});
      await new Promise(resolve=>setTimeout(resolve,2000));
    }
  }
  function finish(job,onProgress=()=>{},once=false){
    const key=job.requestId;
    if(active.has(key))return active.get(key);
    const work=step(job,onProgress,once).catch(async error=>{
      if(!error.temporary && !/account|sign in|Sync/i.test(error.message))await saveJob({...job,status:/interrupted/i.test(error.message)?'interrupted':'failed',error:error.message});
      throw error;
    }).finally(()=>active.delete(key));active.set(key,work);return work;
  }
  async function start(track,section,duration,onProgress,tabId){
    if(!/^[A-Za-z0-9_-]{1,128}$/.test(track?.songId||''))throw new Error('Open the song page in Suno first.');
    if(track.is_public===false)throw new Error('Song is not published. Publish it in Suno first.');
    const auth=await token();
    // Check server identity even for a manually supplied token before binding a new job.
    const user=await request('/api/auth/me',{},auth.uid);
    if(user.id!==auth.uid)throw new Error('Account mismatch. Sync your website account again.');
    const stored=await chrome.storage.local.get('videoJobs');
    let job=(stored.videoJobs||[]).find(j=>j.kind==='cloud'&&j.ownerUid===auth.uid&&j.songId===track.songId&&j.section===section&&j.duration===duration&&
      ['submitting','pending','running','completed','downloading','download_failed'].includes(j.status));
    if(!job){const uuid=/^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(track.songId);
      job={kind:'cloud',requestId:crypto.randomUUID(),targetServer:api,ownerUid:auth.uid,title:track.title,songId:track.songId,
        songUrl:'https://suno.com/'+(uuid?'song/':'s/')+track.songId,section,duration,tabId,status:'submitting',track};
      await saveJob(job);}
    const published=await request('/api/suno/publish_status?url='+encodeURIComponent(job.songUrl),{},auth.uid);
    if(published.is_public!==true)throw new Error('Song is not published. Publish it in Suno first.');
    return finish(job,onProgress);
  }
  async function ensureOffscreen() {
    if (!chrome?.offscreen) return false;
    const offscreenUrl = chrome.runtime.getURL('offscreen.html');
    if (chrome.runtime?.getContexts) {
      const contexts = await chrome.runtime.getContexts({
        contextTypes: ['OFFSCREEN_DOCUMENT'],
        documentUrls: [offscreenUrl],
      });
      if (contexts.length > 0) return true;
    } else if (chrome.offscreen?.hasDocument && await chrome.offscreen.hasDocument()) {
      return true;
    }
    try {
      await chrome.offscreen.createDocument({
        url: offscreenUrl,
        reasons: ['BLOBS'],
        justification: 'Hardware-accelerated WebCodecs video encoding',
      });
      return true;
    } catch (err) {
      if (err?.message?.includes('Only a single offscreen document may be created')) return true;
      console.warn('[FoveaCloud] Offscreen document creation failed:', err);
      return false;
    }
  }
  async function exportWebCodecs(job, onProgress=()=>{}) {
    if (!chrome?.offscreen) return null;
    const ok = await ensureOffscreen();
    if (!ok) return null;
    const ping = await chrome.runtime.sendMessage({ target: 'offscreen', action: 'CHECK_WEBCODECS_SUPPORT' })
      .catch(() => null);
    if (!ping?.supported) return null;

    onProgress({ ...job, task_id: job.songTaskId || job.requestId, message: 'Loading song project data…' });
    let project = null;
    try {
      const motionRes = await request('/api/cloud-motion/project?project_id=' + encodeURIComponent(job.songTaskId), {}, job.ownerUid);
      project = motionRes?.project || motionRes;
    } catch (_) {
      project = await request('/api/editor/tasks/' + encodeURIComponent(job.songTaskId) + '/align', {}, job.ownerUid);
    }
    if (!project) throw new Error('Project data could not be loaded');

    const auth = await token(job.ownerUid);
    const audioUrl = api + '/api/editor/tasks/' + encodeURIComponent(job.songTaskId) + '/audio';
    const audioHeaders = { Authorization: 'Bearer ' + auth.value };

    let audioArrayBuffer = null;
    try {
      const audioResp = await fetch(audioUrl, {
        headers: audioHeaders,
        signal: AbortSignal.timeout(35000),
      });
      if (audioResp.ok) {
        audioArrayBuffer = await audioResp.arrayBuffer();
      }
    } catch (fetchErr) {
      console.warn('[FoveaCloud] Pre-fetching audio buffer in worker failed, will try via offscreen URL:', fetchErr);
    }

    onProgress({ ...job, task_id: job.songTaskId || job.requestId, progress: 65, message: 'Encoding lyric video with WebCodecs GPU…' });
    const key = job.requestId;
    const progressHandler = (msg) => {
      if (msg?.action === 'WEBCODECS_PROGRESS' && msg.requestId === key) {
        job.status = 'running';
        job.progress = 65 + Math.round((msg.pct || 0) * 0.35);
        onProgress({
          ...job,
          task_id: job.songTaskId || job.requestId,
          progress: job.progress,
          message: `Hardware GPU encoding frame ${msg.frame}/${msg.totalFrames} (${msg.pct}%)…`,
        });
      }
    };
    if (chrome.runtime?.onMessage?.addListener) {
      chrome.runtime.onMessage.addListener(progressHandler);
    }
    let res;
    try {
      res = await chrome.runtime.sendMessage({
        target: 'offscreen',
        action: 'RENDER_WEBCODECS',
        requestId: job.requestId,
        project,
        audioArrayBuffer,
        audioUrl,
        audioHeaders,
        section: job.section || '',
        duration: job.duration || 0,
        aspect: '9:16',
        visualMode: project.motion_design?.active_mode || 'kinetic',
        title: job.title || project.title || 'lyric-video',
      });
    } finally {
      if (chrome.runtime?.onMessage?.removeListener) {
        chrome.runtime.onMessage.removeListener(progressHandler);
      }
    }

    if (res?.status !== 'ok' || !res?.data?.blobUrl) {
      throw new Error(res?.message || 'WebCodecs video rendering failed');
    }

    const { blobUrl, filename } = res.data;
    onProgress({ ...job, task_id: job.songTaskId || job.requestId, progress: 99, message: 'Video ready. Starting download…' });
    const downloadId = await chrome.downloads.download({
      url: blobUrl,
      filename,
      saveAs: false,
      conflictAction: 'uniquify',
    });

    job.downloadId = downloadId;
    job.taskId = job.songTaskId;
    job.status = 'completed';
    job.progress = 100;
    await saveJob(job);
    await trackDownload(downloadId, filename, 'MP4', job.tabId, job.songTaskId);
    await changeRecords('downloads', records => records.map(r => r.id === downloadId ? { ...r, backend: api, ownerUid: job.ownerUid, localWebCodecs: true } : r));

    post('/api/cloud-motion/unlock?project_id=' + encodeURIComponent(job.songTaskId) + '&accepted_cost=0', {}, job.ownerUid).catch(() => {});
    return { status: 'ok', downloadId, filename };
  }
  return {api,web,official,sync,acceptToken,token,request,download,start,finish,exportWebCodecs};
})();
