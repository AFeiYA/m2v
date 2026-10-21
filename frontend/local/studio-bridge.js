/** Readiness and saved/dirty events; navigation remains owned by the parent. */
(() => {
  const studio=document.documentElement.dataset.studio;
  const requestId=new URLSearchParams(location.search).get('_workspace');
  let songId='',dirty=false,saving=false;
  // The workspace uses account-scoped task IDs, including on localhost. Standalone
  // editors keep their local-directory mode; a saved login alone never selects it.
  if(window.parent!==window){
    try{
      if(window.parent.m2vWorkspaceApi){
        window.M2V_API_BASE=window.parent.m2vWorkspaceApi();
        window.M2V_FORCE_CLOUD=true;
      }
      if(window.parent.m2vAuth)window.m2vAuth=window.parent.m2vAuth;
    }catch(_){}
  }
  function send(type,extra={}){
    if(!requestId||!studio||window.parent===window)return;
    window.parent.postMessage({type,studio,requestId,songId,dirty,saving,...extra},location.origin);
  }
  window.m2vStudioBridge={
    state(id,changed,busy=false){
      if(songId===id&&dirty===Boolean(changed)&&saving===Boolean(busy))return;
      songId=id;dirty=Boolean(changed);saving=Boolean(busy);send('M2V_STUDIO_STATE');
    },
    loaded(id,changed=false,title=''){songId=id;dirty=Boolean(changed);send('M2V_STUDIO_LOADED',{title});},
    saved(id,changed=false,version=null){songId=id;dirty=Boolean(changed);send('M2V_STUDIO_SAVED',{version});},
    error(id,message){songId=id;send('M2V_STUDIO_ERROR',{message:String(message).slice(0,300)});},
  };
  send('M2V_STUDIO_READY');
})();
