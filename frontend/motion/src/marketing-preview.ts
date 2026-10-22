import {RemotionPreview} from './remotion-preview';
import {demoScene,type DemoMode} from './marketing-demo';

/** Same LyricVideo/RemotionPreview used by Studio. No auth, audio, APIs or export. */
export function mountPreview(host:HTMLElement,initialMode:DemoMode){
  let engine:RemotionPreview|null=null,mode=initialMode,frame=0,playing=false,elapsed=2.4,origin=0,disposed=false;
  const sampleLength=18;
  const canvas=document.createElement('canvas');
  canvas.setAttribute('aria-hidden','true');
  const fail=(error:Error)=>{
    playing=false;cancelAnimationFrame(frame);host.dataset.state='error';
    host.replaceChildren();
    const message=document.createElement('p');message.className='preview-error';message.setAttribute('role','alert');
    message.textContent='Preview could not load. Reload the page or open the studio to try your song.';
    host.append(message);console.warn('Public preview unavailable',error.message);
  };
  function draw(){
    if(!playing||disposed)return;
    const t=(elapsed+(performance.now()-origin)/1000)%sampleLength;
    engine?.renderAt(t);frame=requestAnimationFrame(draw);
  }
  function pause(){
    if(playing)elapsed=(elapsed+(performance.now()-origin)/1000)%sampleLength;
    playing=false;cancelAnimationFrame(frame);
  }
  function show(next:DemoMode){
    pause();mode=next;engine?.dispose();host.replaceChildren(canvas);host.dataset.state='loading';
    const scene=demoScene(mode);host.style.aspectRatio=`${scene.width} / ${scene.height}`;
    engine=new RemotionPreview(canvas,scene.project,scene.options,scene.width,scene.height,fail);
    elapsed=mode==='poster'?4.2:2.4;engine.renderAt(elapsed);
  }
  const ready=new MutationObserver(()=>{
    if(host.querySelector('svg text'))host.dataset.state='ready';
  });
  ready.observe(host,{childList:true,subtree:true});
  show(mode);
  const visibility=()=>{if(document.hidden)pause();};
  document.addEventListener('visibilitychange',visibility);
  return {
    show,
    play(){if(disposed||host.dataset.state==='error')return;pause();elapsed=0;origin=performance.now();playing=true;draw();},
    pause,
    dispose(){disposed=true;pause();ready.disconnect();engine?.dispose();document.removeEventListener('visibilitychange',visibility);}
  };
}
