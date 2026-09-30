import { MotionEngine } from './engine';
import { normalizeProject, renderSize, type Options } from './model';
declare global { interface Window { motionReady:Promise<void>; motionFrame:(t:number)=>Uint8Array; } }
let engine:MotionEngine;
window.motionReady=(async()=>{
  const response=await fetch('/job'); if(!response.ok)throw new Error('无法读取渲染任务');
  const job=await response.json();await document.fonts.ready;
  const {width,height}=renderSize(job.options);
  engine=new MotionEngine(document.getElementById('stage') as HTMLCanvasElement,normalizeProject(job.project),job.options as Options,width,height);
})();
window.motionFrame=(t:number)=>{engine.renderAt(t,false);return engine.readPixels();};
