import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {selectComposition,renderMedia,makeCancelSignal} from '@remotion/renderer';
const [jobFile,outFile]=process.argv.slice(2);
if(!jobFile||!outFile)throw new Error('缺少渲染任务或输出路径');
const job=JSON.parse(fs.readFileSync(jobFile,'utf8'));
const {start,length,project,options,audioPath}=job;
if(!Number.isFinite(start)||start<0||!Number.isFinite(length)||length<=0)throw new Error('导出时间无效');
const serveUrl=fileURLToPath(new URL('../../local/remotion',import.meta.url));
if(!fs.existsSync(path.join(serveUrl,'index.html')))throw new Error('请先构建 Remotion 前端');
const browserExecutable=process.env.CHROME_PATH||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':'/usr/bin/chromium');
const inputProps={project,options,timeOffset:start,renderLength:length};
const tmp=fs.mkdtempSync(path.join(path.dirname(outFile),'remotion-'));
const silent=path.join(tmp,'silent.mp4');
const {cancel,cancelSignal}=makeCancelSignal();let mux;
process.on('SIGTERM',()=>{cancel();mux?.kill('SIGTERM');});
try{
 const composition=await selectComposition({serveUrl,id:'LyricPoster',inputProps,browserExecutable,logLevel:'error'});
 let previous=-1;
 await renderMedia({serveUrl,composition,inputProps,browserExecutable,outputLocation:silent,codec:'h264',pixelFormat:'yuv420p',crf:18,concurrency:2,logLevel:'error',cancelSignal,onProgress:({renderedFrames})=>{
   if(renderedFrames!==previous&&(renderedFrames%15===0||renderedFrames===composition.durationInFrames)){previous=renderedFrames;process.stdout.write(`PROGRESS ${renderedFrames}/${composition.durationInFrames}\n`);}
 }});
 await new Promise((resolve,reject)=>{
   mux=spawn('ffmpeg',['-y','-v','error','-i',silent,'-ss',String(start),'-t',String(length),'-i',audioPath,'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-shortest','-movflags','+faststart',outFile]);
   let error='';mux.stderr.on('data',d=>error+=d);mux.on('error',reject);mux.on('close',code=>code===0?resolve():reject(new Error(error||`音频合成失败 ${code}`)));
 });
 process.stdout.write(`PROGRESS ${composition.durationInFrames}/${composition.durationInFrames}\n`);
}finally{fs.rmSync(tmp,{recursive:true,force:true});}
