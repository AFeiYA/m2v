import React, {useEffect,useMemo,useState} from 'react';
import {AbsoluteFill,useCurrentFrame,useVideoConfig,useDelayRender} from 'remotion';
import {featuresAt,type Project,type Options} from './model';
import {compilePoster,canvasMeasure,POSTER_FONT,posterNodeState,posterOpacity,type CompiledPoster} from './poster-layout';
export type VideoProps={project:Project;options:Options;timeOffset?:number;renderLength?:number};
export const LyricVideo:React.FC<VideoProps>=({project,timeOffset=0})=>{
 const frame=useCurrentFrame(),{fps,width,height}=useVideoConfig(),t=timeOffset+frame/fps;
 const {delayRender,continueRender,cancelRender}=useDelayRender();
 const [handle]=useState(()=>delayRender('等待字体与海报排版'));
 const [layouts,setLayouts]=useState<CompiledPoster[]|null>(null);
 useEffect(()=>{let active=true;(async()=>{await document.fonts.ready;if(!active)return;
  const context=document.createElement('canvas').getContext('2d')!;
  const result=project.lines.map(line=>compilePoster(line,project.motion_plan?.cues.find(c=>c.line_id===line.id),width,height,canvasMeasure(context)));
  setLayouts(result);continueRender(handle);
 })().catch(cancelRender);return()=>{active=false;};},[project,width,height,handle,continueRender,cancelRender]);
 const plan=layouts?.find(p=>t>=p.start&&t<p.end);
 const feature=useMemo(()=>featuresAt(project,t),[project,t]);
 if(!plan)return <AbsoluteFill style={{background:'#eeeee6',fontFamily:POSTER_FONT,display:'flex',justifyContent:'center',alignItems:'center',color:'#20261e',fontWeight:800,fontSize:Math.min(width*.05,height*.08),padding:'8%',textAlign:'center'}}>{project.title}</AbsoluteFill>;
 const complete=Math.max(...plan.nodes.map(n=>n.settled));
 return <AbsoluteFill style={{background:plan.background}}><svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{overflow:'hidden'}} aria-label="歌词海报动画">
  <g opacity={posterOpacity(plan,t)}>
   {plan.motif==='rings'&&[0,1,2].map(i=><ellipse key={i} cx={width*.81} cy={height*.20} rx={width*(.08+i*.012)} ry={height*(.12+i*.017)} stroke={plan.accent} strokeWidth={height*.003} fill="none"/>)}
   {plan.nodes.map((n,i)=>{const state=posterNodeState(n,t,height);const holding=t>=complete;
    const drift=holding&&n.hold==='drift'?Math.sin((t-complete)*1.4)*height*.002:0;
    const pulse=holding&&n.beat_reaction==='pulse'?1+Math.min(1,feature.kick||feature.beat*.3)*.012:1;
    const cx=n.x+n.width/2,cy=n.y+n.height/2,scale=state.scale*pulse;
    return <g key={i} opacity={state.alpha} transform={`translate(${cx+state.dx} ${cy+state.dy+drift}) scale(${scale}) translate(${-cx} ${-cy})`}>
     {n.rows.map((row,j)=><text key={j} x={row.x} y={row.y} fill={n.color} fontSize={n.fontSize} fontWeight={n.weight} fontFamily={POSTER_FONT} style={{whiteSpace:'pre'}}>{row.text}</text>)}
    </g>;
   })}
  </g>
 </svg></AbsoluteFill>;
};
