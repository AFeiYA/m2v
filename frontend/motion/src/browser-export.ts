import {cloudService, serviceJson} from './service-api';

/** Encoding and archive/charging are separate stages. Retry this with the same
 * blob and request ID; an archive failure must not restart a cloud render. */
export async function archiveBrowserVideo(blob:Blob, input:{
 projectId:string;requestId:string;acceptedCost:number;title:string;aspect:'9:16'|'16:9';
}, options:{signal?:AbortSignal;timeoutMs?:number}={}):Promise<void>{
 if(!cloudService())return;
 if(options.signal?.aborted)throw new Error('Upload cancelled. Cloud saving may be unconfirmed; retry the same video to check.');
 const query=new URLSearchParams({project_id:input.projectId,request_id:input.requestId,
  accepted_cost:String(input.acceptedCost),title:input.title.slice(0,255),aspect:input.aspect});
 const controller=new AbortController();
 let timer:ReturnType<typeof setTimeout>|undefined;
 let cancel:()=>void=()=>{};
 const interrupted=new Promise<never>((_,reject)=>{
  cancel=()=>{controller.abort();reject(new Error('Upload cancelled. Cloud saving may be unconfirmed; retry the same video to check.'));};
  options.signal?.addEventListener('abort',cancel,{once:true});
  timer=setTimeout(()=>{
   controller.abort();
   reject(new Error('Cloud upload timed out. Retry saving this video; it will not be rendered or charged twice.'));
  },options.timeoutMs??300_000);
 });
 try{
  // Bound authentication and response reading too, even if either ignores abort.
  await Promise.race([interrupted,serviceJson('/api/cloud-motion/browser-exports?'+query,{
   method:'POST',headers:{'Content-Type':'video/mp4'},body:blob,signal:controller.signal,
  })]);
 }finally{
  clearTimeout(timer);
  options.signal?.removeEventListener('abort',cancel);
 }
}
