import {cloudService, serviceJson} from './service-api';

/** Encoding and archive/charging are separate stages. Retry this with the same
 * blob and request ID; an archive failure must not restart a cloud render. */
export async function archiveBrowserVideo(blob:Blob, input:{
 projectId:string;requestId:string;acceptedCost:number;title:string;aspect:'9:16'|'16:9';
}):Promise<void>{
 if(!cloudService())return;
 const query=new URLSearchParams({project_id:input.projectId,request_id:input.requestId,
  accepted_cost:String(input.acceptedCost),title:input.title.slice(0,255),aspect:input.aspect});
 await serviceJson('/api/cloud-motion/browser-exports?'+query,{
  method:'POST',headers:{'Content-Type':'video/mp4'},body:blob,
 });
}
