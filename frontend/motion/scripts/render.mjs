import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { chromium } from 'playwright-core';
import { WebSocketServer } from 'ws';

const motionDir=fileURLToPath(new URL('../',import.meta.url));
const localDir=path.resolve(motionDir,'../local');
const [jobFile,outFile]=process.argv.slice(2);
if(!jobFile||!outFile)throw new Error('用法: node scripts/render.mjs job.json output.mp4');
const job=JSON.parse(fs.readFileSync(jobFile,'utf8'));
const {start,length,options,audioPath}=job;
const short=options.height||720,long=Math.round(short*16/9);
const width=options.aspect==='9:16'?short:long,height=options.aspect==='9:16'?long:short,fps=30,total=Math.round(length*fps);
if(!Number.isFinite(start)||!Number.isFinite(length)||length<=0)throw new Error('渲染任务缺少有效范围或导演方案');
const chrome=process.env.CHROME_PATH||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':'/usr/bin/chromium');
const source={
  '/motion_render.html': ['motion_render.html','text/html; charset=utf-8'],
  '/motion/render-entry.js':['motion/render-entry.js','text/javascript; charset=utf-8'],
};
let frames=0,browser,ff,server;
const timeout=setTimeout(async()=>{process.stderr.write('渲染任务超过时限\n');ff?.kill('SIGTERM');await browser?.close().catch(()=>{});process.exit(1);},Math.max(120000,length*30000));
timeout.unref();
process.once('SIGTERM',async()=>{ff?.kill('SIGTERM');await browser?.close().catch(()=>{});process.exit(143);});
try{
  server=http.createServer((req,res)=>{
    if(req.url==='/job'){res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({project:job.project,options}));return;}
    const entry=source[req.url];if(!entry){res.writeHead(404);res.end();return;}
    const file=path.join(localDir,entry[0]);res.writeHead(200,{'Content-Type':entry[1]});fs.createReadStream(file).pipe(res);
  });
  const wss=new WebSocketServer({server,path:'/frames',maxPayload:width*height*4+1024});
  server.listen(0,'127.0.0.1');await once(server,'listening');
  ff=spawn('ffmpeg',['-y','-hide_banner','-loglevel','error','-f','rawvideo','-pix_fmt','rgba','-s',`${width}x${height}`,'-r',String(fps),'-i','pipe:0',
    '-ss',String(start),'-t',String(length),'-i',audioPath,'-vf','vflip,scale=out_color_matrix=bt709,setparams=color_primaries=bt709:color_trc=bt709',
    '-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-shortest','-movflags','+faststart',outFile],{stdio:['pipe','ignore','pipe']});
  let ffError='';ff.stderr.on('data',d=>ffError+=d.toString());
  const ended=new Promise((resolve,reject)=>{ff.once('error',reject);ff.once('close',code=>code===0?resolve():reject(new Error(`FFmpeg 退出码 ${code}: ${ffError.slice(-2000)}`)));});
  ended.catch(()=>{});
  const streamDone=new Promise((resolve,reject)=>wss.on('connection',socket=>{
    socket.on('message',data=>{
      if(data.length!==width*height*4){socket.close();reject(new Error('渲染帧大小错误'));return;}
      if(frames>=total){socket.close();return;}
      socket.pause();ff.stdin.write(data,err=>{
        if(err){reject(err);return;}frames++;process.stdout.write(`PROGRESS ${frames}/${total}\n`);
        socket.send(String(frames));socket.resume();if(frames===total){ff.stdin.end();resolve();}
      });
    });socket.once('error',reject);socket.once('close',()=>{if(frames<total)reject(new Error('渲染连接提前断开'));});
  }));
  streamDone.catch(()=>{});
  browser=await chromium.launch({executablePath:chrome,headless:true,args:['--enable-webgl','--use-gl=angle','--use-angle=swiftshader']});
  const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
  page.on('pageerror',e=>process.stderr.write(`PAGE ERROR ${e.message}\n`));
  await page.goto(`http://127.0.0.1:${server.address().port}/motion_render.html`,{waitUntil:'load'});
  await page.evaluate(()=>window.motionReady);
  await page.evaluate(async({start,total,fps})=>{
    const ws=new WebSocket(`ws://${location.host}/frames`);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
    for(let i=0;i<total;i++){
      const ack=new Promise((resolve,reject)=>{ws.onmessage=resolve;ws.onerror=reject;});
      ws.send(window.motionFrame(start+i/fps));await ack;
    }
    ws.close();
  },{start,total,fps});
  await streamDone;await ended;
  if(!fs.existsSync(outFile)||fs.statSync(outFile).size<1000)throw new Error('没有生成有效视频');
}catch(e){ff?.kill('SIGTERM');try{fs.unlinkSync(outFile);}catch{}throw e;}
finally{clearTimeout(timeout);await browser?.close();await new Promise(resolve=>server?.close(resolve)??resolve());}
