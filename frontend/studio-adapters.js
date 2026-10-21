/** One owner for studio navigation, readiness and draft protection. */
(() => {
  let sequence = 0;
  const origin = () => typeof window !== 'undefined' ? window.location?.origin : undefined;
  class StudioAdapter {
    constructor(name, frameId, path) {
      this.name=name;this.frameId=frameId;this.path=path;this.container=null;
      this.currentSongId=null;this.requestId='';this.phase='idle';this.dirty=false;
      this.staleSongs=new Set();this.timer=null;
      if(typeof window!=='undefined')window.addEventListener?.('message',event=>this.receive(event));
    }
    frame(){return this.container?.querySelector?.('#'+this.frameId)||
      (typeof document!=='undefined'?document.getElementById(this.frameId):null);}
    async mount(container,context={}){this.container=container;return this.activate(context);}
    status(phase,message=''){
      this.phase=phase;
      const frame=this.frame();frame?.setAttribute?.('aria-busy',String(phase==='loading'));
      if(typeof document==='undefined')return;
      const box=document.getElementById('studio-status-'+this.name);
      const text=document.getElementById('studio-status-text-'+this.name);
      const retry=document.getElementById('studio-retry-'+this.name);
      if(box){box.hidden=phase==='ready'||phase==='idle';box.dataset.phase=phase;}
      if(text)text.textContent=message;
      if(retry){retry.hidden=phase!=='error';retry.onclick=()=>this.activate({songId:this.currentSongId,retry:true});}
    }
    invalidate(songId){if(songId)this.staleSongs.add(songId);}
    async activate({songId=this.currentSongId,retry=false}={}){
      const frame=this.frame();if(!frame)return false;
      songId=songId||'';
      if((songId!==this.currentSongId||retry||this.staleSongs.has(songId))&&this.dirty){
        this.status('blocked','Save your changes in this editor before switching or refreshing.');return false;
      }
      if(this.currentSongId===songId&&!retry&&!this.staleSongs.has(songId)&&this.phase!=='idle')return true;
      clearTimeout(this.timer);
      this.currentSongId=songId;this.requestId=Date.now().toString(36)+'-'+(++sequence);
      this.status('loading','Opening '+(this.name==='lyric'?'Lyric Editor':'Motion Design')+'…');
      const target=this.path(songId),separator=target.includes('?')?'&':'?';
      frame.dataset.loadedSongId=songId;
      frame.src=target+separator+'_workspace='+encodeURIComponent(this.requestId);
      frame.onerror=()=>this.fail('The editor page could not load. Check the service and retry.');
      this.timer=setTimeout(()=>this.fail('The editor has not finished loading. Check the service or sign-in, then retry.'),30000);
      this.timer?.unref?.();
      return true;
    }
    fail(message){clearTimeout(this.timer);this.status('error',message);}
    receive(event){
      const data=event.data,frame=this.frame();
      if(!frame||event.origin!==origin()||event.source!==frame.contentWindow||
        !data||data.studio!==this.name||data.requestId!==this.requestId)return false;
      if(data.type==='M2V_STUDIO_READY'){
        if(!this.currentSongId){clearTimeout(this.timer);this.status('ready');}return true;
      }
      if(data.type==='M2V_STUDIO_LOADED'&&typeof data.songId==='string'){
        this.currentSongId=data.songId;frame.dataset.loadedSongId=data.songId;
      }
      if(data.songId!==this.currentSongId)return false;
      if(data.type==='M2V_STUDIO_ERROR'){this.fail(data.message||'Unable to load this song. Retry opening the editor.');return true;}
      if(!['M2V_STUDIO_LOADED','M2V_STUDIO_STATE','M2V_STUDIO_SAVED'].includes(data.type))return false;
      this.dirty=Boolean(data.dirty);
      if(data.type==='M2V_STUDIO_LOADED'){
        clearTimeout(this.timer);this.staleSongs.delete(data.songId);this.status('ready');
      }
      if(!this.dirty&&this.phase==='blocked')this.status('ready');
      if(typeof window!=='undefined'){
        window.m2vStore?.setEditorState?.(this.name,{songId:data.songId,dirty:this.dirty,saving:Boolean(data.saving)});
        if(!Object.values(window.m2vStudios||{}).some(editor=>editor.dirty)){
          const notice=typeof document!=='undefined'?document.getElementById('workspace-notice'):null;
          if(notice)notice.hidden=true;
        }
        if(this.name==='lyric'&&data.type==='M2V_STUDIO_SAVED'){
          window.m2vStore?.setLyricVersion?.(data.songId,data.version||null);
          window.m2vStudios?.motion.invalidate(data.songId);
        }
      }
      return true;
    }
    pause(){this.frame()?.contentWindow?.postMessage({type:'M2V_STUDIO_PAUSE'},origin());}
    destroy(){
      clearTimeout(this.timer);const frame=this.frame();
      frame?.contentWindow?.postMessage({type:'M2V_STUDIO_DESTROY'},origin());
      if(frame){frame.src='about:blank';delete frame.dataset.loadedSongId;}
      this.currentSongId=null;this.requestId='';this.dirty=false;this.staleSongs.clear();this.status('idle');
    }
  }
  class LyricStudioAdapter extends StudioAdapter{
    constructor(){super('lyric','iframe-lyric-editor',id=>id?'/lyric-editor/'+encodeURIComponent(id):'/lyric-editor');}
  }
  class MotionStudioAdapter extends StudioAdapter{
    constructor(){super('motion','iframe-motion-studio',id=>id?'/motion-studio?project='+encodeURIComponent(id):'/motion-studio');}
  }
  const m2vStudios={lyric:new LyricStudioAdapter(),motion:new MotionStudioAdapter()};
  if(typeof window!=='undefined'){
    window.m2vStudios=m2vStudios;
    window.m2vCanOpenStudio=(studio,songId)=>{
      const blocked=Object.values(m2vStudios).find(editor=>editor.dirty&&editor.currentSongId!==(songId||''));
      const lyrics=m2vStudios.lyric;
      if(blocked){blocked.status('blocked','Save your changes before switching to another song.');window.m2vNavigationNotice?.('Save your changes before switching to another song.',blocked.name);return false;}
      if(studio==='motion'&&lyrics.dirty&&lyrics.currentSongId===songId){
        lyrics.status('blocked','Save your lyric changes before opening Motion Design.');window.m2vNavigationNotice?.('Save your lyric changes before opening Motion Design.','lyric');return false;
      }
      return true;
    };
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={LyricStudioAdapter,MotionStudioAdapter,m2vStudios};
})();
