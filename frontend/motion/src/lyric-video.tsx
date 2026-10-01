import React, {useEffect,useMemo,useState} from 'react';
import {AbsoluteFill,useCurrentFrame,useVideoConfig,useDelayRender} from 'remotion';
import {featuresAt,type Project,type Options} from './model';
import {compileSongPosters,stageAt,visiblePosterAt,canvasMeasure,POSTER_FONT,posterNodeState,posterHoldState,posterExitOpacity,posterRings,type CompiledPoster} from './poster-layout';
export type VideoProps={project:Project;options:Options;timeOffset?:number;renderLength?:number};
export const LyricVideo:React.FC<VideoProps>=({project,timeOffset=0})=>{
 const frame=useCurrentFrame(),{fps,width,height}=useVideoConfig(),t=timeOffset+frame/fps;
 const {delayRender,continueRender,cancelRender}=useDelayRender();
 const [handle]=useState(()=>delayRender('等待字体与海报排版'));
 const [layouts,setLayouts]=useState<CompiledPoster[]|null>(null);
 useEffect(()=>{let active=true;(async()=>{await document.fonts.ready;if(!active)return;
  const context=document.createElement('canvas').getContext('2d')!;
  const result=compileSongPosters(project,width,height,canvasMeasure(context));
  setLayouts(result);continueRender(handle);
 })().catch(cancelRender);return()=>{active=false;};},[project,width,height,handle,continueRender,cancelRender]);
 const plan=layouts?visiblePosterAt(layouts,t):undefined;
 const stage=layouts?stageAt(layouts,t):undefined;
 const feature=useMemo(()=>featuresAt(project,t),[project,t]);
 if(!stage)return <AbsoluteFill style={{background:'#eeeee6'}}/>;
 const complete=plan?Math.max(...plan.nodes.map(n=>n.settled)):Infinity;
 return <AbsoluteFill style={{background:stage.background}}><svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{overflow:'hidden'}} aria-label="歌词海报动画">
  <g>
   {stage.motif==='rings'&&posterRings(width,height).map((ring,i)=><ellipse key={i} cx={ring.cx} cy={ring.cy} rx={ring.rx} ry={ring.ry} opacity={ring.opacity} stroke={stage.accent} strokeWidth={Math.min(width,height)*.003} fill="none"/>)}
   <g>{plan?.nodes.map((n,i)=>{const state=posterNodeState(n,t,height);
    const {drift,pulse}=posterHoldState(n,t,complete,width,height,feature.kick||feature.beat*.3);
    const cx=n.x+n.width/2,cy=n.y+n.height/2,scale=state.scale*pulse;
    return <g key={i} opacity={state.alpha*(plan?posterExitOpacity(plan,n,t):0)} transform={`translate(${cx+state.dx} ${cy+state.dy+drift}) scale(${scale}) translate(${-cx} ${-cy})`}>
     {n.rows.map((row,j)=><text key={j} x={row.x} y={row.y} fill={n.color} fontSize={n.fontSize} fontWeight={n.weight} fontFamily={POSTER_FONT} style={{whiteSpace:'pre'}}>{row.text}</text>)}
    </g>;
   })}
  </g></g>
 </svg></AbsoluteFill>;
};
