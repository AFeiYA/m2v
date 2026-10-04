import React, {useEffect,useMemo,useState} from 'react';
import {AbsoluteFill,useCurrentFrame,useVideoConfig,useDelayRender} from 'remotion';
import {featuresAt,type Project,type Options} from './model';
import {compileSongPosters,stageAt,visiblePosterAt,canvasMeasure,POSTER_FONT,posterNodeState,posterHoldState,posterExitOpacity,posterRings,compileIntroTitle,introTitleState,type CompiledPoster,type CompiledIntroTitle} from './poster-layout';
import {compileSongLayout,songLayoutAt,songTextColor,type SongLayout} from './song-layout';
export type VideoProps={project:Project;options:Options;timeOffset?:number;renderLength?:number};
export const LyricVideo:React.FC<VideoProps>=({project,timeOffset=0})=>{
 const frame=useCurrentFrame(),{fps,width,height}=useVideoConfig(),t=timeOffset+frame/fps;
 const {delayRender,continueRender,cancelRender}=useDelayRender();
 const [handle]=useState(()=>delayRender('等待字体与海报排版'));
 const [layouts,setLayouts]=useState<CompiledPoster[]|null>(null);
 const [songLayout,setSongLayout]=useState<SongLayout|null>(null);
 const [intro,setIntro]=useState<CompiledIntroTitle|null>(null);
 useEffect(()=>{let active=true;(async()=>{await document.fonts.ready;if(!active)return;
  const context=document.createElement('canvas').getContext('2d')!;
  const measure=canvasMeasure(context);
  const result=compileSongPosters(project,width,height,measure);
  const introResult=project.song_identity?null:compileIntroTitle(project,width,height,measure);
  setSongLayout(compileSongLayout(project,width,height,measure));
  setLayouts(result);setIntro(introResult);continueRender(handle);
 })().catch(cancelRender);return()=>{active=false;};},[project,width,height,handle,continueRender,cancelRender]);
 const plan=layouts?visiblePosterAt(layouts,t):undefined;
 const stage=layouts?stageAt(layouts,t):undefined;
 const feature=useMemo(()=>featuresAt(project,t),[project,t]);
 if(!stage)return <AbsoluteFill style={{background:'#0d120a'}}/>;
 const complete=plan?Math.max(...plan.nodes.map(n=>n.settled)):Infinity;
 const introState=intro?introTitleState(intro,t,height):null;
 const songFrame=songLayoutAt(songLayout,t);
 const pulse=1+(feature.kick||feature.beat*.3)*.012;
 return <AbsoluteFill style={{background:stage.background}}><svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{overflow:'hidden'}} aria-label="歌词海报动画">
  <g>
   {stage.motif==='rings'&&posterRings(width,height).map((ring,i)=><ellipse key={i} cx={ring.cx} cy={ring.cy} rx={ring.rx} ry={ring.ry} opacity={ring.opacity} stroke={stage.accent} strokeWidth={Math.min(width,height)*.003} fill="none"/>)}
   {introState&&introState.alpha>0&&intro&&<g opacity={introState.alpha} transform={`translate(${intro.cx} ${intro.cy+introState.dy}) scale(${introState.scale*pulse}) translate(${-intro.cx} ${-intro.cy})`}>
    <text x={intro.x} y={intro.y} fill={intro.color} fontSize={intro.fontSize} fontWeight={intro.weight} fontFamily={POSTER_FONT} style={{whiteSpace:'pre'}}>{intro.text}</text>
   </g>}
   <g>{!songFrame.cover&&plan?.nodes.map((n,i)=>{const state=posterNodeState(n,t,height);
    const {drift,pulse:nodePulse}=posterHoldState(n,t,complete,width,height,feature.kick||feature.beat*.3);
    const cx=n.x+n.width/2,cy=n.y+n.height/2,scale=state.scale*nodePulse;
    return <g key={i} opacity={state.alpha*(plan?posterExitOpacity(plan,n,t):0)} transform={`translate(${cx+state.dx} ${cy+state.dy+drift}) scale(${scale}) translate(${-cx} ${-cy})`}>
     {n.rows.map((row,j)=><text key={j} x={row.x} y={row.y} fill={n.color} fontSize={n.fontSize} fontWeight={n.weight} fontFamily={POSTER_FONT} style={{whiteSpace:'pre'}}>{row.text}</text>)}
    </g>;
   })}
  </g>
   <g opacity={songFrame.alpha}>
    {songFrame.rule&&<line x1={width*.07} x2={width*.93} y1={height*(songFrame.cover?.3:.125)} y2={height*(songFrame.cover?.3:.125)} stroke={stage.accent} strokeWidth={Math.max(1,Math.min(width,height)*.0015)} opacity={.5}/>}
    {songFrame.texts.map((item,i)=><text key={i} x={item.x} y={item.y} fill={songTextColor(stage.background)} fontSize={item.fontSize} fontWeight={item.weight} textAnchor={item.anchor} fontFamily={POSTER_FONT}>{item.text}</text>)}
    {songFrame.section&&<text x={width*.07} y={height*.94} fill={stage.accent} fontSize={Math.min(width,height)*.022} fontFamily={POSTER_FONT}>{songFrame.section}</text>}
   </g></g>
 </svg></AbsoluteFill>;
};
