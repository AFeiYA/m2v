const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const esbuild=require('../motion/node_modules/esbuild');
const code=esbuild.transformSync(fs.readFileSync(path.join(__dirname,'../motion/src/lyric-video.tsx'),'utf8'),{loader:'tsx',format:'cjs'}).code;
for(const mode of ['kinetic','tv','apple'])test(`${mode} preview keeps the same React hook sequence before and after layout becomes ready`,()=>{
 let ready=false,index=0,calls=[];
 const hook=name=>calls.push(name);
 const palette={background:'#000',accent:'#ff0',foreground:'#fff'};
 const react={createElement:()=>({}),useId:()=>{hook('id');return 'id';},useEffect:()=>hook('effect'),useMemo:fn=>{hook('memo');return fn();},
  useState:initial=>{hook('state');const slot=index++;return [slot===0?0:ready&&slot===1&&mode==='kinetic'?[]:ready&&slot===2&&mode==='tv'?{palette}:ready&&slot===3&&mode==='apple'?{palette}:null,()=>{}];}};
 const imports={react,remotion:{AbsoluteFill:'fill',Img:'img',useCurrentFrame:()=>0,useVideoConfig:()=>({fps:30,width:720,height:1280}),useDelayRender:()=>({delayRender:()=>0,continueRender(){},cancelRender(){}})},
  './model':{featuresAt:()=>({kick:0,beat:0})},'./poster-layout':{visiblePosterAt:()=>null,stageAt:()=>null},
  './song-layout':{songLayoutAt:()=>({cover:false,alpha:0,texts:[]}),coverPlacement:()=>null},
  './stream-layout':{ktvDualStateAt:()=>({upper:null,lower:null}),appleScrollStateAt:()=>({items:[]})},'./karaoke':{}};
 const context={module:{exports:{}},require:name=>imports[name]};vm.runInNewContext(code,context);
 const render=context.module.exports.LyricVideo,props={project:{duration:2},options:{visualMode:mode}};
 render(props);const first=[...calls];ready=true;index=0;calls=[];render(props);
 assert.deepEqual(calls,first);
});
