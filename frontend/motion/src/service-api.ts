/** Motion Studio uses the same authenticated backend as the lyric editor. */
declare global {
 interface Window {
  M2V_API_BASE?: string;
  m2vAuth?: {ready?: Promise<unknown>; getIdToken(forceRefresh?: boolean): Promise<string|null>};
  m2vServiceAuthReady?: Promise<void>;
 }
}

export function cloudService(): boolean {
 return Boolean(window.M2V_API_BASE) || /(?:fovea\.si|pages\.dev|web\.app|hf\.space)$/.test(location.hostname);
}

export function serviceUrl(path: string): string {
 const base=window.M2V_API_BASE?.replace(/\/+$/,'') ||
  (cloudService()&&!location.hostname.endsWith('hf.space')?'https://lucazhou-suno2mv-api.hf.space':location.origin);
 return new URL(path,base).href;
}

function script(src: string): Promise<void> {
 return new Promise((resolve,reject)=>{
  const tag=document.createElement('script');tag.src=src;tag.onload=()=>resolve();
  tag.onerror=()=>reject(new Error('登录服务加载失败，请检查网络后刷新'));document.head.append(tag);
 });
}

async function authentication(): Promise<void> {
 if(!cloudService())return;
 if(!window.m2vAuth){
  window.m2vServiceAuthReady ||= (async()=>{
   await script('https://www.gstatic.com/firebasejs/10.14.1/firebase-app-compat.js');
   await script('https://www.gstatic.com/firebasejs/10.14.1/firebase-auth-compat.js');
   await script('/firebase-config.js?v=20261013_motion');
  })();
  await window.m2vServiceAuthReady;
 }
 await window.m2vAuth?.ready;
}

export async function serviceFetch(path: string, options: RequestInit={}): Promise<Response> {
 const url=serviceUrl(path);
 // Never attach account tokens to an unrelated CDN or external media URL.
 const ownBackend=new URL(url).origin===new URL(serviceUrl('/')).origin;
 const authenticated=cloudService()&&ownBackend;
 const headers=new Headers(options.headers);
 if(authenticated){
  await authentication();
  const token=await window.m2vAuth?.getIdToken(false);
  if(!token)throw new Error('请先在首页登录，再打开动效工作室');
  headers.set('Authorization','Bearer '+token);
 }
 let response=await fetch(url,{...options,headers});
 if(authenticated&&response.status===401){
  const token=await window.m2vAuth?.getIdToken(true);
  if(!token)throw new Error('登录已过期，请重新登录');
  headers.set('Authorization','Bearer '+token);
  response=await fetch(url,{...options,headers});
 }
 return response;
}

export async function serviceJson(path: string, options: RequestInit={}): Promise<any> {
 const response=await serviceFetch(path,options);
 if(!response.headers.get('content-type')?.includes('json')){
  throw new Error(`后端返回了非 JSON 响应（HTTP ${response.status}），请检查后端地址与服务状态`);
 }
 const result=await response.json();
 if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:JSON.stringify(result.detail||result));
 return result;
}

export function motionUrl(path: string): string {
 return (cloudService()?'/api/cloud-motion/':'/api/motion/')+path;
}

export function motionJson(path: string,method='GET',body?: unknown): Promise<any> {
 return serviceJson(motionUrl(path),{method,headers:body?{'Content-Type':'application/json'}:undefined,
  body:body?JSON.stringify(body):undefined});
}

export async function downloadService(path:string): Promise<void> {
 const response=await serviceFetch(path);
 if(!response.ok)throw new Error(`视频下载失败（HTTP ${response.status}）`);
 const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');
 link.href=url;link.download='motion-studio.mp4';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
