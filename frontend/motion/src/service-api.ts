/** Motion Studio uses the same authenticated backend as the lyric editor. */
declare global {
 interface Window {
  m2vSongPicker?: {mount(select:HTMLElement,request:(path:string)=>Promise<any>,choose:(id:string)=>Promise<boolean>):unknown};
  M2V_API_BASE?: string;
  m2vAuth?: {ready?: Promise<unknown>; getIdToken(forceRefresh?: boolean): Promise<string|null>};
  m2vServiceAuthReady?: Promise<void>;
  m2vCache?: {getMedia(uid:string,task:string,type:string,version:string):Promise<Blob|null>;saveMedia(uid:string,task:string,type:string,blob:Blob,version:string):Promise<unknown>};
  m2vMediaCacheReady?:Promise<void>;
 }
}

export async function serviceAudio(path:string,task:string,identity?:{uid:string;version:string}):Promise<{blob:Blob;cached:boolean}>{
 await authentication();
 const checkAccount=async()=>{
  const token=await window.m2vAuth?.getIdToken(false);
  if(!token)throw new Error('Sign in before loading audio.');
  if(identity){let uid='';try{uid=JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))).sub;}catch{}
   if(uid!==identity.uid)throw new Error('Account changed. Please select your song again.');}
 };
 await checkAccount();
 if(!window.m2vCache){
  try{window.m2vMediaCacheReady ||= script('/static/cache.js');await window.m2vMediaCacheReady;}catch{/* Cache failure must not prevent playback. */}
 }
 const cache=window.m2vCache, key=serviceUrl('/');
 const type='motion-original:'+key;
 const cached=identity&&cache?await cache.getMedia(identity.uid,task,type,identity.version):null;
 if(cached){await checkAccount();return {blob:cached,cached:true};}
 const response=await serviceFetch(path);
 if(!response.ok)throw new Error(`Unable to load original audio (HTTP ${response.status}).`);
 const contentType=response.headers.get('content-type')||'';
 if(!/^(audio\/|application\/octet-stream)/i.test(contentType))throw new Error('The server did not return audio. Nothing was cached.');
 const blob=await response.blob();
 if(!blob.size)throw new Error('Audio is empty. Nothing was cached.');
 await checkAccount();
 if(identity&&cache)await cache.saveMedia(identity.uid,task,type,blob,identity.version);
 return {blob,cached:false};
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
  tag.onerror=()=>reject(new Error('Unable to load sign-in. Check your connection and refresh.'));document.head.append(tag);
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
  if(!token)throw new Error('Sign in on the home page before opening Motion Studio.');
  headers.set('Authorization','Bearer '+token);
 }
 let response=await fetch(url,{...options,headers});
 if(authenticated&&response.status===401){
  const token=await window.m2vAuth?.getIdToken(true);
  if(!token)throw new Error('Your session expired. Please sign in again.');
  headers.set('Authorization','Bearer '+token);
  response=await fetch(url,{...options,headers});
 }
 return response;
}

export async function serviceJson(path: string, options: RequestInit={}): Promise<any> {
 const response=await serviceFetch(path,options);
 if(!response.headers.get('content-type')?.includes('json')){
  throw new Error(`The backend returned a non-JSON response (HTTP ${response.status}). Check its address and status.`);
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

export async function downloadService(path:string,filename='motion-studio.mp4'): Promise<void> {
 const backend=new URL(serviceUrl('/')),target=new URL(serviceUrl(path));
 if(target.origin!==backend.origin)throw new Error('Invalid video download address.');
 let url=target.href;
 if(cloudService()){
  const match=target.pathname.match(/^\/api\/cloud-motion\/render\/([a-f0-9]{32,64})\/download$/);
  if(!match)throw new Error('Open My Exports to download this video.');
  await authentication();
  const account=async()=>{
   const token=await window.m2vAuth?.getIdToken(false);
   if(!token)return null;
   try{return JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))).sub||token;}catch{return token;}
  };
  const owner=await account();
  const data=await serviceJson('/api/exports/'+match[1]+'/access?preview=false');
  if(!owner||await account()!==owner)throw new Error('Account changed. Open My Exports to download your video.');
  if(typeof data.url!=='string'||!data.url)throw new Error('Video link is unavailable. Please retry from My Exports.');
  url=new URL(data.url,backend).href;
  if(!/^https?:$/.test(new URL(url).protocol))throw new Error('Invalid video download address.');
  filename=data.filename||filename;
 }
 // Let the browser download manager stream to disk. Never buffer an MP4 Blob.
 const link=document.createElement('a');link.href=url;link.download=filename;
 document.body.appendChild(link);link.click();link.remove();
}
